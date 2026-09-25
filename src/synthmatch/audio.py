"""音声ファイルの読み書き。内部ではモノラル float32 で扱う。"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def load(path: str | Path, sr: int | None = 44100) -> tuple[np.ndarray, int]:
    import librosa

    y, sr = librosa.load(str(path), sr=sr, mono=True)
    return y.astype(np.float32), int(sr)


def save(path: str | Path, y: np.ndarray, sr: int) -> None:
    import soundfile as sf

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak > 0.99:
        y = y * (0.99 / peak)
    sf.write(str(path), y, sr)


def to_mono(y: np.ndarray) -> np.ndarray:
    y = np.asarray(y, dtype=np.float32)
    if y.ndim == 2:
        # (samples, channels) と (channels, samples) の両方に対応
        axis = 1 if y.shape[0] > y.shape[1] else 0
        y = y.mean(axis=axis)
    return y
