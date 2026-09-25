"""動作確認用の簡易減算シンセ（numpyのみ）。

実機がなくても全体を動かせるようにするためのもの。
テストでは「既知の音色を少しいじった音」を正しく当てられるかの確認に使う。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from scipy import signal

from ..notes import Note, end_time
from .base import Instrument, Preset


@dataclass(frozen=True)
class DemoPatch:
    wave: str = "saw"  # saw / square / triangle / sine
    unison: int = 1
    detune_cents: float = 0.0
    octave: int = 0
    cutoff: float = 4000.0  # フィルターの基本カットオフ (Hz)
    filter_env: float = 0.0  # アタック時にカットオフを何オクターブ開くか
    filter_decay: float = 0.3  # フィルターエンベロープの減衰 (秒)
    attack: float = 0.005
    decay: float = 0.2
    sustain: float = 1.0
    release: float = 0.1
    noise: float = 0.0
    reverb: float = 0.0  # 0〜1


PATCHES: dict[str, tuple[str, DemoPatch]] = {
    "Saw Lead": ("Lead", DemoPatch("saw", 2, 8, cutoff=5000, release=0.15)),
    "Square Lead": ("Lead", DemoPatch("square", cutoff=3000, release=0.1)),
    "Sine Lead": ("Lead", DemoPatch("sine", cutoff=8000, attack=0.02, release=0.2, reverb=0.2)),
    "Soft Pad": ("Pad", DemoPatch("saw", 3, 12, cutoff=1200, attack=0.6, release=1.2, reverb=0.4)),
    "String Pad": ("Pad", DemoPatch("saw", 4, 18, cutoff=3000, attack=0.35, release=0.8, reverb=0.3)),
    "Warm Pad": ("Pad", DemoPatch("triangle", 2, 6, cutoff=900, attack=0.8, release=1.5, reverb=0.5)),
    "Brass": ("Brass", DemoPatch("saw", 2, 5, cutoff=900, filter_env=2.0, filter_decay=0.25, attack=0.04, sustain=0.8, release=0.2)),
    "Pluck": ("Pluck", DemoPatch("saw", cutoff=600, filter_env=3.0, filter_decay=0.12, decay=0.35, sustain=0.0, release=0.3, reverb=0.2)),
    "Bell": ("Keys", DemoPatch("sine", octave=1, cutoff=8000, decay=1.2, sustain=0.0, release=1.0, reverb=0.3)),
    "Organ": ("Keys", DemoPatch("square", 2, 3, cutoff=2500, attack=0.003, release=0.05)),
    "Synth Bass": ("Bass", DemoPatch("saw", octave=-1, cutoff=500, filter_env=2.0, filter_decay=0.15, sustain=0.7, release=0.08)),
    "Noise Sweep": ("FX", DemoPatch("saw", cutoff=2000, noise=0.6, attack=0.3, release=0.8, reverb=0.4)),
}


def _osc(wave: str, freq: float, t: np.ndarray, phase: float) -> np.ndarray:
    ph = (freq * t + phase) % 1.0
    if wave == "saw":
        return 2.0 * ph - 1.0
    if wave == "square":
        return np.where(ph < 0.5, 1.0, -1.0)
    if wave == "triangle":
        return 4.0 * np.abs(ph - 0.5) - 1.0
    return np.sin(2 * np.pi * ph)


def _adsr(p: DemoPatch, n: int, gate: int, sr: int) -> np.ndarray:
    a = max(int(p.attack * sr), 1)
    d = max(int(p.decay * sr), 1)
    idx = np.arange(n)
    # アタック → ディケイ → サステイン
    decay_part = p.sustain + (1 - p.sustain) * np.exp(-np.maximum(idx - a, 0) / (d / 4))
    env = np.where(idx < a, idx / a, decay_part)
    # ノートオフ時点のレベルからリリース
    level = env[min(gate, n - 1)] if gate < n else env[-1]
    r = max(p.release * sr, 1)
    after = idx >= gate
    env[after] = level * np.exp(-(idx[after] - gate) / (r / 5))
    return env


def render_patch(p: DemoPatch, notes: list[Note], sr: int = 44100, tail: float = 2.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    total = int((end_time(notes) + tail) * sr) + 1
    out = np.zeros(total, dtype=np.float64)
    nyq = sr / 2
    dark = signal.butter(2, min(p.cutoff, nyq * 0.9) / nyq, output="sos")
    bright = signal.butter(2, min(p.cutoff * 2**p.filter_env, nyq * 0.9) / nyq, output="sos")
    for note in notes:
        start = int(note.start * sr)
        gate = int(note.duration * sr)
        n = min(gate + int(p.release * sr * 1.5) + 1, total - start)
        if n <= 0:
            continue
        t = np.arange(n) / sr
        freq = 440.0 * 2 ** ((note.pitch - 69 + 12 * p.octave) / 12)
        x = np.zeros(n)
        for u in range(p.unison):
            spread = 0.0 if p.unison == 1 else (u / (p.unison - 1) - 0.5) * 2
            f = freq * 2 ** (spread * p.detune_cents / 1200)
            x += _osc(p.wave, f, t, rng.random())
        x /= p.unison
        if p.noise:
            x = (1 - p.noise) * x + p.noise * rng.uniform(-1, 1, n)
        if p.filter_env > 0:
            fenv = np.exp(-t / max(p.filter_decay, 1e-3))
            x = fenv * signal.sosfilt(bright, x) + (1 - fenv) * signal.sosfilt(dark, x)
        else:
            x = signal.sosfilt(dark, x)
        out[start : start + n] += x * _adsr(p, n, gate, sr) * (note.velocity / 127)
    if p.reverb > 0:
        ir_len = int(1.8 * sr)
        ir = rng.standard_normal(ir_len) * np.exp(-np.arange(ir_len) / (0.35 * sr))
        wet = signal.fftconvolve(out, ir)[:total]
        wet *= np.max(np.abs(out)) / (np.max(np.abs(wet)) + 1e-9)
        out = (1 - p.reverb * 0.5) * out + p.reverb * wet
    peak = np.max(np.abs(out))
    return (out / peak * 0.8 if peak > 0 else out).astype(np.float32)


class DemoInstrument(Instrument):
    name = "Demo Synth"
    controls = {
        "cutoff": "Cutoff",
        "attack": "Amp Attack",
        "sustain": "Amp Sustain / Decay",
        "release": "Amp Release",
        "reverb": "Reverb",
        "noise": "Noise",
    }

    def __init__(self, config: dict | None = None, base_dir=None):
        self.sample_rate = int((config or {}).get("sample_rate", 44100))

    def presets(self) -> list[Preset]:
        return [
            Preset(id=f"demo-{i:03d}", name=name, category=cat, data={"patch": patch})
            for i, (name, (cat, patch)) in enumerate(PATCHES.items())
        ]

    def render(self, preset: Preset, notes: list[Note], tail: float = 2.0) -> np.ndarray:
        return render_patch(preset.data["patch"], notes, self.sample_rate, tail)

    @staticmethod
    def variant(name: str, **changes) -> DemoPatch:
        """既存パッチを少し変えたもの（テスト・デモ用）。"""
        return replace(PATCHES[name][1], **changes)
