"""「楽譜にする」公開版を Hugging Face Spaces にアップロードする。

    .venv/bin/hf auth login                      # 最初に1回（Hugging Face のアクセストークンでログイン）
    .venv/bin/python scripts/deploy_hf_space.py  # Space を作って（なければ）アップロード

アップロードするのは Dockerfile・Space 用 README（deploy/hf-space/）と、src/・pyproject.toml だけ。
録音データや出力（libraries/, out/）、楽器の設定（instruments/）は含めない。
"""

import argparse
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    from huggingface_hub import HfApi

    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="synthmatch", help="Space の名前（URL の最後の部分）")
    ap.add_argument("--private", action="store_true", help="非公開の Space にする")
    a = ap.parse_args()

    api = HfApi()
    user = api.whoami()["name"]
    repo_id = f"{user}/{a.name}"
    api.create_repo(repo_id, repo_type="space", space_sdk="docker", private=a.private, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shutil.copy(ROOT / "deploy" / "hf-space" / "Dockerfile", tmp / "Dockerfile")
        shutil.copy(ROOT / "deploy" / "hf-space" / "README.md", tmp / "README.md")
        shutil.copy(ROOT / "pyproject.toml", tmp / "pyproject.toml")
        shutil.copytree(ROOT / "src", tmp / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"))
        api.upload_folder(folder_path=str(tmp), repo_id=repo_id, repo_type="space", commit_message="synthmatch を更新")

    print(f"アップロードしました: https://huggingface.co/spaces/{repo_id}")
    print("組み立て（ビルド）に 10〜20 分ほどかかります。ページの「Logs」で進み具合を見られます。")


if __name__ == "__main__":
    main()
