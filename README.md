# synthmatch

バンドカバーのためのシンセ音作りサポートツール。

1. 楽曲からキーボードパートだけを取り出す（音源分離）
2. 取り出した音から MIDI を作る（採譜）
3. 手持ちのシンセの全音色と比べ、近い音色の候補と「カットオフを下げる」「リリースを長く」などの調整案を出す

```
楽曲 ──分離──▶ keys.wav ──採譜──▶ notes.mid
                  │                    │
                  └──── 照合 ◀─────────┘
                         │  ① 音色ライブラリ（全音色で共通フレーズを鳴らした特徴量）と比べて候補を絞る
                         │  ② 上位の音色で同じ MIDI を実際に鳴らし、時間をそろえて比べ直す
                         ▼
                   report.md（候補・調整案・試聴用 wav）
```

## セットアップ

Python 3.11 以上が必要。

```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[ui,dev]"         # 画面つき・最小構成（デモシンセで動作確認できる）
pip install -e ".[hardware]"       # ハードウェアシンセを使う場合
pip install -e ".[separate]"       # 音源分離（Demucs, torch を含むので重い）
pip install -e ".[transcribe]"     # 和音の採譜（basic-pitch）
brew install ffmpeg                # mp3 などを読む場合
```

## 画面（UI）で使う

```sh
synthmatch ui        # ブラウザで http://127.0.0.1:8765/ が開く
```

| タブ | できること |
|---|---|
| ① 録音 | 機器の接続チェック、テスト録音（音量の確認つき）、音色ライブラリの録音（カテゴリ指定・進み具合・残り時間・中止） |
| ② 音色ライブラリ | 音色の検索、録音した音の試聴、1音色だけ録り直す |
| ③ 曲から探す | 曲（と任意で MIDI）をアップロード → 候補・調整案・試聴、過去の結果 |

録音データは `libraries/`、照合結果は `out/ui/` に保存される。

## まず動かしてみる（実機なし）

内蔵のデモシンセ（12音色）で、全体の流れを確認できる。

```sh
# デモシンセの音色ライブラリを作る
synthmatch build-library -i instruments/demo.toml

# 「Soft Pad のカットオフとリリースを変えた音」を目標として作る
python scripts/make_demo_song.py --base "Soft Pad" --cutoff 700 --release 0.5

# 照合（分離なし・MIDIあり）
synthmatch run demo_keys.wav -i instruments/demo.toml --separator none --midi demo_keys.mid
```

`out/report.md` に Soft Pad が1位として出て、「カットオフを下げる」「リリースを短く」という調整案が付く。

## 実際の曲で使う

```sh
synthmatch run song.mp3 -i instruments/fa06.toml -o out/song
```

| オプション | 意味 |
|---|---|
| `--midi file.mid` | 採譜の代わりに MIDI を使う（バンドスコアから打ち込んだものなど。精度が一番上がる） |
| `--clip 30` | 先頭何秒で比べるか（0 で全体）。キーボードが目立つ区間を切り出した wav を `match` に渡すのもおすすめ |
| `--rerank 3` | 上位何音色を実際に鳴らして比べ直すか。ハードでは1音色ごとに曲の長さ分の録音時間がかかる |
| `--separator none` | 分離をしない（すでにキーボードだけの音源がある場合） |

分離だけ・採譜だけ・照合だけも実行できる: `synthmatch separate` / `transcribe` / `match`

## Roland FA-06 の準備

音色一覧（[instruments/fa06_presets.csv](instruments/fa06_presets.csv)）は、公式サウンド・リストから作成済み
（SuperNATURAL Acoustic 100 / SuperNATURAL Synth 1115 / PCM Synth 897、計 2112 音色。ドラムと GM2 は除外）。
作り直すときは `scripts/parse_fa_soundlist.py` を使う。

1. FA 本体の設定（詳しくは [instruments/fa06.toml](instruments/fa06.toml) のコメント）
   - `SYSTEM > General > USB Driver` を **VENDOR** にして Write → 電源を入れ直す（GENERIC だと MIDI しか通らない）
   - Mac に Roland の FA 用ドライバーを入れる（入らない場合は MAIN OUT をオーディオインターフェースで録る）
   - `USB Audio Output Select` = MAIN、鳴らすパートの Rx Channel = 1
2. `pip install -e ".[hardware]"` → `synthmatch devices` でポート名とデバイス名を確認し、必要なら `fa06.toml` を直す
3. 少しだけ試す: `synthmatch build-library -i instruments/fa06.toml --limit 5`
   `libraries/roland_fa-06/renders/` の wav を聴いて、正しい音色で録れているか確認する
4. 全音色の録音は約 14 秒 × 2112 ≒ 8 時間かかるので、カテゴリごとに分けるのがおすすめ（中断しても同じコマンドで続きから再開できる）
   ```sh
   synthmatch build-library -i instruments/fa06.toml --category "Synth Lead"   # 307 音色 ≒ 70 分
   synthmatch build-library -i instruments/fa06.toml --category "Synth Pad"    # 290 音色
   synthmatch build-library -i instruments/fa06.toml --category "SN-S"         # SuperNATURAL Synth 全部
   ```
   照合は、その時点でライブラリにある音色の中から探す。

## 他の楽器を追加する

- **ハードのシンセ**: `fa06.toml` と CSV をコピーして書き換えるだけ
- **ソフトシンセ（VST3）**: `type = "vst"` で `plugin` と `presets_dir`（.vstpreset のフォルダ）を指定する（実験的）
- **新しい種類**: `src/synthmatch/instruments/base.py` の `Instrument` を継承し、`presets()` と `render()` を実装して `instruments/__init__.py` に登録する

## 構成

```
src/synthmatch/
  separate.py     音源分離（demucs / none）
  transcribe.py   採譜（basic-pitch / pyin）
  features.py     音色の特徴量（スペクトル形状・明るさ・エンベロープ など）
  library.py      音色ライブラリの作成・読み込み・距離計算
  matcher.py      2段階の照合
  hints.py        特徴量の差から調整案を作る
  pipeline.py     全体の流れとレポート出力
  instruments/    楽器（demo / hardware / vst）
  ui/             Web UI（FastAPI + 素の HTML/JS）
```

## 今後の課題

- シンセに特化した分離モデル（現状は Demucs の piano + other）
- 採譜の精度（和音は basic-pitch 推奨。pyin は単音のみ）
- ヒントを増やす（レゾナンス、デチューン・コーラス、LFO など）
- パラメータの自動最適化（ソフトシンセで、近い音色を出発点にパラメータを探索する）
