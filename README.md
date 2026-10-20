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

## ピアノの音から楽譜を作る

ピアノだけの音声（mp3 / wav / mp4 / 動画）から、楽譜（PDF・MusicXML・MIDI）を作る。

```sh
pip install -e ".[sheet]"     # torch などを含むので重い
brew install ffmpeg fluid-synth   # 動画の読み込み / ピアノの音で鳴らす（初回に SoundFont 約24MB を自動取得）
synthmatch sheet piano.mp4 -o out/sheet --title "曲名"
synthmatch sheet -o out/sheet --rebuild --time-signature 3/4 --bpm 92   # 採譜はそのままで設定だけ変えて作り直す
synthmatch sheet -o out/sheet --rebuild --key -5   # 調号を指定（♯は正・♭は負。-5 = ♭5つ）
```

1. ffmpeg で音声を取り出す（動画もそのまま渡せる）
2. ピアノ専用の採譜モデル（ByteDance, Kong et al. 2021）で音を拾う（初回のみモデル約170MBをダウンロード）
3. 拍とテンポを推定し、弾いていないと思われる音（弱い誤検出・押さえたままの音の再検出・極端に短い音）を除き、
   少しずれて弾いた音を1つの和音にそろえてから、16分（または8分）音符の格子にそろえる
   （除く量は `--sensitivity low / normal / high / off` で調整）。3連符で弾いている拍は 1/3 拍の格子にそろえる
   （テンポの揺れを許して、等間隔に並んでいるかで判定）
4. 調を推定し（嬰ハ長調／変ニ長調のように書き方が2通りある調は♯・♭の少ない方）、右手（ト音記号）と左手（ヘ音記号）に分けて MusicXML にする → Verovio で描画、PDF 化
5. 楽譜には「聞こえている長さ」で書く：ペダルで響いている音は伸ばし、録音の最後まで鳴っていた音は小節の終わりまで伸ばす。
   休符は拍の区切りで分けて書く（複付点の休符を作らない）
6. 採譜結果（ペダルつき）と楽譜どおりの演奏を、FluidSynth でピアノの音にする

| 出力 | 中身 |
|---|---|
| `score.pdf` | 印刷用の楽譜 |
| `score.musicxml` | MuseScore などで開いて直せる楽譜データ |
| `score.mid` / `transcription.mid` | 楽譜どおりの MIDI / 演奏そのままの MIDI |
| `preview.wav` | 採譜結果を演奏そのまま（ペダルつき）ピアノの音で鳴らしたもの |
| `score.wav` | 楽譜どおりにピアノの音で鳴らしたもの（先頭を原曲にそろえてある） |

自動の楽譜は「どちらの手で弾くか」「音の長さの書き方」などが人の書いた楽譜とは違うことがある。仕上げは MuseScore で直す前提。

## 画面（UI）で使う

```sh
synthmatch ui        # ブラウザで http://127.0.0.1:8765/ が開く
```

| タブ | できること |
|---|---|
| 録音 | 機器の接続チェック、テスト録音（音量の確認つき）、音色ライブラリの録音（カテゴリ指定・音色名で1つだけ・進み具合・残り時間・中止） |
| ライブラリ | 音色の検索・試聴。音色をクリックすると、その音色の分析（明るさ・アタック・サステイン・余韻・ノイズ感と、ライブラリ内での位置）を表示 |
| 曲から探す | 曲（と任意で MIDI）をドロップ → 候補・調整案・原曲とのA/B比較。「探す範囲」で Bell だけ、などに絞れる |
| 楽譜にする | ピアノの音声をドロップ → 楽譜の表示・PDF/MusicXML/MIDI・原曲と採譜のA/B比較・ピアノロール。拍子やテンポを変えて数秒で作り直せる |

音色はカテゴリ単位ではなく、1音色ずつ録音・分析・照合する。
照合結果は `report.html`（試聴・A/B比較・特徴の比較表つき。フォルダごと渡せば他の人も見られる）と `report.md` に出力される。

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

`out/report.html` に Soft Pad が1位として出て、「カットオフを下げる」「リリースを短く」という調整案が付く。

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
| `--category Bell` | カテゴリ名に Bell を含む音色の中だけから探す |

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
  sheet/          ピアノの音声 → 楽譜（採譜・幽霊の音の除去・拍の推定・量子化・music21・Verovio・FluidSynth）
  ui/             Web UI（FastAPI + 素の HTML/JS）
```

## 今後の課題

- シンセに特化した分離モデル（現状は Demucs の piano + other）
- 採譜の精度（和音は basic-pitch 推奨。pyin は単音のみ）
- ヒントを増やす（レゾナンス、デチューン・コーラス、LFO など）
- パラメータの自動最適化（ソフトシンセで、近い音色を出発点にパラメータを探索する）
