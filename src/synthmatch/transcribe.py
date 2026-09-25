"""採譜：キーボードの音声からノート列（MIDI）を作る。

backend:
  basic-pitch  Spotify の basic-pitch（和音OK）。pip install -e ".[transcribe]"
  pyin         librosa の pyin（単音のみ。追加インストール不要）
  auto         basic-pitch が入っていればそれを、なければ pyin を使う

バンドスコアなどから作った MIDI があるなら、採譜せずに --midi で渡す方が確実。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

from .notes import Note


def _basic_pitch(path: Path) -> list[Note]:
    from basic_pitch.inference import predict

    _, midi, _ = predict(str(path))
    notes = [Note(n.pitch, float(n.start), float(n.end), n.velocity) for inst in midi.instruments for n in inst.notes]
    return sorted(notes, key=lambda n: (n.start, n.pitch))


def _pyin(path: Path, min_dur: float = 0.08) -> list[Note]:
    import librosa

    y, sr = librosa.load(str(path), sr=22050, mono=True)
    hop = 256
    f0, voiced, _ = librosa.pyin(y, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"), sr=sr, hop_length=hop)
    midi = np.where(voiced, np.round(librosa.hz_to_midi(np.nan_to_num(f0, nan=1.0))), -1).astype(int)
    notes, start, cur = [], 0, -1
    for i, m in enumerate(list(midi) + [-1]):
        if m != cur:
            if cur >= 0 and (i - start) * hop / sr >= min_dur:
                notes.append(Note(int(cur), start * hop / sr, i * hop / sr, 100))
            start, cur = i, m
    return notes


BACKENDS = {"basic-pitch": _basic_pitch, "pyin": _pyin}


def transcribe(path: str | Path, backend: str = "auto", log=print) -> list[Note]:
    if backend == "auto":
        backend = "basic-pitch" if importlib.util.find_spec("basic_pitch") else "pyin"
        if backend == "pyin":
            log("  basic-pitch が入っていないので pyin（単音のみ）で採譜します")
    if backend not in BACKENDS:
        raise ValueError(f"採譜方法 '{backend}' は未対応です（{', '.join(BACKENDS)}, auto）")
    return BACKENDS[backend](Path(path))
