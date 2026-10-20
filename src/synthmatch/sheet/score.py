"""拍にそろえた音符から、ピアノの大譜表（右手・左手）を music21 で組み立てる。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from .quantize import QNote


@dataclass
class ScoreInfo:
    key: str  # 例: "C major", "A minor"
    key_sharps: int
    key_candidates: list[dict]  # 推定の候補（上位から。key / sharps / confidence）
    time_signature: str
    bpm: float
    measures: int
    notes: int


def _events(qnotes: list[QNote], total: float | None = None) -> list[tuple[float, list[int], float]]:
    """同じ瞬間に始まる音を和音にまとめ、次の和音とは重ならないように長さを切る。

    楽譜を読みやすくするため、片手の中は「一度に1つの和音」にする（伸ばしたまま別の音を弾く書き方はしない）。
    total（曲の終わり）を渡すと、録音の最後まで鳴っていた最後の和音を曲の終わりまで伸ばす。
    """
    groups: dict[float, list[QNote]] = {}
    for q in qnotes:
        groups.setdefault(q.start, []).append(q)
    starts = sorted(groups)
    out = []
    for i, s in enumerate(starts):
        g = groups[s]
        length = max(q.length for q in g)
        if i + 1 < len(starts):
            nxt = starts[i + 1] - s
            # 次の音の直前で離している（半拍未満の隙間）なら、次の音までつなげて書く。細かい休符を減らすため
            length = nxt if nxt - length < 0.5 else min(length, nxt)
        elif total is not None and any(q.to_end for q in g):
            length = total - s
        out.append((s, sorted({q.pitch for q in g}), length))
    return out


def _rest_pieces(t0: float, t1: float, beat: float, sub: float, bar: float, half_bar_rests: bool) -> list[tuple[float, float]]:
    """t0〜t1 の休符を、拍の区切りで分けた（開始, 長さ）の一覧にする。

    手書きの楽譜と同じく、拍をまたぐ休符や複付点の休符は作らない。
      - 拍の途中から始まる休符は、まず半拍（sub）の区切り、次に拍の区切りまで
      - 拍の頭からの休符は1拍ずつ。4/4 では小節の前半・後半にぴったり収まる2拍は二分休符にする
    """
    eps = 1e-6
    out = []
    t = t0
    while t < t1 - eps:
        pos = t % bar
        on_beat = abs(pos / beat - round(pos / beat)) < eps
        if on_beat and t1 - t >= beat - eps:
            if half_bar_rests and abs(pos % (bar / 2)) < eps and t1 - t >= bar / 2 - eps:
                length = bar if abs(pos) < eps and t1 - t >= bar - eps else bar / 2
            else:
                length = beat
            out.append((t, length))
            t += length
            continue
        next_beat = t - pos + (np.floor(pos / beat + eps) + 1) * beat
        end = min(next_beat, t1)
        # 16分音符の位置から始まる休符は、まず次の8分音符の区切りまで（3連符の位置は分けない）
        next_sub = t - pos + (np.floor(pos / sub + eps) + 1) * sub
        if abs(t * 4 - round(t * 4)) < eps and next_sub < end - eps:
            end = next_sub
        out.append((t, end - t))
        t = end
    return out


def _to_fraction(x) -> Fraction:
    return x if isinstance(x, Fraction) else Fraction(x).limit_denominator(48)


def _pitch(midi: int, use_flats: bool):
    from music21 import pitch

    p = pitch.Pitch(midi=midi)
    if use_flats and p.accidental is not None and p.accidental.name == "sharp":
        p = p.getEnharmonic()
    return p


def _simplest(k):
    """同じ音で書き方が2通りある調（嬰ハ長調＝変ニ長調など）は、♯・♭の少ない方にする。"""
    from music21 import key

    if abs(k.sharps) > 6:
        return key.Key(k.tonic.getEnharmonic().name, k.mode)
    return k


def _key_name(k) -> str:
    return f"{k.tonic.name.replace('-', 'b')} {'major' if k.mode == 'major' else 'minor'}"


def estimate_key(qnotes: list[QNote]):
    """調を推定する（Krumhansl-Schmuckler 法。音の長さで重み付け）。候補を確からしい順に返す。"""
    from music21 import key, note, stream

    if not qnotes:
        return [key.Key("C")]
    probe = stream.Stream()
    for q in qnotes:
        n = note.Note(midi=q.pitch)
        n.quarterLength = max(q.length, 0.25)
        probe.append(n)
    best = probe.analyze("key")
    seen, out = set(), []
    for k in [best, *best.alternateInterpretations]:
        k2 = _simplest(k)
        name = _key_name(k2)
        if name not in seen:
            seen.add(name)
            k2.correlationCoefficient = k.correlationCoefficient
            out.append(k2)
    return out


def build_score(
    right: list[QNote],
    left: list[QNote],
    bpm: float,
    time_signature: str = "4/4",
    title: str = "",
    key_sharps: int | None = None,
):
    """key_sharps で調号（♯なら正、♭なら負）を指定できる。省略すると自動で推定する。"""
    """music21 の Score と ScoreInfo を返す。"""
    from music21 import chord, clef, instrument, key, layout, metadata, meter, note, stream, tempo

    allq = right + left
    candidates = estimate_key(allq)
    k = candidates[0]
    if key_sharps is not None:
        # 指定された調号の中で、いちばん確からしい長調・短調を選ぶ
        k = next((c for c in candidates if c.sharps == key_sharps), None) or key.KeySignature(key_sharps).asKey("major")
    use_flats = k.sharps < 0

    ts = meter.TimeSignature(time_signature)
    bar = ts.barDuration.quarterLength
    end = max((q.start + q.length for q in allq), default=bar)
    total = max(bar, bar * -(-end // bar))  # 小節の区切りまで切り上げ

    beat, sub = (1.5, 0.5) if time_signature == "6/8" else (1.0, 0.5)

    def add_rests(part, t0, t1):
        for start, length in _rest_pieces(float(t0), float(t1), beat, sub, bar, half_bar_rests=time_signature == "4/4"):
            r = note.Rest()
            r.quarterLength = _to_fraction(length)
            part.insert(_to_fraction(start), r)

    def make_part(qnotes: list[QNote], is_right: bool):
        part = stream.Part()
        part.id = "RH" if is_right else "LH"
        piano = instrument.Piano()
        piano.instrumentName = piano.partName = piano.instrumentAbbreviation = piano.partAbbreviation = ""
        part.partName = part.partAbbreviation = ""
        part.insert(0, piano)
        part.insert(0, clef.TrebleClef() if is_right else clef.BassClef())
        part.insert(0, key.KeySignature(k.sharps))
        part.insert(0, meter.TimeSignature(time_signature))
        if is_right:
            part.insert(0, tempo.MetronomeMark(number=round(bpm)))
        cursor = Fraction(0)
        for start, pitches, length in _events(qnotes, total):
            start, length = _to_fraction(start), _to_fraction(length)
            add_rests(part, cursor, start)
            el = note.Note(_pitch(pitches[0], use_flats)) if len(pitches) == 1 else chord.Chord([_pitch(p, use_flats) for p in pitches])
            el.quarterLength = length
            part.insert(start, el)
            cursor = start + length
        add_rests(part, cursor, _to_fraction(total))
        part = part.makeMeasures()
        part.makeTies(inPlace=True)
        return part

    sc = stream.Score()
    sc.insert(0, metadata.Metadata())
    sc.metadata.title = title or "Untitled"
    sc.metadata.composer = "synthmatch（自動採譜）"
    rh, lh = make_part(right, True), make_part(left, False)
    sc.insert(0, rh)
    sc.insert(0, lh)
    sc.insert(0, layout.StaffGroup([rh, lh], name="", symbol="brace", barTogether=True))

    info = ScoreInfo(
        key=_key_name(k),
        key_sharps=k.sharps,
        key_candidates=[
            {"key": _key_name(c), "sharps": c.sharps, "confidence": round(float(c.correlationCoefficient or 0), 3)}
            for c in candidates[:5]
        ],
        time_signature=time_signature,
        bpm=round(bpm, 1),
        measures=int(total // bar),
        notes=len(allq),
    )
    return sc, info
