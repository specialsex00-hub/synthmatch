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
    modulations: list[dict]  # 転調（measure: 何小節目から / key / sharps）。最初の調は含まない
    key_plan: list[dict]  # 調号の区間（beat: 何拍目から / measure / sharps / key）。最初の区間も含む
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
        nxt_start = starts[i + 1] if i + 1 < len(starts) else total
        limit = None if nxt_start is None else nxt_start - s
        out.append((s, sorted({q.pitch for q in g}), _tidy_length(s, length, limit)))
    return out


def _tidy_length(start, length, limit):
    """長い音の終わりを、読みやすい位置にそろえる。

    2拍以上の音は拍の頭、1拍以上の音は半拍の位置まで伸ばす（次の音・曲の終わり limit を越えない場合だけ）。
    鍵盤を離すのが少し早かっただけで「3と¾拍（三重付点）」のような書き方になるのを防ぐ。
    """
    end = start + length
    step = 1 if length >= 2 else Fraction(1, 2) if length >= 1 else None
    if step is None:
        return length
    snapped = -(-Fraction(end).limit_denominator(48) // step) * step  # step の倍数に切り上げ
    if snapped - end <= Fraction(1, 4) and (limit is None or snapped - start <= limit):
        return snapped - start
    return length


# 1つの音符（付点は1つまで）で書ける長さ。3連符の長さも含む
_PLAIN = {Fraction(x) for x in ("4", "3", "2", "3/2", "1", "3/4", "1/2", "3/8", "1/4", "1/8")}
_PLAIN |= {Fraction(x) for x in ("4/3", "2/3", "1/3", "1/6")}


def _note_pieces(start: Fraction, length: Fraction, beat: Fraction) -> list[tuple[Fraction, Fraction]]:
    """1つの音符で書けない長さ（複付点・三重付点になる長さ）を、タイでつなぐ複数の音符に分ける。

    拍の途中から始まる音は、まず次の拍の区切りまでで分ける。
    """
    out = []
    t, rest = start, length
    while rest > 0:
        if rest in _PLAIN:
            out.append((t, rest))
            break
        to_beat = beat - (t % beat)
        if to_beat < rest and to_beat in _PLAIN and to_beat != beat:
            piece = to_beat
        else:
            piece = max((p for p in _PLAIN if p <= rest), default=rest)
        out.append((t, piece))
        t, rest = t + piece, rest - piece
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
    """調号に合わせて書き分ける（♭系の調なら D♭・G♭、♯系の調なら C♯・F♯ …）。"""
    from music21 import pitch

    p = pitch.Pitch(midi=midi)
    wrong = "sharp" if use_flats else "flat"
    if p.accidental is not None and p.accidental.name == wrong:
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


def key_segments(
    qnotes: list[QNote],
    bar: float,
    total: float,
    block_bars: int = 4,
    min_bars: int = 8,
    change_penalty: float = 0.15,
) -> list[tuple[int, object]]:
    """転調を見つけて、（何小節目から〈0始まり〉, music21 の Key）の一覧を返す。

    1. 曲を block_bars 小節ずつのまとまりに区切り、まとまりごとに各調号の当てはまり（相関）を出す。
       同じ調号の長調・短調（変ニ長調と変ロ短調など）は区別しない。
    2. 調号を変えるたびに change_penalty を引いて、合計がいちばん高くなる調号の並びを動的計画法で選ぶ。
       1つのまとまりだけ調がぶれるような細かい切り替えを防ぐため。
    3. min_bars 小節より短く終わる調は、前の調にまとめる。
    """
    block = bar * block_bars
    nblocks = max(1, int(-(-total // block)))
    sigs = list(range(-6, 7))
    scores = []
    for b in range(nblocks):
        notes = [q for q in qnotes if b * block <= q.start < (b + 1) * block]
        sc = {s: 0.0 for s in sigs}
        if len(notes) >= 6:  # 音が少ないまとまりは判断しない（どの調号も同じ点）
            for k in estimate_key(notes):
                if k.sharps in sc:
                    sc[k.sharps] = max(sc[k.sharps], float(k.correlationCoefficient or 0))
        scores.append(sc)

    # 動的計画法（ビタビ）
    best = [dict(scores[0])]
    back: list[dict] = [{}]
    for b in range(1, nblocks):
        cur, bk = {}, {}
        prev = best[-1]
        top = max(prev, key=prev.get)
        for s_ in sigs:
            stay, move = prev[s_], prev[top] - change_penalty
            cur[s_], bk[s_] = (stay, s_) if stay >= move else (move, top)
            cur[s_] += scores[b][s_]
        best.append(cur)
        back.append(bk)
    path = [max(best[-1], key=best[-1].get)]
    for b in range(nblocks - 1, 0, -1):
        path.append(back[b][path[-1]])
    path.reverse()

    # 区間にまとめ、短すぎる区間は前の区間に吸収する
    segs: list[list[int]] = []  # [開始まとまり, 終了まとまり(含まない), 調号]
    for b, s_ in enumerate(path):
        if segs and segs[-1][2] == s_:
            segs[-1][1] = b + 1
        else:
            segs.append([b, b + 1, s_])
    min_blocks = max(1, min_bars // block_bars)
    merged: list[list[int]] = []
    for seg in segs:
        if merged and (seg[1] - seg[0] < min_blocks or merged[-1][2] == seg[2]):
            merged[-1][1] = seg[1]
        else:
            merged.append(seg)
    if len(merged) > 1 and merged[0][1] - merged[0][0] < min_blocks:
        merged[1][0] = merged[0][0]
        merged.pop(0)

    # 区間ごとに、その調号の長調・短調のどちらかを選ぶ
    out = []
    for b0, b1, s_ in merged:
        notes = [q for q in qnotes if b0 * block <= q.start < b1 * block]
        cands = estimate_key(notes) if notes else []
        k = next((c for c in cands if c.sharps == s_), None)
        if k is None:
            from music21 import key

            k = key.KeySignature(s_).asKey("major")
        out.append((b0 * block_bars, k))
    return out


def build_score(
    right: list[QNote],
    left: list[QNote],
    bpm: float,
    time_signature: str = "4/4",
    title: str = "",
    key_sharps: int | None = None,
    modulation: bool = True,
    key_plan: list[tuple[float, int]] | None = None,
):
    """music21 の Score と ScoreInfo を返す。

    調号の決め方（上ほど優先）:
      key_plan    （何拍目から, 調号）の一覧で区間ごとに指定する。拍は小節の頭にそろえる
      key_sharps  曲全体をその調号（♯なら正、♭なら負）で書く
      どちらもなし 自動で推定する。modulation=True なら転調も見つけて途中に新しい調号を入れる
    """
    from music21 import bar as barline, chord, clef, instrument, key, layout, metadata, meter, note, stream, tempo, tie
    from music21.stream.makeNotation import makeAccidentalsInMeasureStream

    allq = right + left
    candidates = estimate_key(allq)

    ts = meter.TimeSignature(time_signature)
    bar = ts.barDuration.quarterLength
    end = max((q.start + q.length for q in allq), default=bar)
    total = max(bar, bar * -(-end // bar))  # 小節の区切りまで切り上げ

    def key_for(sig: int, notes: list[QNote]):
        """指定された調号の中で、いちばん確からしい長調・短調を選ぶ。"""
        cands = estimate_key(notes) if notes else candidates
        return next((c for c in cands if c.sharps == sig), None) or key.KeySignature(sig).asKey("major")

    if key_plan:
        # 拍を小節の頭にそろえ、同じ小節・同じ調号が続くものはまとめる
        plan: list[tuple[int, int]] = []
        for b, sig in sorted(key_plan):
            m = max(0, int(round(float(b) / bar)))
            if plan and plan[-1][0] == m:
                plan[-1] = (m, sig)
            elif not plan or plan[-1][1] != sig:
                plan.append((m, sig))
        plan[0] = (0, plan[0][1])
        bounds = [m for m, _ in plan] + [int(total // bar) + 1]
        segments = [
            (m, key_for(sig, [q for q in allq if m * bar <= q.start < bounds[i + 1] * bar]))
            for i, (m, sig) in enumerate(plan)
        ]
    elif key_sharps is not None:
        segments = [(0, key_for(key_sharps, allq))]
    elif modulation and allq:
        segments = key_segments(allq, bar, total)
    else:
        segments = [(0, candidates[0])]
    k = segments[0][1]
    starts = [m for m, _ in segments]

    def key_at(offset) -> object:
        measure = int(float(offset) // bar)
        i = max(j for j, m in enumerate(starts) if m <= measure)
        return segments[i][1]

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
            use_flats = key_at(start).sharps < 0
            pieces = _note_pieces(start, length, _to_fraction(beat))
            for j, (t, ln) in enumerate(pieces):
                el = note.Note(_pitch(pitches[0], use_flats)) if len(pitches) == 1 else chord.Chord([_pitch(p, use_flats) for p in pitches])
                el.quarterLength = ln
                if len(pieces) > 1:
                    el.tie = tie.Tie("start" if j == 0 else "stop" if j == len(pieces) - 1 else "continue")
                part.insert(t, el)
            cursor = start + length
        add_rests(part, cursor, _to_fraction(total))
        part = part.makeMeasures()
        part.makeTies(inPlace=True)
        measures = list(part.getElementsByClass(stream.Measure))
        for m, seg_key in segments[1:]:
            if m < len(measures):
                measures[m].insert(0, key.KeySignature(seg_key.sharps))
                if m > 0:
                    measures[m - 1].rightBarline = barline.Barline("light-light")  # 転調の前は複縦線
        # 調号を見て臨時記号を付け直す。music21 は小節を作る途中で「臨時記号は決めた」という印を付けるため、
        # そのままだと書き出し時に調号が考慮されず、調号どおりの♭にまで♭が付いてしまう
        makeAccidentalsInMeasureStream(part, useKeySignature=True, overrideStatus=True)
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
        modulations=[{"measure": m + 1, "key": _key_name(kk), "sharps": kk.sharps} for m, kk in segments[1:]],
        key_plan=[
            {"beat": float(m * bar), "measure": m + 1, "key": _key_name(kk), "sharps": kk.sharps} for m, kk in segments
        ],
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
