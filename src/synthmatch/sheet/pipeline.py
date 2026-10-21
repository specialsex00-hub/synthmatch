"""ピアノの音声ファイル → 楽譜（PDF / MusicXML / MIDI / SVG）。

出力フォルダ:
  audio.wav          読み込んだ音声（モノラル）
  transcription.mid  採譜そのままの MIDI（演奏の揺れを含む）
  preview.wav        採譜結果（演奏そのまま・ペダルつき）をピアノの音で鳴らしたもの
  score.wav          楽譜どおりにピアノの音で鳴らしたもの（先頭を原曲にそろえてある）
  score.musicxml     楽譜データ（MuseScore などで開いて直せる）
  score.mid          楽譜どおりの MIDI
  score.pdf          印刷用
  pages/page-N.svg   画面表示用
  sheet.json         調・拍子・テンポなどの情報
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np

from .. import audio
from ..notes import Note, read_pedals, write_midi
from .cleanup import SENSITIVITY, clean
from .playback import render_midi
from .quantize import beats_to_seconds, estimate_beats, extend_by_pedal, origin_beat, quantize, split_hands
from .render import render
from .score import build_score
from .transcribe import Transcription, decode_audio, transcribe_piano

TIME_SIGNATURES = ("4/4", "3/4", "2/4", "6/8")


def make_sheet(
    src: str | Path,
    out_dir: str | Path,
    title: str | None = None,
    backend: str = "piano",
    bpm: float | None = None,
    time_signature: str = "4/4",
    grid: int = 4,
    split: int = 60,
    key_sharps: int | None = None,
    sensitivity: str = "normal",
    log=print,
) -> dict:
    src, out = Path(src), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    log("[1/4] 音声を読み込んでいます")
    wav = decode_audio(src, out / "audio.wav", sr=44100)
    wav16 = decode_audio(src, out / "audio16k.wav", sr=16000) if backend == "piano" else wav

    log("[2/4] ピアノの音を拾っています")
    tr = transcribe_piano(wav, wav16, backend=backend, log=log)
    if wav16 != wav:
        wav16.unlink(missing_ok=True)
    if not tr.notes:
        raise RuntimeError("音を拾えませんでした。ピアノの音が入っているか確認してください。")
    log(f"  {len(tr.notes)} 個の音が見つかりました")

    y, sr = audio.load(wav, sr=22050)
    _clip_to(tr, len(y) / sr)
    write_midi(tr.notes, out / "transcription.mid", tr.pedals)
    log("  採譜した音をピアノの音で鳴らしています…")
    method = render_midi(out / "transcription.mid", out / "preview.wav", log=log)
    return sheet_from_transcription(
        tr, y, sr, out, title=title or src.stem, source=src.name,
        bpm=bpm, time_signature=time_signature, grid=grid, split=split, key_sharps=key_sharps,
        sensitivity=sensitivity, playback=method, log=log,
    )


def _clip_to(tr: Transcription, dur: float) -> None:
    """録音の終わりで鳴り続けている音は、採譜モデルが録音より後ろの時刻を付けるので録音の長さで切る。"""
    tr.notes = [Note(n.pitch, n.start, min(n.end, dur), n.velocity) for n in tr.notes if n.start < dur]
    tr.pedals = [(a, min(b, dur)) for a, b in tr.pedals if a < dur]


def sheet_from_transcription(
    tr: Transcription,
    y: np.ndarray,
    sr: int,
    out: Path,
    title: str,
    source: str = "",
    bpm: float | None = None,
    time_signature: str = "4/4",
    grid: int = 4,
    split: int = 60,
    key_sharps: int | None = None,
    key_plan: list[tuple[float, int]] | None = None,
    sensitivity: str = "normal",
    playback: str | None = None,
    log=print,
) -> dict:
    """採譜済みのノートから楽譜を作る（採譜をやり直さずに設定だけ変えて作り直すときにも使う）。

    transcription.mid と preview.wav（演奏そのままの音）は呼び出し側で用意しておく。
    """
    if time_signature not in TIME_SIGNATURES:
        raise ValueError(f"拍子は {', '.join(TIME_SIGNATURES)} から選んでください")
    if sensitivity not in SENSITIVITY:
        raise ValueError(f"音を拾う量は {', '.join(SENSITIVITY)} から選んでください")

    log("[3/4] 拍とテンポを推定しています")
    beats, tempo = estimate_beats(y, sr, tr.notes, bpm=bpm)
    log(f"  テンポ 約{tempo:.0f} BPM")
    notes, stats = clean(tr.notes, tempo, sensitivity)
    if sensitivity != "off":
        log(f"  弾いていないと思われる音を {len(stats.removed)} 個除き、{stats.merged} 個の音を和音にそろえました")
    # 楽譜には「聞こえている長さ」で書く：ペダルで響いている音は伸ばし、録音の最後まで鳴っていた音には印を付ける
    qnotes = quantize(extend_by_pedal(notes, tr.pedals), beats, grid=grid, held_until=len(y) / sr)
    right, left = split_hands(qnotes, split=split)

    log("[4/4] 楽譜にしています")
    score, info = build_score(
        right, left, bpm=tempo, time_signature=time_signature, title=title, key_sharps=key_sharps, key_plan=key_plan
    )
    xml = out / "score.musicxml"
    score.write("musicxml", fp=str(xml))
    score.write("midi", fp=str(out / "score.mid"))
    pages, pdf = render(xml, out)
    log(f"  {info.key}・{info.time_signature}・{info.measures}小節・{len(pages)}ページ")
    for mod in info.modulations:
        log(f"  小節{mod['measure']}から転調: {mod['key']}（調号 {mod['sharps']:+d}）")
    log("  楽譜どおりの音を作っています…")
    offset = max(beats_to_seconds(origin_beat(notes, beats), beats), 0.0)
    method = render_midi(out / "score.mid", out / "score.wav", offset=offset, log=log)

    removed = set(stats.removed)
    meta = {
        "title": title,
        "source": source,
        "created": datetime.now().isoformat(timespec="seconds"),
        "key": info.key,
        "key_sharps": info.key_sharps,
        "key_fixed": key_sharps is not None,  # 曲全体を1つの調号に指定
        "key_plan": info.key_plan,
        "key_plan_fixed": bool(key_plan),  # 区間ごとの調号を手で直した
        "key_candidates": info.key_candidates,
        "modulations": info.modulations,
        "playback": playback or method,
        "time_signature": info.time_signature,
        "bpm": info.bpm,
        "bpm_fixed": bpm is not None,
        "grid": grid,
        "split": split,
        "measures": info.measures,
        "notes": info.notes,
        "pedals": len(tr.pedals),
        "duration": round(len(y) / sr, 2),
        "pages": [p.relative_to(out).as_posix() for p in pages],
        "files": {
            "pdf": pdf.name,
            "musicxml": xml.name,
            "score_midi": "score.mid",
            "transcription_midi": "transcription.mid",
            "audio": "audio.wav",
            "preview": "preview.wav",
            "score_audio": "score.wav",
        },
        "sensitivity": sensitivity,
        "cleanup": {"removed": len(stats.removed), "merged": stats.merged},
        # 画面のピアノロール用（高さ, 開始秒, 終了秒, 強さ, 楽譜に使ったか）
        "roll": [
            [n.pitch, round(n.start, 3), round(n.end, 3), n.velocity, i not in removed]
            for i, n in enumerate(tr.notes)
        ],
    }
    (out / "sheet.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


KEEP = "keep"


def rebuild(out_dir: str | Path, key: object = KEEP, **kw) -> dict:
    """前回の採譜結果（transcription.mid）から、拍子やテンポなどの設定だけ変えて楽譜を作り直す。

    key（調号の決め方）:
      "keep"   前回の指定をそのまま使う（手で直した区間ごとの調号・曲全体の調号も引き継ぐ）
      "auto"   自動で推定し直す（転調も検出）
      int      曲全体をその調号で書く
      list     区間ごとの調号 [(何拍目から, 調号), ...]
    互換のため key_sharps=... でも曲全体の調号を指定できる。
    """
    from ..notes import read_midi

    out = Path(out_dir)
    old = json.loads((out / "sheet.json").read_text(encoding="utf-8"))
    mid = out / "transcription.mid"
    tr = Transcription(read_midi(mid), read_pedals(mid))
    y, sr = audio.load(out / "audio.wav", sr=22050)
    if max((n.end for n in tr.notes), default=0) > len(y) / sr:  # 古いバージョンで作った結果
        _clip_to(tr, len(y) / sr)
        write_midi(tr.notes, mid, tr.pedals)
        old["playback"] = None
    opts = {k: old[k] for k in ("time_signature", "grid", "split")}
    opts["bpm"] = old["bpm"] if old.get("bpm_fixed") else None
    opts["sensitivity"] = old.get("sensitivity", "normal")
    opts.update({k: v for k, v in kw.items() if k in ("bpm", "time_signature", "grid", "split", "sensitivity", "log")})
    if "key_sharps" in kw:
        key = "auto" if kw["key_sharps"] is None else int(kw["key_sharps"])
    if key == KEEP:
        opts["key_sharps"] = old.get("key_sharps") if old.get("key_fixed") else None
        opts["key_plan"] = [(p["beat"], p["sharps"]) for p in old.get("key_plan", [])] if old.get("key_plan_fixed") else None
    elif key == "auto":
        opts["key_sharps"], opts["key_plan"] = None, None
    elif isinstance(key, int):
        opts["key_sharps"], opts["key_plan"] = key, None
    else:
        opts["key_sharps"], opts["key_plan"] = None, [(float(b), int(sig)) for b, sig in key]
    log = opts.get("log", print)
    if not (out / "preview.wav").exists() or old.get("playback") != "fluidsynth":
        old["playback"] = render_midi(mid, out / "preview.wav", log=log)
    return sheet_from_transcription(
        tr, y, sr, out, title=old["title"], source=old.get("source", ""), playback=old.get("playback"), **opts
    )
