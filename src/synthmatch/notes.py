"""ノート列（MIDI）の表現と入出力。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Note:
    pitch: int  # MIDIノート番号 (60 = C4)
    start: float  # 秒
    end: float  # 秒
    velocity: int = 100

    @property
    def duration(self) -> float:
        return self.end - self.start


def read_midi(path: str | Path) -> list[Note]:
    import pretty_midi

    pm = pretty_midi.PrettyMIDI(str(path))
    notes = [
        Note(n.pitch, float(n.start), float(n.end), n.velocity)
        for inst in pm.instruments
        if not inst.is_drum
        for n in inst.notes
    ]
    return sorted(notes, key=lambda n: (n.start, n.pitch))


def write_midi(notes: list[Note], path: str | Path) -> None:
    import pretty_midi

    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0, name="keys")
    for n in notes:
        inst.notes.append(pretty_midi.Note(n.velocity, n.pitch, n.start, n.end))
    pm.instruments.append(inst)
    pm.write(str(path))


def end_time(notes: list[Note]) -> float:
    return max((n.end for n in notes), default=0.0)


def clip_notes(notes: list[Note], seconds: float) -> list[Note]:
    """先頭 seconds 秒に収まるノートだけを残す（はみ出す分は切る）。"""
    return [
        Note(n.pitch, n.start, min(n.end, seconds), n.velocity)
        for n in notes
        if n.start < seconds - 0.05
    ]


def probe_notes() -> list[Note]:
    """音色ライブラリ作成用の共通フレーズ。

    長音（アタック・サステイン・リリースを見る）、短い連打、和音を
    3つの音域で鳴らす。各音の後に1秒の無音を置いてリリースや残響を測れるようにする。
    """
    notes: list[Note] = []
    t = 0.0
    for pitch in (48, 60, 72):
        notes.append(Note(pitch, t, t + 1.5, 100))
        t += 2.5
    for pitch in (60, 64, 67, 72):
        notes.append(Note(pitch, t, t + 0.2, 100))
        t += 0.3
    t += 1.0
    for pitch in (60, 64, 67):
        notes.append(Note(pitch, t, t + 1.5, 90))
    return notes
