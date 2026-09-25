"""ハードウェアシンセ：MIDIで音色を切り替えて鳴らし、オーディオ入力から録音する。

必要なもの: pip install -e ".[hardware]"（python-rtmidi, sounddevice）
設定は instruments/*.toml、音色一覧は CSV（name,category,msb,lsb,pc）。
"""

from __future__ import annotations

import csv
import time
from pathlib import Path

import numpy as np

from ..audio import to_mono
from ..notes import Note, end_time
from .base import Instrument, Preset


def read_preset_csv(path: Path) -> list[Preset]:
    """コメント行（#）を除いた CSV を読む。pc は取扱説明書どおり 1〜128 で書く。"""
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    presets = []
    for i, row in enumerate(csv.DictReader(lines)):
        presets.append(
            Preset(
                id=f"{row['msb']}-{row['lsb']}-{row['pc']}",
                name=row["name"].strip(),
                category=row.get("category", "").strip(),
                data={"msb": int(row["msb"]), "lsb": int(row["lsb"]), "pc": int(row["pc"])},
            )
        )
    return presets


def _find(names: list[str], wanted: str, kind: str) -> str:
    for n in names:
        if wanted.lower() in n.lower():
            return n
    raise RuntimeError(f"{kind} '{wanted}' が見つかりません。候補: {names}\n`synthmatch devices` で確認してください。")


class HardwareInstrument(Instrument):
    def __init__(self, config: dict, base_dir: Path):
        self.name = config.get("name", "Hardware Synth")
        midi = config.get("midi", {})
        audio = config.get("audio", {})
        timing = config.get("timing", {})
        self.midi_port_name = midi.get("output_port", "")
        self.channel = int(midi.get("channel", 1)) - 1
        self.input_device = audio.get("input_device", "")
        self.input_channels = [int(c) for c in audio.get("input_channels", [1, 2])]
        self.sample_rate = int(audio.get("sample_rate", 48000))
        self.preroll = float(timing.get("preroll", 0.3))
        self.program_change_wait = float(timing.get("program_change_wait", 0.5))
        self.controls = config.get("controls", {})
        self._presets = read_preset_csv(base_dir / config["presets"])
        self._port = None
        self._current = None

    def presets(self) -> list[Preset]:
        return self._presets

    def _open(self):
        if self._port is None:
            import mido

            name = _find(mido.get_output_names(), self.midi_port_name, "MIDI出力ポート")
            self._port = mido.open_output(name)
        return self._port

    def _send(self, msg_type: str, **kw) -> None:
        import mido

        self._open().send(mido.Message(msg_type, channel=self.channel, **kw))

    def select(self, preset: Preset) -> None:
        if self._current == preset.id:
            return
        d = preset.data
        self._send("control_change", control=0, value=d["msb"])
        self._send("control_change", control=32, value=d["lsb"])
        self._send("program_change", program=d["pc"] - 1)
        time.sleep(self.program_change_wait)
        self._current = preset.id

    def render(self, preset: Preset, notes: list[Note], tail: float = 2.0) -> np.ndarray:
        import mido
        import sounddevice as sd

        self.select(preset)
        port = self._open()
        device = _find([d["name"] for d in sd.query_devices()], self.input_device, "オーディオ入力") if self.input_device else None
        events = sorted(
            [(n.start, mido.Message("note_on", channel=self.channel, note=n.pitch, velocity=n.velocity)) for n in notes]
            + [(n.end, mido.Message("note_off", channel=self.channel, note=n.pitch)) for n in notes],
            key=lambda e: e[0],
        )
        length = self.preroll + end_time(notes) + tail
        mapping = self.input_channels
        rec = sd.rec(int(length * self.sample_rate), samplerate=self.sample_rate, channels=len(mapping), mapping=mapping, device=device)
        t0 = time.perf_counter() + self.preroll
        try:
            for when, msg in events:
                delay = t0 + when - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                port.send(msg)
        finally:
            self._send("control_change", control=123, value=0)  # All Notes Off
        sd.wait()
        y = to_mono(rec)
        return self._align(y, notes)

    def _align(self, y: np.ndarray, notes: list[Note]) -> np.ndarray:
        """オーディオ遅延を補正する：最初の発音位置が notes[0].start に来るように切り出す。"""
        env = np.abs(y)
        thresh = env.max() * 10 ** (-40 / 20)
        above = np.flatnonzero(env > thresh)
        onset = above[0] if above.size else int(self.preroll * self.sample_rate)
        first = min(n.start for n in notes) if notes else 0.0
        start = max(onset - int(first * self.sample_rate) - int(0.005 * self.sample_rate), 0)
        return y[start:].astype(np.float32)

    def close(self) -> None:
        if self._port is not None:
            self._port.close()
            self._port = None


def query_devices() -> dict:
    """MIDI出力ポートとオーディオ入力デバイスの一覧。取得できなかったものは errors に入る。"""
    info: dict = {"midi_outputs": [], "audio_inputs": [], "errors": []}
    try:
        import mido

        info["midi_outputs"] = list(mido.get_output_names())
    except Exception as e:  # noqa: BLE001
        info["errors"].append(f"MIDI: {e}（pip install -e '.[hardware]' が必要）")
    try:
        import sounddevice as sd

        info["audio_inputs"] = [
            {"name": d["name"], "channels": int(d["max_input_channels"]), "sample_rate": int(d["default_samplerate"])}
            for d in sd.query_devices()
            if d["max_input_channels"] > 0
        ]
    except Exception as e:  # noqa: BLE001
        info["errors"].append(f"Audio: {e}（pip install -e '.[hardware]' が必要）")
    return info


def list_devices() -> str:
    info = query_devices()
    lines = ["MIDI出力ポート:"]
    lines += [f"  - {n}" for n in info["midi_outputs"]] or ["  (なし)"]
    lines.append("オーディオ入力デバイス:")
    lines += [f"  - {d['name']} (入力 {d['channels']}ch, {d['sample_rate']}Hz)" for d in info["audio_inputs"]] or ["  (なし)"]
    lines += info["errors"]
    return "\n".join(lines)
