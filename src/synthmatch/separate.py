"""音源分離：楽曲からキーボードパートを取り出す。

backend:
  demucs  htdemucs_6s で6パートに分け、piano と other を足したものをキーボードとする
          （シンセ専用のモデルはまだ少ないため。ギターやボーカルは除かれる）
  none    入力をそのまま使う（すでにキーボードだけの音源がある場合・テスト用）

新しい分離方法を足すときは BACKENDS に関数を追加する。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from . import audio


def _none(src: Path, dst: Path, **_) -> None:
    y, sr = audio.load(src, sr=None)
    audio.save(dst, y, sr)


def _demucs(src: Path, dst: Path, model: str = "htdemucs_6s", stems: tuple[str, ...] = ("piano", "other"), **_) -> None:
    if importlib.util.find_spec("demucs") is None:
        raise RuntimeError("demucs が入っていません。pip install -e '.[separate]' を実行してください。")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, "-m", "demucs", "-n", model, "-o", tmp, str(src)], check=True)
        stem_dir = Path(tmp) / model / src.stem
        mix, sr = None, None
        for s in stems:
            y, sr = audio.load(stem_dir / f"{s}.wav", sr=None)
            mix = y if mix is None else mix[: len(y)] + y[: len(mix)]
        if mix is None:
            raise RuntimeError("分離結果がありません")
        audio.save(dst, np.asarray(mix), sr)


BACKENDS = {"demucs": _demucs, "none": _none}


def separate(src: str | Path, dst: str | Path, backend: str = "demucs", **kw) -> Path:
    if backend not in BACKENDS:
        raise ValueError(f"分離方法 '{backend}' は未対応です（{', '.join(BACKENDS)}）")
    src, dst = Path(src), Path(dst)
    BACKENDS[backend](src, dst, **kw)
    return dst
