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
        category=a.category,
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
        category=a.category,
    )
    _print_report(report, Path(a.out))


def _cmd_devices(a):
    from .instruments.hardware import list_devices

    print(list_devices())


def _cmd_presets(a):
    from .instruments import load_instrument

    for p in load_instrument(a.instrument).presets():
        print(f"{p.id}\t{p.category}\t{p.name}")


def _cmd_sheet(a):
    from .sheet.pipeline import make_sheet, rebuild

    opts = dict(bpm=a.bpm, time_signature=a.time_signature, grid={8: 2, 16: 4}[a.grid], split=a.split, sensitivity=a.sensitivity)
    if a.rebuild:
        key = "auto" if a.key == "auto" else int(a.key) if a.key is not None else "keep"
        meta = rebuild(a.out, key=key, **opts)
    else:
        if not a.input:
            raise ValueError("入力ファイルを指定してください")
        key_sharps = int(a.key) if a.key not in (None, "auto") else None
        meta = make_sheet(a.input, a.out, title=a.title, backend=a.transcriber, key_sharps=key_sharps, **opts)
    out = Path(a.out)
    others = "、".join(c["key"] for c in meta["key_candidates"][1:4])
    for mod in meta.get("modulations", []):
        print(f"小節{mod['measure']}から転調: {mod['key']}（調号 {mod['sharps']:+d}）")
    c = meta["cleanup"]
    print(f"弾いていないと思われる音を {c['removed']} 個除き、{c['merged']} 個を和音にそろえました")
    print(f"\n{meta['key']}（ほかの候補: {others}）・{meta['time_signature']}・テンポ {meta['bpm']}・{meta['measures']}小節・{meta['notes']}音")
    print(f"PDF: {out / meta['files']['pdf']}  /  MusicXML: {out / meta['files']['musicxml']}  /  MIDI: {out / meta['files']['score_midi']}")


def _cmd_ui(a):
    from .ui.server import serve

    serve(a.root, host=a.host, port=a.port, open_browser=not a.no_browser, public=a.public, retention_hours=a.retention_hours)


def _print_report(report: dict, out: Path):
    print()
    for r in report["candidates"]:
        print(f"{r['rank']}. {r['name']}  [{r['category']}]  score={r['score']} ({r['stage']})")
        for h in r["hints"]:
            print(f"     - {h}")
    print(f"\nレポート: {out / 'report.html'}（ブラウザで開く） / {out / 'report.md'}")


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
        sp.add_argument("--category", help="このカテゴリ名を含む音色の中だけから探す（例: Bell）")

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

    sp = sub.add_parser("sheet", help="ピアノの音声（mp3/wav/mp4/動画）から楽譜を作る")
    sp.add_argument("input", nargs="?", help="ピアノの音声ファイル")
    sp.add_argument("-o", "--out", default="out/sheet")
    sp.add_argument("--title", help="楽譜のタイトル（省略時はファイル名）")
    sp.add_argument("--bpm", type=float, help="テンポを指定する（省略時は自動で推定）")
    sp.add_argument("--time-signature", default="4/4", choices=["4/4", "3/4", "2/4", "6/8"], help="拍子")
    sp.add_argument("--grid", type=int, default=16, choices=[8, 16], help="リズムを何分音符単位でそろえるか")
    sp.add_argument("--split", type=int, default=60, help="右手と左手を分ける音（MIDI番号。60 = 真ん中のド）")
    sp.add_argument(
        "--key", choices=[str(i) for i in range(-6, 7)] + ["auto"], metavar="-6〜6|auto",
        help="調号（♯の数は正、♭の数は負。例: -5 = ♭5つ）。曲全体をこの調号で書く。auto = 自動（転調も検出）。"
        "--rebuild で省略すると前回の指定のまま",
    )
    sp.add_argument("--transcriber", default="piano", choices=["piano", "basic"], help="piano = ピアノ専用の高精度採譜")
    sp.add_argument(
        "--sensitivity", default="normal", choices=["off", "low", "normal", "high"],
        help="音を拾う量。low = 弱い音を多めに除く / high = 弱い音もなるべく残す / off = 除かない",
    )
    sp.add_argument("--rebuild", action="store_true", help="採譜はやり直さず、-o のフォルダの結果から設定だけ変えて作り直す")
    sp.set_defaults(func=_cmd_sheet)

    sp = sub.add_parser("ui", help="ブラウザで使う画面を起動する")
    sp.add_argument("--root", default=".", help="instruments/ があるフォルダ（録音データもここに保存）")
    sp.add_argument("--host", default="127.0.0.1", help="公開するときは 0.0.0.0")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--public", action="store_true", help="公開モード（楽譜にするだけ・ブラウザごとに分ける・順番待ち・自動削除）")
    sp.add_argument("--retention-hours", type=float, default=24, help="公開モードで楽譜を残しておく時間")
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
