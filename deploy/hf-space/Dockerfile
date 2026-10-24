# synthmatch「楽譜にする」公開版（Hugging Face Spaces 用）
# scripts/deploy_hf_space.py が、このファイルと src/・pyproject.toml を Space にアップロードする。
FROM python:3.12-slim

# 動画・mp3 の読み込み（ffmpeg）と、採譜結果をピアノの音で鳴らす（fluidsynth）
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fluidsynth libsndfile1 \
 && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces は uid 1000 のユーザーで動かすのが推奨
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR /home/user/app

# torch は CPU 版（GPU 版は数GBあり、無料の CPU 環境では使わない）
RUN pip install --no-cache-dir --user torch --index-url https://download.pytorch.org/whl/cpu

COPY --chown=user pyproject.toml README.md ./
COPY --chown=user src ./src
RUN pip install --no-cache-dir --user ".[sheet,ui]"

# 採譜モデル（約170MB）とピアノの音源（約24MB）を先に取っておく（最初に使う人が待たされないように）
RUN python -c "from synthmatch.sheet.transcribe import ensure_model; ensure_model()" \
 && python -c "from synthmatch.sheet.playback import ensure_soundfont; assert ensure_soundfont()"

EXPOSE 7860
CMD ["synthmatch", "ui", "--public", "--host", "0.0.0.0", "--port", "7860", "--no-browser", "--root", "/home/user/app/data"]
