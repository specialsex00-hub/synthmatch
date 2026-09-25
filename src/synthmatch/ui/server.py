"""ローカルで動くWeb UI（FastAPI）。`synthmatch ui` で起動する。

録音・照合などの時間がかかる処理は「ジョブ」として裏で動かし、画面から進み具合を見たり中止したりできる。
MIDI やオーディオ機器は同時に1つしか使えないので、ジョブは同時に1つまで。
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import audio
from ..instruments import Instrument, load_instrument, slugify
from ..library import build_library, is_recorded, select_presets
from ..notes import Note
from ..pipeline import default_library_dir, run

STATIC = Path(__file__).parent / "static"


class Cancelled(Exception):
    pass


@dataclass
class Job:
    id: str
    kind: str
    status: str = "running"  # running / done / error / cancelled
    progress: int = 0
    total: int = 0
    message: str = ""
    log: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)  # 途中経過（最近録音した音色など）
    result: dict | None = None
    error: str | None = None
    started: float = field(default_factory=time.time)
    finished: float | None = None
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def check(self) -> None:
        if self._cancel.is_set():
            raise Cancelled()

    def write(self, msg: str) -> None:
        self.check()
        self.message = msg
        self.log.append(msg)
        del self.log[:-200]

    def public(self) -> dict:
        return {
            k: getattr(self, k)
            for k in ("id", "kind", "status", "progress", "total", "message", "log", "data", "result", "error", "started", "finished")
        }


class Jobs:
    def __init__(self):
        self._lock = threading.Lock()
        self.jobs: dict[str, Job] = {}
        self.current: Job | None = None

    def start(self, kind: str, fn) -> Job:
        with self._lock:
            if self.current and self.current.status == "running":
                raise HTTPException(409, f"別の処理（{self.current.kind}）が実行中です。終わるか中止してから始めてください。")
            job = Job(uuid.uuid4().hex[:12], kind)
            self.jobs[job.id] = job
            self.current = job

        def target():
            try:
                job.result = fn(job)
                job.status = "done"
            except Cancelled:
                job.status = "cancelled"
            except Exception as e:  # noqa: BLE001
                job.status = "error"
                job.error = str(e) or e.__class__.__name__
            finally:
                job.finished = time.time()

        threading.Thread(target=target, daemon=True).start()
        return job

    def get(self, job_id: str) -> Job:
        if job_id not in self.jobs:
            raise HTTPException(404, "ジョブが見つかりません")
        return self.jobs[job_id]


class BuildRequest(BaseModel):
    category: str | None = None
    limit: int | None = None
    ids: list[str] | None = None
    overwrite: bool = False


class TestRequest(BaseModel):
    preset_id: str | None = None


def create_app(root: str | Path = ".") -> FastAPI:
    root = Path(root).resolve()
    inst_dir = root / "instruments"
    lib_root = root / "libraries"
    out_root = root / "out"
    lib_root.mkdir(exist_ok=True)
    out_root.mkdir(exist_ok=True)
    jobs = Jobs()
    app = FastAPI(title="synthmatch")

    def instrument(inst_id: str) -> Instrument:
        path = inst_dir / f"{inst_id}.toml"
        if not path.exists() or path.parent != inst_dir:
            raise HTTPException(404, f"楽器 '{inst_id}' がありません")
        try:
            return load_instrument(path)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"楽器設定を読めません: {e}") from e

    def lib_dir(inst: Instrument) -> Path:
        return root / default_library_dir(inst)

    def url(path: Path) -> str:
        rel = path.resolve().relative_to(root)
        return "/files/" + rel.as_posix()

    # ---- 楽器・機器 ----

    @app.get("/api/instruments")
    def list_instruments():
        out = []
        for path in sorted(inst_dir.glob("*.toml")):
            try:
                inst = load_instrument(path)
            except Exception as e:  # noqa: BLE001
                out.append({"id": path.stem, "name": path.stem, "error": str(e)})
                continue
            out.append(_summary(path.stem, inst, lib_dir(inst)))
        return out

    @app.get("/api/instruments/{inst_id}")
    def instrument_detail(inst_id: str):
        inst = instrument(inst_id)
        return _summary(inst_id, inst, lib_dir(inst))

    @app.get("/api/instruments/{inst_id}/presets")
    def presets(inst_id: str, category: str | None = None, q: str | None = None, recorded: bool | None = None, limit: int = 300):
        inst = instrument(inst_id)
        ld = lib_dir(inst)
        rows = []
        for p in select_presets(inst.presets(), category=category):
            if q and q.lower() not in p.name.lower():
                continue
            rec = is_recorded(ld, p)
            if recorded is not None and rec != recorded:
                continue
            wav = ld / "renders" / f"{slugify(p.id)}.wav"
            rows.append({"id": p.id, "name": p.name, "category": p.category, "recorded": rec, "audio": url(wav) if wav.exists() else None})
        return {"total": len(rows), "presets": rows[:limit]}

    @app.get("/api/devices")
    def devices():
        from ..instruments.hardware import query_devices

        return query_devices()

    # ---- ジョブ ----

    @app.get("/api/jobs/current")
    def current_job():
        return jobs.current.public() if jobs.current else None

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        return jobs.get(job_id).public()

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        jobs.get(job_id)._cancel.set()
        return {"ok": True}

    @app.post("/api/instruments/{inst_id}/test")
    def test_sound(inst_id: str, req: TestRequest):
        inst = instrument(inst_id)
        all_presets = inst.presets()
        if not all_presets:
            raise HTTPException(400, "音色一覧が空です")
        preset = next((p for p in all_presets if p.id == req.preset_id), all_presets[0])

        def work(job: Job):
            job.write(f"{preset.name} を鳴らして録音しています…")
            notes = [Note(60, 0.0, 0.8, 100), Note(60, 1.1, 2.3, 100), Note(64, 1.1, 2.3, 100), Note(67, 1.1, 2.3, 100)]
            try:
                y = inst.render(preset, notes, tail=1.0)
            finally:
                inst.close()
            path = out_root / "ui" / "test" / f"{datetime.now():%Y%m%d-%H%M%S}.wav"
            peak_db = float(20 * np.log10(np.max(np.abs(y)) + 1e-9)) if y.size else -120.0
            audio.save(path, y, inst.sample_rate)
            if peak_db < -50:
                verdict = "音が入っていません。接続・入力デバイス・MIDIチャンネルを確認してください。"
            elif peak_db < -24:
                verdict = "音が小さめです。本体のボリュームか入力レベルを上げてください。"
            elif peak_db > -0.5:
                verdict = "音が割れている可能性があります。本体のボリュームか入力レベルを下げてください。"
            else:
                verdict = "OK。正しい音色が鳴っているか聴いて確認してください。"
            return {"preset": preset.name, "audio": url(path), "peak_db": round(peak_db, 1), "verdict": verdict}

        return jobs.start("test", work).public()

    @app.post("/api/instruments/{inst_id}/build")
    def build(inst_id: str, req: BuildRequest):
        inst = instrument(inst_id)
        out = lib_dir(inst)
        targets = select_presets(inst.presets(), category=req.category, ids=req.ids)
        if not targets:
            raise HTTPException(400, "条件に合う音色がありません")

        def work(job: Job):
            counts = Counter()
            job.data = {"counts": {}, "recent": [], "current": None}

            def progress(i, n, preset, status):
                counts[status] += 1
                job.progress, job.total = i, n
                job.data["counts"] = dict(counts)
                if status != "skipped":
                    wav = out / "renders" / f"{slugify(preset.id)}.wav"
                    job.data["recent"] = ([{"name": preset.name, "category": preset.category, "status": status, "audio": url(wav) if wav.exists() else None}] + job.data["recent"])[:30]
                job.data["current"] = targets[i].name if i < job.total else None
                job.write(f"[{i}/{n}] {preset.name}（{ {'done': '録音', 'skipped': '録音済み', 'silent': '無音'}[status] }）")

            job.total = min(len(targets), req.limit) if req.limit else len(targets)
            job.data["current"] = targets[0].name
            try:
                build_library(inst, out, category=req.category, limit=req.limit, ids=req.ids, overwrite=req.overwrite, progress=progress)
            except ValueError:
                pass  # 1音色も録れなかった場合（index が空）
            return {"counts": dict(counts)}

        return jobs.start("build", work).public()

    @app.post("/api/match")
    async def match_song(
        instrument_id: str = Form(...),
        song: UploadFile = File(...),
        midi: UploadFile | None = File(None),
        separator: str = Form("demucs"),
        transcriber: str = Form("auto"),
        top: int = Form(5),
        rerank: int = Form(3),
        clip: float = Form(30.0),
    ):
        inst = instrument(instrument_id)
        ld = lib_dir(inst)
        if not (ld / "index.json").exists():
            raise HTTPException(400, "この楽器の音色ライブラリがまだありません。先に「録音」タブで音色を録音してください。")
        work_dir = out_root / "ui" / f"{datetime.now():%Y%m%d-%H%M%S}_{slugify(Path(song.filename or 'song').stem)}"
        work_dir.mkdir(parents=True, exist_ok=True)
        song_path = work_dir / f"input{Path(song.filename or '.wav').suffix or '.wav'}"
        song_path.write_bytes(await song.read())
        midi_path = None
        if midi is not None and midi.filename:
            midi_path = work_dir / "input.mid"
            midi_path.write_bytes(await midi.read())

        def work(job: Job):
            report = run(
                song_path, inst_dir / f"{instrument_id}.toml", work_dir,
                separator=separator, transcriber=transcriber, midi=midi_path,
                library_dir=ld, top=top, rerank=rerank, clip=clip or None, log=job.write,
            )
            report["target_audio"] = url(work_dir / "keys.wav")
            report["input_audio"] = url(song_path)
            report["midi"] = url(work_dir / "notes.mid")
            report["report_md"] = url(work_dir / "report.md")
            for c in report["candidates"]:
                c["audio"] = url(work_dir / c["audio"]) if c["audio"] else None
            return report

        return jobs.start("match", work).public()

    @app.get("/api/history")
    def history():
        """過去の照合結果（新しい順）。"""
        import json

        rows = []
        for d in sorted((out_root / "ui").glob("*/report.json"), reverse=True)[:30]:
            rep = json.loads(d.read_text(encoding="utf-8"))
            top1 = rep["candidates"][0]["name"] if rep["candidates"] else None
            rows.append({"name": d.parent.name, "instrument": rep["instrument"], "top": top1, "report_md": url(d.parent / "report.md")})
        return rows

    app.mount("/files/libraries", StaticFiles(directory=lib_root), name="libraries")
    app.mount("/files/out", StaticFiles(directory=out_root), name="out")
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


def _summary(inst_id: str, inst: Instrument, ld: Path) -> dict:
    presets = inst.presets()
    recorded = {p.id for p in presets if is_recorded(ld, p)}
    total, done = Counter(), Counter()
    for p in presets:
        total[p.category] += 1
        done[p.category] += p.id in recorded
    return {
        "id": inst_id,
        "name": inst.name,
        "type": type(inst).__name__.replace("Instrument", "").lower(),
        "total": len(presets),
        "recorded": len(recorded),
        "categories": [{"name": c, "total": total[c], "recorded": done[c]} for c in total],
        "sample_rate": inst.sample_rate,
        "file": f"instruments/{inst_id}.toml",
        "settings": _settings(inst),
    }


def _settings(inst: Instrument) -> dict:
    from ..instruments.hardware import HardwareInstrument

    if isinstance(inst, HardwareInstrument):
        return {
            "MIDI出力": inst.midi_port_name or "(未設定)",
            "MIDIチャンネル": inst.channel + 1,
            "録音デバイス": inst.input_device or "(システムの既定入力)",
            "入力チャンネル": ", ".join(map(str, inst.input_channels)),
            "サンプルレート": f"{inst.sample_rate} Hz",
        }
    return {"種類": "ソフトウェア（機器の接続は不要）", "サンプルレート": f"{inst.sample_rate} Hz"}


def serve(root: str | Path = ".", host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import uvicorn

    if open_browser:
        import webbrowser

        threading.Timer(1.2, lambda: webbrowser.open(f"http://{host}:{port}/")).start()
    print(f"synthmatch UI: http://{host}:{port}/  （終了は Ctrl+C）")
    uvicorn.run(create_app(root), host=host, port=port, log_level="warning")
