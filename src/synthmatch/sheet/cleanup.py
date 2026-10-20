"""楽譜にする前の後片付け：採譜で拾った「弾いていない音」を除き、ほぼ同時の音を1つの和音にそろえる。

採譜モデルは、ペダルの残響や押さえたままの音を「もう一度弾いた」と誤って拾うことがある。
そのまま楽譜にすると、四分音符の和音が16分音符に細切れにされたりする。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..notes import Note

# 音を拾う量。ratio: 周りでいちばん強い音の何割より弱ければ除くか / min_dur: これより短い音は除く（秒）
SENSITIVITY = {
    "off": None,  # 除かない（採譜そのまま）
    "low": {"ratio": 0.8, "min_dur": 0.08},  # 少なめ：弱い音を多めに除く
    "normal": {"ratio": 0.65, "min_dur": 0.05},
    "high": {"ratio": 0.5, "min_dur": 0.03},  # 多め：弱い音もなるべく残す
}


@dataclass
class CleanupStats:
    removed: list[int]  # 除いた音（入力の何番目か）
    merged: int  # 和音にそろえた音の数（0.03秒以上ずれていたもの）


def remove_ghosts(notes: list[Note], ratio: float, min_dur: float, window: float = 0.6, chord_window: float = 0.06) -> list[int]:
    """除く音の番号を返す。

    次のどれかに当てはまる音を除く。
      1. 極端に短い（min_dur 秒未満）
      2. 同じ高さの、より強い音を押さえている途中で鳴った（押さえたままの音の再検出）
      3. 前後 window 秒でいちばん強い音の ratio 倍より弱く、しかも同時（chord_window 秒以内）に
         それ以上強い音を弾いていない（＝和音の一部ではない、ぽつんと鳴った弱い音）

    強い音から順に「残す音」を決め、2・3 の判定は残すと決めた音とだけ比べる。
    こうしないと、弱い誤検出どうしが「和音の一部」としてお互いを残してしまう。
    """
    order = sorted(range(len(notes)), key=lambda i: -notes[i].velocity)
    kept: list[Note] = []
    removed: list[int] = []
    for i in order:
        n = notes[i]
        loudest = max(m.velocity for m in notes if abs(m.start - n.start) <= window)
        held = any(m.pitch == n.pitch and m.start < n.start < m.end and m.velocity > n.velocity for m in kept)
        in_chord = any(abs(m.start - n.start) <= chord_window and m.velocity >= n.velocity for m in kept)
        weak = n.velocity < ratio * loudest and not in_chord
        if n.end - n.start < min_dur or held or weak:
            removed.append(i)
        else:
            kept.append(n)
    return sorted(removed)


def merge_chords(notes: list[Note], tight: float, loose: float = 0.12, weaker: float = 0.8) -> tuple[list[Note], int]:
    """ほぼ同時に弾いた音を、いちばん強い音の時刻にそろえる。

    そろえた音の数（0.03秒以上ずれていたものだけ。もともとほぼ同時の音は数えない）も返す。

    tight 秒以内の音はそのまま和音とみなす。loose 秒以内でも、強い音より明らかに弱い（weaker 倍未満）
    少し早い・遅い音は、アルペジオ気味の和音や前打音とみなしてそろえる。
    速い旋律の16分音符まで和音にしないよう、tight と loose はテンポから決める。
    """
    # 強い音から順に「和音の基準」にして、まだ引き取られていない近くの音をその時刻にそろえる
    order = sorted(range(len(notes)), key=lambda i: (-notes[i].velocity, notes[i].start))
    anchor_of: dict[int, int] = {}
    for a in order:
        if a in anchor_of:
            continue
        anchor_of[a] = a
        for i, n in enumerate(notes):
            gap = abs(notes[a].start - n.start)
            if i not in anchor_of and gap <= loose and (gap <= tight or n.velocity < weaker * notes[a].velocity):
                anchor_of[i] = a
    out, merged = [], 0
    for i, n in enumerate(notes):
        t = notes[anchor_of[i]].start
        gap = abs(t - n.start)
        if gap > 1e-9:
            out.append(Note(n.pitch, t, max(n.end, t + 0.05), n.velocity))
            merged += gap > 0.03
        else:
            out.append(n)
    return out, merged


def clean(notes: list[Note], tempo: float, sensitivity: str = "normal") -> tuple[list[Note], CleanupStats]:
    """幽霊の音を除き、ほぼ同時の音を和音にそろえる。sensitivity="off" なら何もしない。"""
    if sensitivity not in SENSITIVITY:
        raise ValueError(f"音を拾う量は {', '.join(SENSITIVITY)} から選んでください")
    opts = SENSITIVITY[sensitivity]
    if opts is None or not notes:
        return list(notes), CleanupStats([], 0)
    removed = remove_ghosts(notes, **opts)
    gone = set(removed)
    kept = [n for i, n in enumerate(notes) if i not in gone]
    sixteenth = 60.0 / tempo / 4
    kept, merged = merge_chords(kept, tight=min(0.06, 0.4 * sixteenth), loose=min(0.12, 0.6 * sixteenth))
    return sorted(kept, key=lambda n: (n.start, n.pitch)), CleanupStats(removed, merged)
