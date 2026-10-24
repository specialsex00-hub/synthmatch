#!/bin/sh
# 「楽譜にする」公開版をこの Mac で動かし、Cloudflare Tunnel で誰でも開ける URL を作る。
#
#     brew install cloudflared     # 最初に1回
#     sh scripts/share_public.sh   # 止めるときは Ctrl+C
#
# URL（https://〜.trycloudflare.com）は起動するたびに変わる。Mac がスリープすると開けなくなる。
# データは public-data/ に保存され、24時間で自動削除される。
set -eu
cd "$(dirname "$0")/.."
PORT="${PORT:-8780}"

.venv/bin/synthmatch ui --public --host 127.0.0.1 --port "$PORT" --no-browser --root public-data &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT INT TERM

# スリープさせない（caffeinate は cloudflared が終わるまで有効）。
# 学校などの UDP が通らないネットワークでもつながるよう、QUIC ではなく HTTP/2 を使う
caffeinate -i cloudflared tunnel --no-autoupdate --protocol http2 --url "http://127.0.0.1:$PORT"
