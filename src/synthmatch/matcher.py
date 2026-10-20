"""目標の音に近い音色を探す。

1段目: 共通フレーズで作ったライブラリと特徴量で比べる（速い・楽器を使わない）
2段目 (rerank): 上位の音色で「目標と同じMIDI」を実際に鳴らし、時間をそろえて比べ直す
          音の高さや弾き方の違いがなくなるので精度が上がる。ハードの場合は実機で録音する。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import features
from .hints import make_hints
from .instruments import Instrument, Preset
from .library import Library
from .notes import Note


@dataclass
class Candidate:
    rank: int
    preset_id: str
    name: str
    category: str
    score: float  # 小さいほど近い
    stage: str  # "library" または "rerank"
    hints: list[str] = field(default_factory=list)
    profile: dict = field(default_factory=dict)  # features.describe() の値
    audio: np.ndarray | None = None  # rerank 時に鳴らした音


def match(
    y: np.ndarray,
    sr: int,
    notes: list[Note] | None,
    library: Library,
    instrument: Instrument | None = None,
    top: int = 5,
    rerank: int = 0,
    category: str | None = None,
    info: dict | None = None,
    log=print,
) -> list[Candidate]:
    """近い順の候補を返す。category を渡すと、そのカテゴリ名を含む音色だけから探す。
    info に dict を渡すと、目標の音の特徴（target_profile）を書き込む。"""
    target = features.extract(y, sr, notes)
    tvec = features.to_vector(target)
    ranked = library.rank(tvec)
    if category:
        ranked = [(i, d) for i, d in ranked if category.lower() in library.entries[i].get("category", "").lower()]
        if not ranked:
            raise ValueError(f"カテゴリ「{category}」の音色がライブラリにありません（先に録音してください）")
    if info is not None:
        info["target_profile"] = features.describe(target)

    pool = ranked[: max(top, rerank)]
    results: list[Candidate] = []
    for i, dist in pool:
        e = library.entries[i]
        results.append(Candidate(0, e["id"], e["name"], e.get("category", ""), dist, "library"))
    cand_feats = {c.preset_id: library.features_of(i) for c, (i, _) in zip(results, pool)}

    if rerank and instrument is not None and notes:
        presets = {p.id: p for p in instrument.presets()}
        try:
            for c in results[:rerank]:
                preset: Preset = presets[c.preset_id]
                log(f"  鳴らして比較: {c.name}")
                ry = instrument.render(preset, notes)
                rf = features.extract(ry, instrument.sample_rate, notes)
                ty = y if sr == instrument.sample_rate else _resample(y, sr, instrument.sample_rate)
                c.score = library.distance(tvec, features.to_vector(rf)) + features.aligned_mel_distance(ty, ry, instrument.sample_rate) / 10
                c.stage = "rerank"
                c.audio = ry
                cand_feats[c.preset_id] = rf
        finally:
            instrument.close()
        reranked = sorted(results[:rerank], key=lambda c: c.score)
        results = reranked + results[rerank:]

    results = results[:top]
    controls = getattr(instrument, "controls", None)
    for n, c in enumerate(results, 1):
        c.rank = n
        c.hints = make_hints(target, cand_feats[c.preset_id], controls)
        c.profile = features.describe(cand_feats[c.preset_id])
    return results


def _resample(y: np.ndarray, sr: int, target: int) -> np.ndarray:
    import librosa

    return librosa.resample(y, orig_sr=sr, target_sr=target)
