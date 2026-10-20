"""ピアノの音声から楽譜を作る。

音声 → 採譜（transcribe） → 拍の推定（beats） → 拍の格子にそろえる（quantize）
→ 右手・左手に分けて楽譜にする（score） → SVG / PDF に描く（render）
"""
