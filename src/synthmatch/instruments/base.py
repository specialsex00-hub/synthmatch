"""楽器（音色を持ち、MIDIを鳴らして音を返すもの）の共通インターフェース。

新しい楽器に対応するには Instrument を継承して presets() と render() を実装し、
instruments/__init__.py の INSTRUMENT_TYPES に登録する。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

from ..notes import Note


@dataclass
class Preset:
    id: str  # ライブラリ内で一意なID
    name: str
    category: str = ""
    data: dict = field(default_factory=dict)  # 楽器固有の情報（MIDIバンク番号など）


class Instrument(ABC):
    name: str = "instrument"
    sample_rate: int = 44100
    # ヒントに使う操作子の呼び名。例: {"cutoff": "CUTOFFツマミ"}
    controls: dict[str, str] = {}

    @abstractmethod
    def presets(self) -> list[Preset]:
        """この楽器で選べる音色の一覧。"""

    @abstractmethod
    def render(self, preset: Preset, notes: list[Note], tail: float = 2.0) -> np.ndarray:
        """preset で notes を鳴らしたモノラル音声を返す（先頭 = 時刻0）。"""

    def close(self) -> None:
        """MIDIポートなどを開いていれば閉じる。"""
