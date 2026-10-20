"""楽曲 → キーボード抽出 → 採譜 → 音色照合 → レポート、の一連の流れ。"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from . import audio
from .instruments import Instrument, load_instrument, slugify
from .library import Library
from .matcher import Candidate, match
from .notes import Note, clip_notes, read_midi, write_midi
from .report_html import render_html
from .separate import separate
from .transcribe import transcribe


def default_library_dir(inst: Instrument) -> Path:
    return Path("libraries") / slugify(inst.name)


def match_audio(
    keys_wav: Path,
    instrument_config: Path,
    out_dir: Path,
    notes: list[Note] | None,
    library_dir: Path | None = None,
    top: int = 5,
    rerank: int = 3,
    clip: float | None = 30.0,
    category: str | None = None,
    log=print,
) -> dict:
    inst = load_instrument(instrument_config)
    library = Library.load(library_dir or default_library_dir(inst))
    y, sr = audio.load(keys_wav, sr=inst.sample_rate)
    if clip:
        y = y[: int(clip * sr)]
        notes = clip_notes(notes, clip) if notes else notes
    scope = f"「{category}」の音色" if category else f"{len(library.entries)} 音色"
    log(f"[照合] {library.instrument} の {scope}から探します")
    info: dict = {}
    cands = match(y, sr, notes, library, inst, top=top, rerank=rerank, category=category, info=info, log=log)
    return write_report(out_dir, keys_wav, library, cands, inst.sample_rate, info.get("target_profile", {}), category)


def run(
    song: Path,
    instrument_config: Path,
    out_dir: Path,
    separator: str = "demucs",
    transcriber: str = "auto",
    midi: Path | None = None,
    **match_kw,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    log = match_kw.get("log", print)

    keys = out_dir / "keys.wav"
    log(f"[1/3] 分離 ({separator}) → {keys}")
    separate(song, keys, backend=separator)

    if midi:
        log(f"[2/3] MIDI を読み込み: {midi}")
        notes = read_midi(midi)
    else:
        log(f"[2/3] 採譜 ({transcriber})")
        notes = transcribe(keys, backend=transcriber, log=log)
    write_midi(notes, out_dir / "notes.mid")
    log(f"      {len(notes)} ノート → {out_dir / 'notes.mid'}")

    log("[3/3] 音色の照合")
    return match_audio(keys, instrument_config, out_dir, notes, **match_kw)


def write_report(
    out_dir: Path,
    keys_wav: Path,
    library: Library,
    cands: list[Candidate],
    sr: int,
    target_profile: dict | None = None,
    category: str | None = None,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    cand_dir = out_dir / "candidates"
    if cand_dir.exists():
        shutil.rmtree(cand_dir)
    cand_dir.mkdir()

    rows = []
    for c in cands:
        wav = cand_dir / f"{c.rank}_{slugify(c.name)}.wav"
        if c.audio is not None:
            audio.save(wav, c.audio, sr)
        else:
            i = next(i for i, e in enumerate(library.entries) if e["id"] == c.preset_id)
            src = library.render_path(i)
            if src.exists():
                shutil.copy(src, wav)
            else:
                wav = None
        rows.append(
            {
                "rank": c.rank,
                "id": c.preset_id,
                "name": c.name,
                "category": c.category,
                "score": round(c.score, 3),
                "stage": c.stage,
                "hints": c.hints,
                "profile": c.profile,
                "audio": str(wav.relative_to(out_dir)) if wav else None,
            }
        )
    report = {
        "target": str(keys_wav),
        "instrument": library.instrument,
        "category": category,
        "created": datetime.now().isoformat(timespec="seconds"),
        "target_profile": target_profile or {},
        "candidates": rows,
    }
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(_markdown(report), encoding="utf-8")
    target_rel = os.path.relpath(keys_wav, out_dir) if keys_wav.exists() else None
    (out_dir / "report.html").write_text(render_html(report, target_rel), encoding="utf-8")
    return report


def _markdown(report: dict) -> str:
    lines = [f"# 音色候補（{report['instrument']}）", "", f"目標: `{report['target']}`", ""]
    if report.get("category"):
        lines += [f"探した範囲: カテゴリ「{report['category']}」", ""]
    for r in report["candidates"]:
        lines.append(f"## {r['rank']}. {r['name']}  ")
        lines.append(f"カテゴリ: {r['category'] or '-'} / ID: `{r['id']}` / スコア: {r['score']}（{r['stage']}）  ")
        if r["audio"]:
            lines.append(f"試聴: `{r['audio']}`")
        lines.append("")
        lines += [f"- {h}" for h in r["hints"]] or ["- 大きな違いは見つかりませんでした"]
        lines.append("")
    lines.append("> スコアは小さいほど近い。rerank は目標と同じフレーズを実際に鳴らして比べた結果。")
    return "\n".join(lines) + "\n"
