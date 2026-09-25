"""音色ライブラリ：楽器の全音色で共通フレーズを鳴らし、特徴量を保存したもの。

libraries/<楽器名>/
  index.json        楽器名・音色一覧
  features/<id>.npy 音色ごとの特徴量（途中から再開できるよう1つずつ保存）
  renders/<id>.wav  録音した音（聴き比べ用）
  probe.mid         使ったフレーズ
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Callable

import numpy as np

from . import audio, features
from .instruments import Instrument, Preset, slugify
from .notes import probe_notes, write_midi

GROUP_WEIGHTS = {
    "mel_shape": 1.0,
    "mfcc_mean": 1.0,
    "mfcc_std": 0.5,
    "brightness": 1.0,
    "flatness": 0.5,
    "contrast": 0.5,
    "envelope": 1.0,
}


def _file_id(preset: Preset) -> str:
    return slugify(preset.id)


def build_library(
    inst: Instrument,
    out_dir: str | Path,
    category: str | None = None,
    limit: int | None = None,
    ids: list[str] | None = None,
    overwrite: bool = False,
    save_audio: bool = True,
    progress: Callable[[int, int, Preset, str], None] | None = None,
) -> "Library":
    """音色を順に鳴らして特徴量を保存する。

    progress(i, n, preset, status) の status は "done" / "skipped"（録音済み）/ "silent"（音が入らなかった）。
    progress の中で例外を投げると中断できる。その場合も、そこまでの結果は index に反映される。
    """
    out = Path(out_dir)
    (out / "features").mkdir(parents=True, exist_ok=True)
    notes = probe_notes()
    write_midi(notes, out / "probe.mid")

    presets = select_presets(inst.presets(), category=category, ids=ids)
    if limit:
        presets = presets[:limit]
    try:
        for i, preset in enumerate(presets):
            fpath = out / "features" / f"{_file_id(preset)}.npy"
            status = "skipped" if fpath.exists() and not overwrite else "done"
            if status == "done":
                y = inst.render(preset, notes)
                try:
                    feats = features.extract(y, inst.sample_rate, notes)
                except ValueError:
                    status = "silent"
                else:
                    np.save(fpath, features.to_vector(feats))
                    if save_audio:
                        audio.save(out / "renders" / f"{_file_id(preset)}.wav", y, inst.sample_rate)
            if progress:
                progress(i + 1, len(presets), preset, status)
    finally:
        inst.close()
        write_index(inst, out)
    return Library.load(out)


def select_presets(presets: list[Preset], category: str | None = None, ids: list[str] | None = None) -> list[Preset]:
    # カテゴリは部分一致（例: "Synth Lead" で "SN-S:Synth Lead" と "PCM:Synth Lead" の両方）
    if category:
        presets = [p for p in presets if category.lower() in p.category.lower()]
    if ids is not None:
        wanted = set(ids)
        presets = [p for p in presets if p.id in wanted]
    return presets


def is_recorded(out_dir: str | Path, preset: Preset) -> bool:
    return (Path(out_dir) / "features" / f"{_file_id(preset)}.npy").exists()


def write_index(inst: Instrument, out_dir: str | Path) -> None:
    """以前の実行分も含め、特徴量がそろっている音色を index に書く。"""
    out = Path(out_dir)
    entries = [{k: v for k, v in asdict(p).items() if k != "data"} for p in inst.presets() if is_recorded(out, p)]
    index = {"instrument": inst.name, "sample_rate": inst.sample_rate, "presets": entries}
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


class Library:
    def __init__(self, path: Path, index: dict, matrix: np.ndarray):
        self.path = path
        self.instrument = index["instrument"]
        self.entries: list[dict] = index["presets"]
        self.matrix = matrix  # (音色数, 次元)
        self.mean = np.nanmean(matrix, axis=0)
        std = np.nanstd(matrix, axis=0)
        self.std = np.where(std > 1e-6, std, 1.0)
        w = np.zeros(matrix.shape[1])
        for g, sl in features.group_slices().items():
            w[sl] = GROUP_WEIGHTS[g] / np.sqrt(sl.stop - sl.start)
        self.weights = w
        # 測れなかった値（NaN）は平均で埋める
        self._z = np.nan_to_num(self._zscore(matrix), nan=0.0)

    @classmethod
    def load(cls, path: str | Path) -> "Library":
        path = Path(path)
        idx_file = path / "index.json"
        if not idx_file.exists():
            raise FileNotFoundError(f"{path} に音色ライブラリがありません。先に `synthmatch build-library` を実行してください。")
        index = json.loads(idx_file.read_text(encoding="utf-8"))
        if not index["presets"]:
            raise ValueError(f"{path} の音色ライブラリが空です")
        rows = [np.load(path / "features" / f"{slugify(e['id'])}.npy") for e in index["presets"]]
        return cls(path, index, np.vstack(rows))

    def _zscore(self, x: np.ndarray) -> np.ndarray:
        return (x - self.mean) / self.std

    def distance(self, a: np.ndarray, b: np.ndarray) -> float:
        """特徴ベクトル同士の重み付き距離（NaN の次元は無視）。"""
        d = (self._zscore(a) - self._zscore(b)) * self.weights
        return float(np.sqrt(np.nansum(d**2)))

    def rank(self, target: np.ndarray) -> list[tuple[int, float]]:
        zt = self._zscore(target)
        d = (self._z - zt) * self.weights
        dist = np.sqrt(np.nansum(d**2, axis=1))
        order = np.argsort(dist)
        return [(int(i), float(dist[i])) for i in order]

    def features_of(self, i: int) -> dict[str, np.ndarray]:
        return features.from_vector(self.matrix[i])

    def render_path(self, i: int) -> Path:
        return self.path / "renders" / f"{slugify(self.entries[i]['id'])}.wav"
