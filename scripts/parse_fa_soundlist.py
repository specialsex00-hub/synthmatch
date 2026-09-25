"""Roland FA-06/07/08 のサウンド・リスト（PDF）から音色一覧 CSV を作る。

    curl -LO https://static.roland.com/assets/media/pdf/FA-06_07_08_SoundList_multi01_W.pdf
    pdftotext -layout FA-06_07_08_SoundList_multi01_W.pdf soundlist.txt
    python scripts/parse_fa_soundlist.py soundlist.txt instruments/fa06_presets.csv

対象は SuperNATURAL Acoustic / SuperNATURAL Synth / PCM Synth のプリセット音色。
ドラムキットと GM2 音色は除く。
"""

import csv
import re
import sys

ROW = re.compile(
    r"(?:^|\s)(\d{1,4})\s+(\S.*?)\s{2,}([A-Za-z]\S*(?: \S+)*?)\s+(\d{2,3})\s+(\d{1,3})\s+(\d{1,3})(?=\s|$)"
)
TYPES = {89: "SN-A", 95: "SN-S", 87: "PCM"}
# PDF の2段組みで見出しと重なり、1行にならない音色
MANUAL = {(89, 64, 52): ("B3 Jazz 3", "E.Organ"), (95, 64, 52): ("Soft Pad 11", "Synth Pad/Strings")}


def main(src: str, dst: str) -> None:
    tones = dict(MANUAL)
    for line in open(src, encoding="utf-8"):
        for m in ROW.finditer(line):
            _, name, cat, msb, lsb, pc = m.groups()
            key = (int(msb), int(lsb), int(pc))
            if key[0] in TYPES and 1 <= key[2] <= 128:
                tones.setdefault(key, (name.strip(), cat.strip()))
    with open(dst, "w", newline="", encoding="utf-8") as f:
        f.write("# Roland FA-06 プリセット音色（サウンド・リストから scripts/parse_fa_soundlist.py で生成）\n")
        f.write("# category は「種類:カテゴリ」。SN-A = SuperNATURAL Acoustic, SN-S = SuperNATURAL Synth, PCM = PCM Synth\n")
        w = csv.writer(f)
        w.writerow(["name", "category", "msb", "lsb", "pc"])
        for (msb, lsb, pc), (name, cat) in sorted(tones.items()):
            w.writerow([name, f"{TYPES[msb]}:{cat}", msb, lsb, pc])
    counts = {t: sum(1 for k in tones if TYPES[k[0]] == t) for t in TYPES.values()}
    print(f"{len(tones)} 音色 → {dst}  {counts}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
