"""音声（mp3 / wav / mp4 / 動画）を読み込み、ピアノの音を MIDI のノートとして拾う。

backend:
  piano  ByteDance の高精度ピアノ採譜（Kong et al. 2021）。ペダルも拾う。初回にモデル（約170MB）をダウンロードする
  basic  basic-pitch / pyin（synthmatch.transcribe と同じ。ピアノ以外にも使えるが精度は落ちる）
"""

from __future__ import annotations

import shutil
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..notes import Note

MODEL_URL = "https://zenodo.org/record/4034264/files/CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth?download=1"
MODEL_PATH = Path.home() / "piano_transcription_inference_data" / "note_F1=0.9677_pedal_F1=0.9186.pth"
MODEL_MIN_BYTES = 160_000_000


@dataclass
class Transcription:
    notes: list[Note]
    pedals: list[tuple[float, float]] = field(default_factory=list)  # サステインペダル（踏んだ秒, 離した秒）


def decode_audio(src: str | Path, dst: str | Path, sr: int = 44100) -> Path:
    """ffmpeg で音声トラックだけをモノラル wav にする（動画もそのまま渡せる）。"""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg が見つかりません。`brew install ffmpeg` を実行してください。")
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", str(sr), str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not dst.exists():
        raise RuntimeError(f"音声を読み込めませんでした: {r.stderr.strip() or src}")
    return dst


def ensure_model(log=print) -> Path:
    if MODEL_PATH.exists() and MODEL_PATH.stat().st_size >= MODEL_MIN_BYTES:
        return MODEL_PATH
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    log("  ピアノ採譜モデルをダウンロードしています（初回のみ・約170MB）…")
    tmp = MODEL_PATH.with_suffix(".part")
    with urllib.request.urlopen(MODEL_URL) as res, open(tmp, "wb") as f:
        total = int(res.headers.get("Content-Length") or 0)
        done, next_report = 0, 0.1
        while chunk := res.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total and done / total >= next_report:
                log(f"  ダウンロード {int(done / total * 100)}%")
                next_report += 0.1
    if tmp.stat().st_size < MODEL_MIN_BYTES:
        tmp.unlink()
        raise RuntimeError("モデルのダウンロードに失敗しました。ネットワークを確認してもう一度試してください。")
    tmp.rename(MODEL_PATH)
    return MODEL_PATH


def _piano(wav16k: Path, log) -> Transcription:
    try:
        import torch
        from piano_transcription_inference import PianoTranscription
    except ImportError as e:
        raise RuntimeError("ピアノ採譜のパッケージが入っていません。pip install -e '.[sheet]' を実行してください。") from e
    import librosa

    model = ensure_model(log)
    y, _ = librosa.load(str(wav16k), sr=16000, mono=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    log(f"  ピアノの音を拾っています（{len(y) / 16000:.0f}秒の音声・数分かかることがあります）…")
    t = PianoTranscription(device=device, checkpoint_path=str(model))
    result = t.transcribe(y, None)
    notes = [
        Note(int(e["midi_note"]), float(e["onset_time"]), float(e["offset_time"]), int(e["velocity"]))
        for e in result["est_note_events"]
    ]
    pedals = [(float(e["onset_time"]), float(e["offset_time"])) for e in result["est_pedal_events"]]
    return Transcription(sorted(notes, key=lambda n: (n.start, n.pitch)), pedals)


def _basic(wav: Path, log) -> Transcription:
    from ..transcribe import transcribe

    return Transcription(transcribe(wav, backend="auto", log=log))


def transcribe_piano(wav: Path, wav16k: Path, backend: str = "piano", log=print) -> Transcription:
    if backend == "piano":
        return _piano(wav16k, log)
    if backend == "basic":
        return _basic(wav, log)
    raise ValueError(f"採譜方法 '{backend}' は未対応です（piano, basic）")


def synth_preview(notes: list[Note], sr: int = 22050, tail: float = 1.5) -> np.ndarray:
    """簡易ピアノ音（テスト用。実際の出力は playback.render_midi を使う）。"""
    from .playback import simple_piano

    return simple_piano(notes, sr=sr, tail=tail)
