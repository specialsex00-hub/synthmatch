"""照合結果を、ブラウザで見やすい1枚の HTML（report.html）にする。

外部ファイルに依存しない（CSS・JS を埋め込み）。音声は report.html からの相対パスで参照するので、
出力フォルダごと渡せば他の人のパソコンでも試聴できる。
"""

from __future__ import annotations

import html
import re

PROFILE_ROWS = [
    # key, 見出し, 単位の付け方, 説明
    ("brightness", "明るさ", lambda v: f"{v:.2f} oct", "基音から何オクターブ上に音の重心があるか。大きいほど明るい（フィルターが開いている）"),
    ("attack_ms", "アタック", lambda v: f"{v:.0f} ms", "音の立ち上がりにかかる時間"),
    ("sustain_db", "サステイン", lambda v: f"{v:.1f} dB", "押さえている間の音量の下がり方。0 に近いほど伸びる"),
    ("release_s", "余韻", lambda v: f"{v:.2f} s", "鍵盤を離してからの余韻（リリース＋リバーブ）"),
    ("noisiness", "ノイズ感", lambda v: f"{v:.2f}", "ノイズっぽさ。大きいほどノイズ寄り"),
]

ICONS = {
    "wave": '<path d="M2 12h3l2-7 3 14 3-10 2 5 2-2h5"/>',
    "verb": '<path d="M3 12h2M8 8v8M12 5v14M16 8v8M20 11v2"/>',
    "env": '<path d="M2 20 7 4l4 8h6l5 8"/>',
    "filter": '<path d="M2 18c4 0 5-12 9-12s4 6 11 6"/>',
    "keys": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M8 5v8M12 5v8M16 5v8"/>',
    "noise": '<path d="M2 12l2-5 2 9 2-7 2 6 2-8 2 10 2-6 2 4 2-5 2 2"/>',
    "check": '<path d="m5 12 5 5 9-10"/>',
}


def _split(cat: str) -> tuple[str, str]:
    return tuple(cat.split(":", 1)) if ":" in cat else ("", cat)  # type: ignore[return-value]


def _icon_for(label: str) -> str:
    c = label.lower()
    if re.search(r"pad|string|choir|orch", c):
        return "verb"
    if "bass" in c:
        return "env"
    if re.search(r"brass|sax|flute|wind|reed|harmonica", c):
        return "filter"
    if re.search(r"piano|organ|clav|harpsi|keys|polykey", c):
        return "keys"
    if re.search(r"fx|puls|hit|noise|beat|drum|perc|seq", c):
        return "noise"
    return "wave"


def _hue(label: str) -> int:
    # UI（app.js の hue()）と同じ計算にして、同じ音色は同じ色にする
    h = 0
    for ch in label.lower():
        h = (h * 31 + ord(ch)) % 360
    return h


def _svg(name: str) -> str:
    return f'<svg viewBox="0 0 24 24" aria-hidden="true">{ICONS[name]}</svg>'


def _art(category: str, cls: str = "") -> str:
    label = _split(category)[1] or "?"
    return f'<div class="art {cls}" style="--h:{_hue(label)}">{_svg(_icon_for(label))}</div>'


def _hint_icon(h: str) -> str:
    if re.search(r"カットオフ|cutoff|フィルター", h, re.I):
        return "filter"
    if re.search(r"リバーブ|reverb|余韻|残響", h, re.I):
        return "verb"
    if re.search(r"ノイズ|noise", h, re.I):
        return "noise"
    return "env"


def _hints(hints: list[str]) -> str:
    if not hints:
        return f'<li class="none">{_svg("check")}<span>大きな違いは見つかりませんでした</span></li>'
    return "".join(f"<li>{_svg(_hint_icon(h))}<span>{html.escape(h)}</span></li>" for h in hints)


def _fmt(key: str, v) -> str:
    if v is None:
        return "–"
    return next(f(v) for k, _, f, _ in PROFILE_ROWS if k == key)


def _profile_table(report: dict) -> str:
    target = report.get("target_profile") or {}
    cands = report["candidates"]
    if not target or not cands:
        return ""
    head = "".join(f'<th><span class="rank">{c["rank"]}</span>{html.escape(c["name"])}</th>' for c in cands)
    rows = []
    for key, label, _, desc in PROFILE_ROWS:
        tv = target.get(key)
        diffs = [abs((c.get("profile") or {}).get(key) - tv) if tv is not None and (c.get("profile") or {}).get(key) is not None else None for c in cands]
        valid = [d for d in diffs if d is not None]
        best = min(valid) if valid else None
        cells = "".join(
            f'<td class="{"closest" if d is not None and d == best else ""}">{_fmt(key, (c.get("profile") or {}).get(key))}</td>'
            for c, d in zip(cands, diffs)
        )
        rows.append(f'<tr><th scope="row" title="{html.escape(desc)}">{label}</th><td class="target">{_fmt(key, tv)}</td>{cells}</tr>')
    return f"""
    <section class="card">
      <h2>音の特徴の比較</h2>
      <p class="muted small">取り出した音（目標）と各候補を、同じ物差しで測った値です。各行で目標にいちばん近い値に色が付いています。</p>
      <div class="table-wrap"><table class="profile">
        <thead><tr><th></th><th class="target">目標</th>{head}</tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table></div>
      <dl class="legend">{"".join(f"<dt>{label}</dt><dd>{html.escape(desc)}</dd>" for _, label, _, desc in PROFILE_ROWS)}</dl>
    </section>"""


def _player(src: str | None, target: str | None, title: str) -> str:
    if not src:
        return ""
    ab = (
        f'<div class="ab" role="group" aria-label="聴き比べ"><button data-src="{html.escape(target)}">A 原曲</button>'
        f'<button data-src="{html.escape(src)}" aria-pressed="true">B この音色</button></div>'
        if target
        else ""
    )
    return f'<div class="player" data-title="{html.escape(title)}">{ab}<audio controls preload="none" src="{html.escape(src)}"></audio></div>'


def render_html(report: dict, target_audio: str | None) -> str:
    cands = report["candidates"]
    best, rest = (cands[0], cands[1:]) if cands else (None, [])
    created = report.get("created", "").replace("T", " ")[:16]
    scope = f"カテゴリ「{html.escape(report['category'])}」の中から" if report.get("category") else "録音済みの全音色から"

    hero = ""
    if best:
        stage = "実際に鳴らして比較" if best["stage"] == "rerank" else "ライブラリで比較"
        hero = f"""
    <section class="hero">
      {_art(best["category"], "xl")}
      <div class="hero-body">
        <div class="eyebrow">いちばん近い音色</div>
        <h1>{html.escape(best["name"])}</h1>
        <div class="meta">{html.escape(best["category"])} ・ スコア {best["score"]}（{stage}）</div>
        {_player(best.get("audio"), target_audio, best["name"])}
        <ul class="hints">{_hints(best["hints"])}</ul>
      </div>
    </section>"""

    others = ""
    if rest:
        items = []
        for c in rest:
            stage = f"スコア {c['score']}（実際に鳴らして比較）" if c["stage"] == "rerank" else f"ライブラリで比較（スコア {c['score']}・参考値）"
            items.append(f"""
        <article class="cand">
          <div class="rank-num">{c["rank"]}</div>
          {_art(c["category"])}
          <div class="cand-body">
            <h3>{html.escape(c["name"])}</h3>
            <div class="meta">{html.escape(c["category"])} ・ {stage}</div>
            {_player(c.get("audio"), target_audio, c["name"])}
            <ul class="hints small">{_hints(c["hints"])}</ul>
          </div>
        </article>""")
        others = f'<section><h2 class="section-title">ほかの候補</h2><p class="muted small">上から近い順。スコアは小さいほど近い。</p>{"".join(items)}</section>'

    target_block = (
        f'<div class="target-player"><div><div class="eyebrow">取り出したキーボードの音（目標）</div>'
        f'<audio controls preload="none" src="{html.escape(target_audio)}"></audio></div></div>'
        if target_audio
        else ""
    )

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>音色レポート - {html.escape(best["name"] if best else report["instrument"])}</title>
<style>{CSS}</style>
</head>
<body>
<main>
  <header class="top">
    <div class="brand"><span class="logo">{_svg("wave")}</span>synthmatch <span class="muted">音色レポート</span></div>
    <div class="facts">
      <span><b>楽器</b>{html.escape(report["instrument"])}</span>
      <span><b>範囲</b>{scope}</span>
      {f'<span><b>作成</b>{html.escape(created)}</span>' if created else ""}
    </div>
  </header>
  {target_block}
  {hero}
  {_profile_table(report)}
  {others}
  <footer class="muted small">
    「A 原曲 / B この音色」で、同じ再生位置のまま切り替えて聴き比べられます。
    調整案は、目標の音と候補の音を同じ物差しで測ったときの差から出した目安です。最後は耳で確かめてください。
  </footer>
</main>
<script>{JS}</script>
</body>
</html>
"""


CSS = """
:root{--bg:#0e0f13;--surface:#1b1d25;--surface-2:#232633;--line:#2c2f3d;--text:#f3f4f8;--text-2:#a9adbd;--text-3:#6f7488;
--accent:#8b6cff;--accent-2:#ff6ba8;--ok:#3ddc97;--grad:linear-gradient(135deg,var(--accent),var(--accent-2));color-scheme:dark}
@media (prefers-color-scheme:light){:root{--bg:#f4f4f8;--surface:#fff;--surface-2:#f3f3f8;--line:#e2e3eb;--text:#14151b;--text-2:#555a6e;--text-3:#8b90a3;
--accent:#6a4dff;--accent-2:#f0478f;--ok:#13a86b;color-scheme:light}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.65 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif;-webkit-font-smoothing:antialiased}
main{max-width:980px;margin:0 auto;padding:32px 24px 56px;display:flex;flex-direction:column;gap:20px}
svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;flex:none}
.muted{color:var(--text-2)}.small{font-size:13px}
.top{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px}
.brand{display:flex;align-items:center;gap:10px;font-weight:800;font-size:17px}
.brand .muted{font-weight:600}
.logo{width:32px;height:32px;border-radius:9px;background:var(--grad);display:grid;place-items:center;color:#fff}
.logo svg{width:18px;height:18px}
.facts{display:flex;flex-wrap:wrap;gap:8px}
.facts span{background:var(--surface);border:1px solid var(--line);border-radius:999px;padding:4px 12px;font-size:13px}
.facts b{color:var(--text-3);font-weight:600;margin-right:6px}
.eyebrow{font-size:12px;font-weight:700;letter-spacing:.06em;color:var(--text-3)}
.target-player{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:14px 18px}
audio{width:100%;height:36px;margin-top:6px}
.art{--h:260;width:52px;height:52px;border-radius:11px;flex:none;display:grid;place-items:center;color:rgba(255,255,255,.92);
background:radial-gradient(120% 90% at 100% 0%,hsl(calc(var(--h) + 50) 90% 65%/.9),transparent 60%),linear-gradient(145deg,hsl(var(--h) 75% 58%),hsl(calc(var(--h) + 30) 70% 28%))}
.art svg{width:45%;height:45%}
.art.xl{width:200px;height:200px;border-radius:20px;box-shadow:0 16px 40px rgba(0,0,0,.35)}
.art.xl svg{width:38%;height:38%}
.hero{display:grid;grid-template-columns:auto minmax(0,1fr);gap:28px;align-items:start;padding:28px;border-radius:24px;border:1px solid var(--line);
background:linear-gradient(135deg,color-mix(in srgb,var(--accent) 30%,var(--surface)),color-mix(in srgb,var(--accent-2) 14%,var(--surface)))}
.hero h1{font-size:42px;font-weight:900;letter-spacing:-.04em;line-height:1.1;margin:4px 0;overflow-wrap:anywhere}
.meta{color:var(--text-2);font-size:14px}
.player{margin-top:14px}
.ab{display:inline-flex;background:var(--surface-2);border-radius:999px;padding:3px}
.ab button{border:0;background:none;color:var(--text-2);font:inherit;font-size:13px;font-weight:700;padding:5px 14px;border-radius:999px;cursor:pointer}
.ab button[aria-pressed=true]{background:var(--accent);color:#fff}
.hints{list-style:none;margin:16px 0 0;padding:0;display:flex;flex-direction:column;gap:8px}
.hints li{display:flex;gap:12px;align-items:flex-start;background:color-mix(in srgb,var(--surface) 72%,transparent);padding:10px 12px;border-radius:12px;font-size:14px}
.hints.small li{padding:6px 10px;font-size:13px;background:var(--surface-2)}
.hints svg{width:18px;height:18px;color:var(--accent);margin-top:2px}
.hints li.none{color:var(--text-2)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:22px}
.card h2,.section-title{margin:0;font-size:20px;font-weight:800;letter-spacing:-.02em}
.section-title{margin-top:8px}
.table-wrap{overflow-x:auto;margin-top:12px}
table.profile{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}
.profile th,.profile td{padding:9px 12px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
.profile thead th{font-size:13px;color:var(--text-2);font-weight:600;vertical-align:bottom}
.profile tbody th{text-align:left;font-weight:600;cursor:help}
.profile .target{background:color-mix(in srgb,var(--accent) 14%,transparent);font-weight:700}
.profile td.closest{color:var(--ok);font-weight:700}
.rank{display:inline-grid;place-items:center;width:18px;height:18px;border-radius:50%;background:var(--surface-2);font-size:11px;margin-right:6px;color:var(--text)}
.legend{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;margin:14px 0 0;font-size:12px;color:var(--text-2)}
.legend dt{font-weight:700;color:var(--text)}.legend dd{margin:0}
.cand{display:grid;grid-template-columns:24px auto minmax(0,1fr);gap:14px;padding:16px;border:1px solid var(--line);border-radius:16px;background:var(--surface);margin-top:12px}
.rank-num{font-weight:800;color:var(--text-3);text-align:center;padding-top:12px}
.cand h3{margin:0;font-size:17px}
footer{border-top:1px solid var(--line);padding-top:16px}
@media (max-width:640px){main{padding:20px 16px 40px}.hero{grid-template-columns:1fr;padding:20px}.art.xl{width:120px;height:120px}.hero h1{font-size:30px}
.cand{grid-template-columns:auto minmax(0,1fr)}.cand .rank-num{display:none}}
@media print{body{background:#fff;color:#000}.player,.target-player{display:none}.hero,.card,.cand{break-inside:avoid;border-color:#ccc}}
"""

JS = """
// A/B：同じ再生位置のまま、原曲と候補の音を切り替える。1つ再生すると他は止める。
document.querySelectorAll('.player').forEach(function (p) {
  var audio = p.querySelector('audio');
  p.querySelectorAll('.ab button').forEach(function (b) {
    b.addEventListener('click', function () {
      if (b.getAttribute('aria-pressed') === 'true') return;
      var t = audio.currentTime, playing = !audio.paused;
      audio.src = b.dataset.src;
      audio.addEventListener('loadedmetadata', function () {
        audio.currentTime = Math.min(t, audio.duration || 0);
        if (playing) audio.play();
      }, { once: true });
      audio.load();
      p.querySelectorAll('.ab button').forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); });
    });
  });
});
document.querySelectorAll('audio').forEach(function (a) {
  a.addEventListener('play', function () {
    document.querySelectorAll('audio').forEach(function (o) { if (o !== a) o.pause(); });
  });
});
"""
