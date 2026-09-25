"""動作確認用の「目標音源」を作る。

デモシンセの音色を少しいじった音でフレーズを弾き、demo_keys.wav と demo_keys.mid を書き出す。
本物の楽曲の代わりに使い、正解の音色（とヒント）が出るかを確かめる。

    python scripts/make_demo_song.py --base "Soft Pad" --cutoff 600
"""

import argparse

from synthmatch import audio
from synthmatch.instruments.demo import DemoInstrument, render_patch
from synthmatch.notes import Note, write_midi


def phrase() -> list[Note]:
    notes, t = [], 0.0
    for chord in ([57, 60, 64], [53, 57, 60], [55, 59, 62], [52, 55, 59]):
        notes += [Note(p, t, t + 1.8, 95) for p in chord]
        t += 2.4
    for p in (69, 72, 76, 74, 72, 71, 72):
        notes.append(Note(p, t, t + 0.35, 105))
        t += 0.5
    return notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="Soft Pad")
    ap.add_argument("--cutoff", type=float)
    ap.add_argument("--attack", type=float)
    ap.add_argument("--release", type=float)
    ap.add_argument("-o", "--out", default="demo_keys")
    a = ap.parse_args()
    changes = {k: v for k, v in {"cutoff": a.cutoff, "attack": a.attack, "release": a.release}.items() if v is not None}
    patch = DemoInstrument.variant(a.base, **changes)
    notes = phrase()
    audio.save(f"{a.out}.wav", render_patch(patch, notes, seed=42), 44100)
    write_midi(notes, f"{a.out}.mid")
    print(f"{a.out}.wav / {a.out}.mid  （正解: {a.base} {changes}）")


if __name__ == "__main__":
    main()
