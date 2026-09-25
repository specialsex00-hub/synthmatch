"""コマンドライン: synthmatch <サブコマンド> ..."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__


def _cmd_run(a):
    from .pipeline import run

    report = run(
        Path(a.song), Path(a.instrument), Path(a.out),
        separator=a.separator, transcriber=a.transcriber, midi=Path(a.midi) if a.midi else None,
        library_dir=Path(a.library) if a.library else None, top=a.top, rerank=a.rerank, clip=a.clip,
    )
    _print_report(report, Path(a.out))


def _cmd_separate(a):
    from .separate import separate

    print(separate(a.song, a.out, backend=a.separator))


def _cmd_transcribe(a):
    from .notes import write_midi
    from .transcribe import transcribe

    notes = transcribe(a.audio, backend=a.transcriber)
    write_midi(notes, a.out)
    print(f"{len(notes)} ノート → {a.out}")


def _cmd_build(a):
    from .instruments import load_instrument
    from .library import build_library
    from .pipeline import default_library_dir

    inst = load_instrument(a.instrument)
    out = Path(a.library) if a.library else default_library_dir(inst)
    print(f"{inst.name} の音色ライブラリを {out} に作成します（中断しても続きから再開できます）")

    labels = {"done": "", "skipped": "(済) ", "silent": "(無音のためスキップ) "}

    def progress(i, n, preset, status):
        print(f"  [{i}/{n}] {labels[status]}{preset.name}")

    lib = build_library(inst, out, category=a.category, limit=a.limit, progress=progress)
    print(f"完了: {len(lib.entries)} 音色")


def _cmd_match(a):
    from .notes import read_midi
    from .pipeline import match_audio
    from .transcribe import transcribe

    notes = read_midi(a.midi) if a.midi else transcribe(a.audio, backend=a.transcriber)
    report = match_audio(
        Path(a.audio), Path(a.instrument), Path(a.out), notes,
        library_dir=Path(a.library) if a.library else None, top=a.top, rerank=a.rerank, clip=a.clip,
    )
    _print_report(report, Path(a.out))


def _cmd_devices(a):
    from .instruments.hardware import list_devices

    print(list_devices())


def _cmd_presets(a):
    from .instruments import load_instrument

    for p in load_instrument(a.instrument).presets():
        print(f"{p.id}\t{p.category}\t{p.name}")


def _cmd_ui(a):
    from .ui.server import serve

    serve(a.root, port=a.port, open_browser=not a.no_browser)


def _print_report(report: dict, out: Path):
    print()
    for r in report["candidates"]:
        print(f"{r['rank']}. {r['name']}  [{r['category']}]  score={r['score']} ({r['stage']})")
        for h in r["hints"]:
            print(f"     - {h}")
    print(f"\nレポート: {out / 'report.md'}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="synthmatch", description="楽曲のキーボードパートに近い手持ちシンセの音色を探す")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def match_opts(sp):
        sp.add_argument("-i", "--instrument", required=True, help="楽器設定（instruments/*.toml）")
        sp.add_argument("--library", help="音色ライブラリのフォルダ（省略時 libraries/<楽器名>）")
        sp.add_argument("--top", type=int, default=5, help="表示する候補数")
        sp.add_argument("--rerank", type=int, default=3, help="実際に鳴らして比べ直す上位の数（0で無効）")
        sp.add_argument("--clip", type=float, default=30.0, help="先頭何秒で比べるか（0で全体）")
        sp.add_argument("--midi", help="採譜の代わりに使う MIDI ファイル")
        sp.add_argument("--transcriber", default="auto", help="auto / basic-pitch / pyin")

    sp = sub.add_parser("run", help="楽曲から一気に：分離 → 採譜 → 照合")
    sp.add_argument("song")
    sp.add_argument("-o", "--out", default="out")
    sp.add_argument("--separator", default="demucs", help="demucs / none")
    match_opts(sp)
    sp.set_defaults(func=_cmd_run)

    sp = sub.add_parser("separate", help="キーボードパートだけを取り出す")
    sp.add_argument("song")
    sp.add_argument("-o", "--out", default="keys.wav")
    sp.add_argument("--separator", default="demucs")
    sp.set_defaults(func=_cmd_separate)

    sp = sub.add_parser("transcribe", help="音声から MIDI を作る")
    sp.add_argument("audio")
    sp.add_argument("-o", "--out", default="notes.mid")
    sp.add_argument("--transcriber", default="auto")
    sp.set_defaults(func=_cmd_transcribe)

    sp = sub.add_parser("build-library", help="楽器の全音色を鳴らして特徴量ライブラリを作る")
    sp.add_argument("-i", "--instrument", required=True)
    sp.add_argument("--library")
    sp.add_argument("--category", help="カテゴリ名を含む音色だけ（部分一致。例: \"SN-S\", \"Synth Lead\"）")
    sp.add_argument("--limit", type=int, help="先頭 N 音色だけ（お試し用）")
    sp.set_defaults(func=_cmd_build)

    sp = sub.add_parser("match", help="キーボードだけの音声から音色を探す")
    sp.add_argument("audio")
    sp.add_argument("-o", "--out", default="out")
    match_opts(sp)
    sp.set_defaults(func=_cmd_match)

    sp = sub.add_parser("devices", help="MIDI ポートとオーディオ入力の一覧")
    sp.set_defaults(func=_cmd_devices)

    sp = sub.add_parser("presets", help="楽器設定から読み込んだ音色一覧")
    sp.add_argument("-i", "--instrument", required=True)
    sp.set_defaults(func=_cmd_presets)

    sp = sub.add_parser("ui", help="ブラウザで使う画面を起動する")
    sp.add_argument("--root", default=".", help="instruments/ があるフォルダ（録音データもここに保存）")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    sp.set_defaults(func=_cmd_ui)

    a = p.parse_args(argv)
    if getattr(a, "clip", None) == 0:
        a.clip = None
    try:
        a.func(a)
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
