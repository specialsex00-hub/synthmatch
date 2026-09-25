"""目標の音と候補の音の特徴量の差から、音作りの調整案を文章で出す。"""

from __future__ import annotations

import numpy as np

DEFAULT_CONTROLS = {
    "cutoff": "フィルターのカットオフ",
    "attack": "アンプエンベロープのアタック",
    "sustain": "アンプエンベロープのサステイン／ディケイ",
    "release": "アンプエンベロープのリリース",
    "reverb": "リバーブ／ディレイ",
    "noise": "ノイズ成分（ノイズOSC・ドライブ）",
}


def make_hints(target: dict[str, np.ndarray], candidate: dict[str, np.ndarray], controls: dict[str, str] | None = None) -> list[str]:
    c = {**DEFAULT_CONTROLS, **(controls or {})}
    hints: list[str] = []

    d = float(target["brightness"][0] - candidate["brightness"][0])
    if abs(d) >= 0.25:
        way = "上げる（もっと明るく）" if d > 0 else "下げる（もっと暗く）"
        hints.append(f"{c['cutoff']}を{way}：約{abs(d):.1f}オクターブ分")

    ta, ts, tr = target["envelope"]
    ca, cs, cr = candidate["envelope"]
    if np.isfinite(ta) and np.isfinite(ca):
        diff = ta - ca
        if abs(diff) >= 0.03 and (max(ta, ca) / max(min(ta, ca), 0.01)) >= 1.5:
            way = "長く（ゆっくり立ち上がる）" if diff > 0 else "短く（速く立ち上がる）"
            hints.append(f"{c['attack']}を{way}：目標 約{ta * 1000:.0f}ms / 現在 約{ca * 1000:.0f}ms")
    if np.isfinite(ts) and np.isfinite(cs) and abs(ts - cs) >= 4:
        way = "上げる（伸ばしている間に音が減りすぎ）" if ts > cs else "下げる（押さえている間にもっと減衰させる）"
        hints.append(f"{c['sustain']}を{way}")
    if np.isfinite(tr) and np.isfinite(cr) and abs(tr - cr) >= 0.15:
        way = "長く／深くする" if tr > cr else "短く／浅くする"
        hints.append(f"{c['release']}または{c['reverb']}を{way}：余韻 目標 約{tr:.2f}s / 現在 約{cr:.2f}s")

    # フィルターを開くとノイズっぽさも増えるので、明るさの差で説明できる場合は出さない
    dn = float(target["flatness"][0] - candidate["flatness"][0])
    if abs(dn) >= 0.5 and not (abs(d) >= 0.25 and np.sign(d) == np.sign(dn)):
        way = "増やす" if dn > 0 else "減らす"
        hints.append(f"{c['noise']}を{way}")

    return hints
