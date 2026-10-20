"""MusicXML を Verovio で SVG（ページごと）に描き、PyMuPDF で PDF にまとめる。"""

from __future__ import annotations

import re
from pathlib import Path


def _flatten_for_pdf(svg: str) -> str:
    """Verovio の入れ子 <svg viewBox> を transform に置き換える。

    PyMuPDF は入れ子の svg の viewBox による拡大縮小を無視するため、そのままだと楽譜がページの外に描かれて真っ白になる。
    また <style> の CSS（線の色を currentColor にする指定）も読まないので、五線や符尾が消えないよう
    各図形に直接 stroke を書き込む。
    """
    svg = svg.replace("currentColor", "#000")
    svg = re.sub(r"<(path|rect|polygon|polyline|ellipse)(?![^>]*\sstroke=)", r'<\1 stroke="#000"', svg)
    outer_w = float(re.search(r'<svg[^>]*\swidth="([\d.]+)', svg).group(1))
    m = re.search(r'<svg([^>]*)viewBox="0 0 ([\d.]+) ([\d.]+)"([^>]*)>', svg[svg.index(">") + 1 :])
    if not m:
        return svg
    start = svg.index(">") + 1 + m.start()
    end = start + (m.end() - m.start())
    scale = outer_w / float(m.group(2))
    attrs = (m.group(1) + m.group(4)).strip()
    svg = svg[:start] + f'<g {attrs} transform="scale({scale})">' + svg[end:]
    close = svg.rfind("</svg>", 0, svg.rfind("</svg>"))
    return svg[:close] + "</g>" + svg[close + len("</svg>") :]


def render(musicxml: Path, out_dir: Path, scale: int = 40) -> tuple[list[Path], Path]:
    """SVG のページ一覧と PDF のパスを返す。用紙は A4 縦。"""
    import pymupdf
    import verovio

    # 別スレッド（UI のジョブ）で作ると、フォントの場所がビルド時のパスになって読み込めないため明示する
    tk = verovio.toolkit(False)
    tk.setResourcePath(str(Path(verovio.__file__).parent / "data"))
    tk.setOptions({
        "pageWidth": 2100,  # A4 (210mm) を 1/10 mm 単位で
        "pageHeight": 2970,
        "pageMarginTop": 100,
        "pageMarginBottom": 100,
        "pageMarginLeft": 100,
        "pageMarginRight": 100,
        "scale": scale,
        "adjustPageHeight": False,
        "breaks": "auto",
        "footer": "none",
        "header": "auto",
    })
    if not tk.loadData(Path(musicxml).read_text(encoding="utf-8")):
        raise RuntimeError("楽譜データ（MusicXML）を読み込めませんでした")

    pages_dir = out_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    for old in pages_dir.glob("page-*.svg"):
        old.unlink()
    pages = []
    pdf = pymupdf.open()
    for i in range(1, tk.getPageCount() + 1):
        svg = tk.renderToSVG(i)
        path = pages_dir / f"page-{i}.svg"
        path.write_text(svg, encoding="utf-8")
        pages.append(path)
        with pymupdf.open(stream=_flatten_for_pdf(svg).encode("utf-8"), filetype="svg") as doc:
            pdf.insert_pdf(pymupdf.open("pdf", doc.convert_to_pdf()))
    pdf_path = out_dir / "score.pdf"
    pdf.save(str(pdf_path))
    pdf.close()
    return pages, pdf_path
