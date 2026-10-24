---
title: synthmatch 楽譜にする
emoji: 🎹
colorFrom: purple
colorTo: pink
sdk: docker
app_port: 7860
pinned: false
short_description: ピアノの音声・動画から楽譜（PDF・MusicXML・MIDI）を作る
---

# synthmatch — ピアノの音から楽譜を作る

ピアノだけの音声・動画（mp3 / wav / mp4 / mov）をドロップすると、楽譜を自動で作ります。

- 楽譜を画面に表示し、PDF（印刷用）・MusicXML（MuseScore などで編集用）・MIDI でダウンロードできる
- 原曲と、楽譜どおりにピアノで鳴らした音を、同じ位置のまま切り替えて聴き比べられる（A/B 比較）
- 調・転調・拍子・テンポを自動で推定。区間ごとの調号、拍子、テンポ、リズムの細かさなどを変えて数秒で作り直せる

## 使うときの注意

- アップロードしたファイルと作った楽譜は、**アップロードしたブラウザからだけ**見られ、**24時間後に自動で削除**されます。
- ファイルは 100MB・10分まで。無料の CPU 環境で動いているので、1曲あたり数分かかり、混んでいるときは順番待ちになります。
- 作った楽譜は個人の練習用にお使いください（他の人が作った曲の楽譜の配布・販売はしないでください）。
- 自動の楽譜なので、指使いや音の長さの書き方などは人の書いた楽譜と違うことがあります。MusicXML を MuseScore で開いて仕上げるのがおすすめです。

ソースコード: https://github.com/specialsex00-hub/synthmatch

使っている主なもの: ピアノ採譜 [Kong et al. 2021 (ByteDance)](https://github.com/bytedance/piano_transcription)、[music21](https://web.mit.edu/music21/)、[Verovio](https://www.verovio.org/)、[FluidSynth](https://www.fluidsynth.org/) と FluidR3 SoundFont
