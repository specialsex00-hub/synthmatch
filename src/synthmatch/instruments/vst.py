"""VST3 / AU のソフトシンセ（実験的）。pip install -e ".[vst]"

プリセットは presets_dir にある .vstpreset ファイルを1つずつ読み込む。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..audio import to_mono
from ..notes import Note, end_time
from .base import Instrument, Preset


class VSTInstrument(Instrument):
    def __init__(self, config: dict, base_dir: Path):
        self.name = config.get("name", "VST Synth")
        self.plugin_path = config["plugin"]
        self.presets_dir = (base_dir / config["presets_dir"]).expanduser()
        self.sample_rate = int(config.get("sample_rate", 44100))
        self.controls = config.get("controls", {})
        self._plugin = None

    def _load(self):
        if self._plugin is None:
            from pedalboard import load_plugin

            self._plugin = load_plugin(self.plugin_path)
        return self._plugin

    def presets(self) -> list[Preset]:
        files = sorted(self.presets_dir.rglob("*.vstpreset"))
        return [
            Preset(id=str(f.relative_to(self.presets_dir)), name=f.stem, category=f.parent.name, data={"file": str(f)})
            for f in files
        ]

    def render(self, preset: Preset, notes: list[Note], tail: float = 2.0) -> np.ndarray:
        import mido

        plugin = self._load()
        plugin.load_preset(preset.data["file"])
        msgs = []
        for n in notes:
            msgs.append((mido.Message("note_on", note=n.pitch, velocity=n.velocity).bytes(), n.start))
            msgs.append((mido.Message("note_off", note=n.pitch).bytes(), n.end))
        msgs.sort(key=lambda m: m[1])
        out = plugin([(bytes(b), t) for b, t in msgs], duration=end_time(notes) + tail, sample_rate=self.sample_rate)
        return to_mono(np.asarray(out))
