"""公開モード（Hugging Face Spaces 用）の確認：楽譜にするだけ・ブラウザごとに分ける・順番待ち・上限・自動削除。"""

import os
import shutil
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from synthmatch import audio  # noqa: E402
from synthmatch.notes import Note  # noqa: E402
from synthmatch.sheet.playback import simple_piano  # noqa: E402
from synthmatch.ui.server import create_app, cleanup_once  # noqa: E402

from .test_ui import wait  # noqa: E402

A, B = "a" * 32, "b" * 32
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が必要")


def melody_wav(path, seconds=4.0):
    beat = 0.5
    notes = [Note(p, 0.3 + i * beat, 0.3 + (i + 0.9) * beat, 100) for i, p in enumerate([60, 64, 67, 72, 67, 64, 60, 60])]
    y = simple_piano([n for n in notes if n.end <= seconds], sr=22050)
    audio.save(path, y, 22050)
    return path


def post_sheet(client, owner, wav, **data):
    return client.post(
        "/api/sheet",
        headers={"X-Client-Id": owner},
        data={"transcriber": "basic", "bpm": "120", **data},
        files={"file": ("melody.wav", wav.read_bytes(), "audio/wav")},
    )


@pytest.fixture()
def app_dir(tmp_path):
    return tmp_path


def test_local_only_features_are_hidden(app_dir):
    client = TestClient(create_app(app_dir, public=True))
    assert client.get("/api/config").json()["public"] is True
    for path in ("/api/instruments", "/api/devices", "/api/history"):
        assert client.get(path, headers={"X-Client-Id": A}).status_code == 404
    assert client.get("/api/sheets").status_code == 400  # ブラウザの ID がない
    assert client.get("/api/sheets", headers={"X-Client-Id": "../etc"}).status_code == 400


@needs_ffmpeg
def test_sheets_are_private_per_browser_and_queued(app_dir, tmp_path):
    client = TestClient(create_app(app_dir, public=True))
    wav = melody_wav(tmp_path / "m.wav")
    job_a = post_sheet(client, A, wav).json()
    assert post_sheet(client, A, wav).status_code == 409  # 同じブラウザは同時に1件まで
    job_b = post_sheet(client, B, wav).json()
    assert job_b["status"] == "queued"

    ga = lambda j: client.get(f"/api/jobs/{j['id']}", headers={"X-Client-Id": A})  # noqa: E731
    gb = lambda j: client.get(f"/api/jobs/{j['id']}", headers={"X-Client-Id": B})  # noqa: E731
    assert gb(job_a).status_code == 404  # 他の人のジョブは見えない

    end = time.time() + 120
    while time.time() < end and {ga(job_a).json()["status"], gb(job_b).json()["status"]} - {"done", "error"}:
        time.sleep(0.3)
    ra, rb = ga(job_a).json(), gb(job_b).json()
    assert ra["status"] == "done" and rb["status"] == "done", (ra.get("error"), rb.get("error"))

    sheets_a = client.get("/api/sheets", headers={"X-Client-Id": A}).json()
    sheets_b = client.get("/api/sheets", headers={"X-Client-Id": B}).json()
    assert len(sheets_a) == 1 and len(sheets_b) == 1 and sheets_a[0]["name"] != sheets_b[0]["name"]
    name_a = sheets_a[0]["name"]
    assert client.get(f"/api/sheets/{name_a}", headers={"X-Client-Id": B}).status_code == 404
    assert client.get(ra["result"]["urls"]["pdf"]).status_code == 200


@needs_ffmpeg
def test_upload_and_length_limits(app_dir, tmp_path):
    client = TestClient(create_app(app_dir, public=True, max_upload_mb=0))
    wav = melody_wav(tmp_path / "m.wav")
    assert post_sheet(client, A, wav).status_code == 413

    client = TestClient(create_app(app_dir / "b", public=True, max_minutes=2 / 60))  # 2秒まで
    job = post_sheet(client, A, wav).json()
    end = time.time() + 60
    while time.time() < end:
        job = client.get(f"/api/jobs/{job['id']}", headers={"X-Client-Id": A}).json()
        if job["status"] not in ("queued", "running"):
            break
        time.sleep(0.2)
    assert job["status"] == "error" and "長すぎ" in job["error"]


def test_cleanup_removes_old_sheets(app_dir):
    from synthmatch.ui.server import Jobs

    old = app_dir / "out" / "sheets" / A / "old"
    new = app_dir / "out" / "sheets" / B / "new"
    for d in (old, new):
        d.mkdir(parents=True)
        (d / "sheet.json").write_text("{}")
    past = time.time() - 48 * 3600
    os.utime(old, (past, past))
    assert cleanup_once(app_dir / "out" / "sheets", Jobs(), retention_hours=24) == 1
    assert not old.exists() and not old.parent.exists() and new.exists()
