"""音色の特徴量。

グループごとに名前付きで持ち、照合（matcher）とヒント（hints）の両方で使う。
- mel_shape / mfcc_*: スペクトルの形（音色の「キャラ」）
- brightness: 基音に対するスペクトル重心の高さ（オクターブ）→ フィルターの開き具合
- flatness: ノイズっぽさ
- contrast: 倍音のピークと谷の差
- envelope: [アタック秒, サステイン(dB), リリース+残響秒]
"""

from __future__ import annotations

import numpy as np

from .notes import Note

SR = 22050
N_FFT = 2048
HOP = 512
FRAME = HOP / SR

GROUPS: dict[str, int] = {
    "mel_shape": 48,
    "mfcc_mean": 19,
    "mfcc_std": 19,
    "brightness": 1,
    "flatness": 1,
    "contrast": 7,
    "envelope": 3,
}


def extract(y: np.ndarray, sr: int, notes: list[Note] | None = None) -> dict[str, np.ndarray]:
    import librosa

    y = np.asarray(y, dtype=np.float32)
    if sr != SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=SR)
    peak = np.max(np.abs(y)) if y.size else 0.0
    if peak <= 0:
        raise ValueError("無音の音声です")
    y = y / peak

    S = np.abs(librosa.stft(y, n_fft=N_FFT, hop_length=HOP))
    mel_db = librosa.power_to_db(librosa.feature.melspectrogram(S=S**2, sr=SR, n_mels=GROUPS["mel_shape"]), ref=np.max)
    rms_db = librosa.amplitude_to_db(librosa.feature.rms(S=S, frame_length=N_FFT)[0], ref=np.max)
    active = rms_db > -35
    if active.sum() < 3:
        active = rms_db > -60

    mfcc = librosa.feature.mfcc(S=mel_db, n_mfcc=20)[1:]  # 0次（音量）は除く
    centroid = librosa.feature.spectral_centroid(S=S, sr=SR)[0]
    flatness = librosa.feature.spectral_flatness(S=S)[0]
    contrast = librosa.feature.spectral_contrast(S=S, sr=SR)

    if notes is None:
        notes = _pseudo_notes(y)
    f0 = 440.0 * 2 ** ((np.median([n.pitch for n in notes]) - 69) / 12) if notes else 261.6

    shape = mel_db[:, active].mean(axis=1)
    return {
        "mel_shape": shape - shape.mean(),
        "mfcc_mean": mfcc[:, active].mean(axis=1),
        "mfcc_std": mfcc[:, active].std(axis=1),
        "brightness": np.array([np.log2(np.median(centroid[active]) / f0)]),
        "flatness": np.array([np.log10(np.median(flatness[active]) + 1e-8)]),
        "contrast": contrast[:, active].mean(axis=1),
        "envelope": envelope_features(rms_db, notes),
    }


def envelope_features(rms_db: np.ndarray, notes: list[Note]) -> np.ndarray:
    """ノート情報を使ってアタック・サステイン・リリースを測る（取れないものは NaN）。"""
    n_frames = len(rms_db)
    onsets = sorted(n.start for n in notes)
    attacks, sustains, releases = [], [], []
    for note in notes:
        on = int(note.start / FRAME)
        off = min(int(note.end / FRAME), n_frames - 1)
        if on >= n_frames - 2 or off - on < 2:
            continue
        seg = rms_db[on : off + 1]
        peak_i = int(np.argmax(seg))
        if note.duration >= 0.3:
            # デチューンのうねりで最大点が遅れて見えるので、最大から -6dB に届いた時点をアタックとする
            reach = np.flatnonzero(seg >= seg[peak_i] - 6)
            attacks.append(reach[0] * FRAME)
            sustains.append(float(seg[-1] - seg[peak_i]))
        # 次の発音まで 0.4 秒以上空いていればリリースを測る
        nxt = next((t for t in onsets if t > note.end - 1e-6), None)
        limit = int(nxt / FRAME) if nxt is not None else n_frames
        if limit - off >= int(0.4 / FRAME):
            level = rms_db[off]
            tail = rms_db[off:limit]
            below = np.flatnonzero(tail < level - 20)
            releases.append((below[0] if below.size else len(tail)) * FRAME)
    med = lambda v: float(np.median(v)) if v else np.nan  # noqa: E731
    return np.array([med(attacks), med(sustains), med(releases)])


def _pseudo_notes(y: np.ndarray) -> list[Note]:
    """ノート情報がないとき、オンセット検出で区間だけ作る（音高は C4 とする）。"""
    import librosa

    times = librosa.onset.onset_detect(y=y, sr=SR, hop_length=HOP, units="time")
    dur = len(y) / SR
    bounds = list(times) + [dur]
    return [Note(60, float(a), float(b)) for a, b in zip(bounds[:-1], bounds[1:])]


def to_vector(feats: dict[str, np.ndarray]) -> np.ndarray:
    return np.concatenate([np.asarray(feats[g], dtype=np.float64).ravel() for g in GROUPS])


def from_vector(vec: np.ndarray) -> dict[str, np.ndarray]:
    out, i = {}, 0
    for g, n in GROUPS.items():
        out[g] = vec[i : i + n]
        i += n
    return out


def group_slices() -> dict[str, slice]:
    out, i = {}, 0
    for g, n in GROUPS.items():
        out[g] = slice(i, i + n)
        i += n
    return out


def aligned_mel_distance(a: np.ndarray, b: np.ndarray, sr: int) -> float:
    """同じMIDIで鳴らした2つの音を時間をそろえて比べる（dB差の平均）。"""
    import librosa

    def logmel(y):
        y = librosa.resample(np.asarray(y, dtype=np.float32), orig_sr=sr, target_sr=SR) if sr != SR else y
        y = y / (np.max(np.abs(y)) + 1e-9)
        m = librosa.feature.melspectrogram(y=y, sr=SR, n_fft=N_FFT, hop_length=HOP, n_mels=64)
        return np.maximum(librosa.power_to_db(m, ref=np.max), -80)

    ma, mb = logmel(a), logmel(b)
    n = min(ma.shape[1], mb.shape[1])
    ma, mb = ma[:, :n], mb[:, :n]
    mask = (ma > -60) | (mb > -60)
    return float(np.abs(ma - mb)[mask].mean()) if mask.any() else 0.0
