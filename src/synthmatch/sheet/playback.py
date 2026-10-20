"""採譜結果・楽譜を、ピアノの音で鳴らして wav にする。

FluidSynth（brew install fluid-synth）と SoundFont（FluidR3Mono_GM、MIT ライセンス、約24MB。初回に自動で取得）で
本物のピアノの録音に近い音を出す。使えないときは numpy の簡易ピアノ音で代わりに鳴らす。
"""

from __future__ import annotations

import shutil
import subprocess
import urllib.request
from pathlib import Path

import numpy as np

from .. import audio
from ..notes import Note, read_midi

SOUNDFONT_URL = "https://github.com/musescore/MuseScore/raw/v3.6.2/share/sound/FluidR3Mono_GM.sf3"
SOUNDFONT_PATH = Path.home() / ".cache" / "synthmatch" / "FluidR3Mono_GM.sf3"
SOUNDFONT_BYTES = 20_000_000


def ensure_soundfont(log=print) -> Path | None:
    """SoundFont を用意する。ダウンロードできなければ None。"""
    if SOUNDFONT_PATH.exists() and SOUNDFONT_PATH.stat().st_size >= SOUNDFONT_BYTES:
        return SOUNDFONT_PATH
    try:
        SOUNDFONT_PATH.parent.mkdir(parents=True, exist_ok=True)
        log("  ピアノの音源（SoundFont・約24MB）をダウンロードしています（初回のみ）…")
        tmp = SOUNDFONT_PATH.with_suffix(".part")
        urllib.request.urlretrieve(SOUNDFONT_URL, tmp)
        if tmp.stat().st_size < SOUNDFONT_BYTES:
            tmp.unlink()
            return None
        tmp.rename(SOUNDFONT_PATH)
        return SOUNDFONT_PATH
    except OSError:
        return None


def simple_piano(notes: list[Note], sr: int = 22050, tail: float = 1.5) -> np.ndarray:
    """FluidSynth が使えないときの代わり：倍音が減衰していく簡単なピアノ風の音。"""
    end = max((n.end for n in notes), default=0.0) + tail
    out = np.zeros(int(end * sr) + 1, dtype=np.float32)
    for n in notes:
        f0 = 440.0 * 2 ** ((n.pitch - 69) / 12)
        length = int((n.end - n.start + 0.25) * sr)
        t = np.arange(length) / sr
        decay = 1.2 + max(n.pitch - 40, 0) * 0.06  # 高い音ほど早く減衰
        x = np.zeros(length, dtype=np.float32)
        for k in range(1, 7):
            if f0 * k > sr / 2:
                break
            x += np.sin(2 * np.pi * f0 * k * t) * np.exp(-t * decay * (1 + 0.6 * k)) / k**1.5
        gate = int((n.end - n.start) * sr)
        rel = np.ones(length, dtype=np.float32)
        rel[gate:] = np.exp(-np.arange(length - gate) / (0.08 * sr))
        attack = np.minimum(1.0, np.arange(length) / (0.004 * sr))
        s = int(n.start * sr)
        seg = out[s : s + length]
        seg += (x * rel * attack * (n.velocity / 127))[: len(seg)]
    peak = np.max(np.abs(out))
    return out / peak * 0.8 if peak > 0 else out


def _apply_pedal(notes: list[Note], pedals: list[tuple[float, float]]) -> list[Note]:
    """簡易音用：ペダルを踏んでいる間に離した音は、ペダルを離すまで伸ばす。"""
    out = []
    for n in notes:
        end = n.end
        for on, off in pedals:
            if on <= n.end < off:
                end = max(end, off)
        out.append(Note(n.pitch, n.start, end, n.velocity))
    return out


def render_midi(midi: Path, wav: Path, offset: float = 0.0, log=print) -> str:
    """MIDI をピアノの音で wav にする。offset 秒の無音を先頭に足す（原曲と頭をそろえるため）。

    戻り値は使った方法（"fluidsynth" または "simple"）。
    """
    sr = 44100
    sf2 = ensure_soundfont(log) if shutil.which("fluidsynth") else None
    if sf2 is not None:
        tmp = wav.with_suffix(".fs.wav")
        r = subprocess.run(
            ["fluidsynth", "-ni", "-q", "-g", "0.8", "-r", str(sr), "-F", str(tmp), str(sf2), str(midi)],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and tmp.exists():
            y, _ = audio.load(tmp, sr=sr)
            tmp.unlink()
            method = "fluidsynth"
        else:
            tmp.unlink(missing_ok=True)
            sf2 = None
    if sf2 is None:
        from ..notes import read_pedals

        y = simple_piano(_apply_pedal(read_midi(midi), read_pedals(midi)), sr=sr)
        method = "simple"
    if offset > 0:
        y = np.concatenate([np.zeros(int(offset * sr), dtype=np.float32), y])
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak > 0:
        y = y / peak * 0.8
    audio.save(wav, y, sr)
    return method
