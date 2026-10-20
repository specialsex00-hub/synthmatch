"""拍の推定と、音符の時刻を拍の格子にそろえる処理。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from ..notes import Note


@dataclass
class QNote:
    """拍単位にそろえた音符。start / length は四分音符 = 1.0。"""

    pitch: int
    start: float
    length: float
    velocity: int = 80
    to_end: bool = False  # 録音の最後まで鳴っていた音（楽譜では小節の終わりまで伸ばす）


def estimate_beats(y: np.ndarray, sr: int, notes: list[Note], bpm: float | None = None) -> tuple[np.ndarray, float]:
    """拍の時刻（秒）とテンポ（BPM）を返す。

    bpm を指定したときは、最初の音から一定テンポの格子を作る。
    指定しないときは音声から拍を検出する（テンポの揺れにも追従する）。
    """
    import librosa

    first = min((n.start for n in notes), default=0.0)
    last = max((n.end for n in notes), default=len(y) / sr)
    if bpm:
        period = 60.0 / bpm
        return first + np.arange(0, (last - first) / period + 2) * period, float(bpm)

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo, frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr, units="frames", start_bpm=100)
    beats = librosa.frames_to_time(frames, sr=sr)
    tempo = float(np.atleast_1d(tempo)[0])
    if len(beats) < 4 or tempo <= 0:
        return estimate_beats(y, sr, notes, bpm=tempo if tempo > 0 else 100.0)
    # 最初の拍を最初の音に合わせる（拍検出は曲の頭の拍を取りこぼしやすい）
    period = float(np.median(np.diff(beats)))
    lead = int(np.floor((beats[0] - first) / period + 0.5))
    if lead > 0:
        beats = np.concatenate([beats[0] - period * np.arange(lead, 0, -1), beats])
    return beats, 60.0 / period


def seconds_to_beats(t: np.ndarray, beats: np.ndarray) -> np.ndarray:
    """秒 → 拍（拍と拍の間は直線で補間し、両端の外側は端のテンポで延長する）。"""
    idx = np.arange(len(beats), dtype=float)
    t = np.asarray(t, dtype=float)
    out = np.interp(t, beats, idx)
    p0 = beats[1] - beats[0]
    p1 = beats[-1] - beats[-2]
    out = np.where(t < beats[0], (t - beats[0]) / p0, out)
    out = np.where(t > beats[-1], len(beats) - 1 + (t - beats[-1]) / p1, out)
    return out


def origin_beat(notes: list[Note], beats: np.ndarray) -> float:
    """楽譜の先頭（0拍目）にする拍の番号。最初の音のいちばん近くの拍の頭。"""
    return float(np.floor(seconds_to_beats(np.array([min(n.start for n in notes)]), beats)[0] + 0.25))


def beats_to_seconds(b: float, beats: np.ndarray) -> float:
    if b <= 0:
        return float(beats[0] + b * (beats[1] - beats[0]))
    if b >= len(beats) - 1:
        return float(beats[-1] + (b - len(beats) + 1) * (beats[-1] - beats[-2]))
    return float(np.interp(b, np.arange(len(beats)), beats))


TRIPLET = (Fraction(0), Fraction(1, 3), Fraction(2, 3), Fraction(1))


def _duple(grid: int) -> tuple[Fraction, ...]:
    return tuple(Fraction(i, grid) for i in range(grid + 1))


def _fit_error(rel: list[float], points: tuple[Fraction, ...]) -> float:
    """拍の中の位置 rel を格子 points に当てはめたときの誤差（二乗平均）。

    テンポの揺れを許すため、拍の長さを 0.85〜1.2 倍に伸び縮みさせた中でいちばん合うものを使う。
    """
    best = np.inf
    for scale in np.linspace(0.85, 1.2, 15):
        err = np.mean([min((r - float(p) * scale) ** 2 for p in points) for r in rel])
        best = min(best, err)
    return float(best)


def detect_triplets(on_beats: np.ndarray, grid: int = 4) -> set[int]:
    """3連符で弾いていると思われる拍の番号を返す。

    1拍の中に（拍の頭以外で）2つ以上の音があり、3連符の格子の方が普通の格子よりはっきり合う拍を選ぶ。
    """
    by_beat: dict[int, list[float]] = {}
    for x in on_beats:
        k = int(np.floor(x + 0.1))  # 拍の少し手前で弾いた音は次の拍の頭とみなす
        by_beat.setdefault(k, []).append(float(x - k))
    out = set()
    for k, rel in by_beat.items():
        rel = sorted(set(round(r, 3) for r in rel))
        if sum(0.15 < r < 0.9 for r in rel) < 2:
            continue
        e_trip = _fit_error(rel, TRIPLET)
        e_duple = _fit_error(rel, _duple(grid))
        if e_trip < 0.004 and e_trip < 0.5 * e_duple:
            out.add(k)
    return out


def _snap(x: float, triplet_beats: set[int], grid: int) -> Fraction:
    k = int(np.floor(x + 1e-6))
    points = TRIPLET if k in triplet_beats else _duple(grid)
    return k + min(points, key=lambda p: abs(x - k - float(p)))


def quantize(
    notes: list[Note],
    beats: np.ndarray,
    grid: int = 4,
    triplets: bool = True,
    held_until: float | None = None,
) -> list[QNote]:
    """音符を拍の格子にそろえる（grid=4 なら16分音符、2 なら8分音符）。

    triplets=True なら、3連符で弾いている拍は 1/3 拍の格子にそろえる。
    held_until（秒）を渡すと、その時刻まで鳴っていた音（録音の終わりで切れた音）に印を付ける。
    楽譜の先頭（0拍目）は、最初の音のいちばん近くの拍の頭にする（少し早く弾き始めても1拍ずれないように）。
    """
    if not notes:
        return []
    origin = origin_beat(notes, beats)
    on = seconds_to_beats(np.array([n.start for n in notes]), beats) - origin
    off = seconds_to_beats(np.array([n.end for n in notes]), beats) - origin
    trip = detect_triplets(on, grid) if triplets else set()
    out: dict[tuple[int, Fraction], QNote] = {}
    for n, a, b in zip(notes, on, off):
        qa, qb = _snap(a, trip, grid), _snap(b, trip, grid)
        unit = Fraction(1, 3) if int(np.floor(float(qa) + 1e-6)) in trip else Fraction(1, grid)
        length = max(qb - qa, unit)
        to_end = held_until is not None and n.end >= held_until - 0.05
        key = (n.pitch, qa)
        # 同じ高さ・同じ位置の音が重なったら長い方を残す
        if key not in out or out[key].length < length:
            out[key] = QNote(n.pitch, qa, length, n.velocity, to_end)
    return sorted(out.values(), key=lambda q: (q.start, q.pitch))


def extend_by_pedal(notes: list[Note], pedals: list[tuple[float, float]]) -> list[Note]:
    """ペダルを踏んだまま指を離した音は、ペダルを離すまで響くので、その長さにする（楽譜用）。"""
    out = []
    for n in notes:
        end = n.end
        for on, off in pedals:
            if on <= n.end < off:
                end = max(end, off)
        out.append(Note(n.pitch, n.start, end, n.velocity))
    return out


def split_hands(qnotes: list[QNote], split: int = 60) -> tuple[list[QNote], list[QNote]]:
    """右手（ト音記号）と左手（ヘ音記号）に分ける。

    基本は split（既定は真ん中のド C4=60）より上を右手にする。
    ただし同じ瞬間に鳴る和音は、いちばん広い隙間で上下に切って、片手が12度を超えて広がらないようにする。
    """
    right, left = [], []
    by_start: dict[float, list[QNote]] = {}
    for q in qnotes:
        by_start.setdefault(q.start, []).append(q)
    for _, group in sorted(by_start.items()):
        group.sort(key=lambda q: q.pitch)
        cut = sum(1 for q in group if q.pitch < split)
        if 0 < cut < len(group) or len(group) == 1:
            pass
        elif group[-1].pitch - group[0].pitch > 19:
            gaps = [group[i + 1].pitch - group[i].pitch for i in range(len(group) - 1)]
            cut = int(np.argmax(gaps)) + 1
        left.extend(group[:cut])
        right.extend(group[cut:])
    return right, left
