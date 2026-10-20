"""Web UI の API をデモシンセで確認する。"""

import io
import shutil
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from synthmatch import audio  # noqa: E402
from synthmatch.instruments.demo import DemoInstrument, render_patch  # noqa: E402
from synthmatch.notes import write_midi  # noqa: E402
from synthmatch.ui.server import create_app  # noqa: E402

from .test_pipeline import phrase  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(tmp_path):
    (tmp_path / "instruments").mkdir()
    shutil.copy(ROOT / "instruments" / "demo.toml", tmp_path / "instruments" / "demo.toml")
    return TestClient(create_app(tmp_path))


def wait(client, job, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.2)
    raise TimeoutError(job)


def test_record_and_match(client, tmp_path):
    info = client.get("/api/instruments").json()
    assert info[0]["id"] == "demo" and info[0]["recorded"] == 0

    job = wait(client, client.post("/api/instruments/demo/test", json={}).json())
    assert job["status"] == "done", job
    assert client.get(job["result"]["audio"]).status_code == 200

    job = wait(client, client.post("/api/instruments/demo/build", json={"category": "Pad"}).json())
    assert job["status"] == "done", job
    assert job["result"]["counts"] == {"done": 3}
    assert client.get("/api/instruments/demo").json()["recorded"] == 3

    detail = client.get("/api/instruments/demo/preset", params={"preset_id": "demo-003"}).json()
    assert detail["name"] == "Soft Pad" and detail["recorded"]
    assert set(detail["profile"]) == {"brightness", "attack_ms", "sustain_db", "release_s", "noisiness"}
    assert 0 <= detail["percentile"]["attack_ms"] <= 100
    assert client.get("/api/instruments/demo/preset", params={"preset_id": "demo-000"}).json()["profile"] is None

    presets = client.get("/api/instruments/demo/presets", params={"recorded": True}).json()["presets"]
    assert {p["name"] for p in presets} == {"Soft Pad", "String Pad", "Warm Pad"}
    assert client.get(presets[0]["audio"]).status_code == 200

    notes = phrase()
    wav, mid = tmp_path / "s.wav", tmp_path / "s.mid"
    audio.save(wav, render_patch(DemoInstrument.variant("Warm Pad"), notes, seed=1), 44100)
    write_midi(notes, mid)
    job = client.post(
        "/api/match",
        data={"instrument_id": "demo", "separator": "none", "rerank": "2", "category": "Pad"},
        files={"song": ("song.wav", io.BytesIO(wav.read_bytes()), "audio/wav"), "midi": ("s.mid", io.BytesIO(mid.read_bytes()), "audio/midi")},
    ).json()
    job = wait(client, job)
    assert job["status"] == "done", job
    assert job["result"]["candidates"][0]["name"] == "Warm Pad"
    assert client.get(job["result"]["target_audio"]).status_code == 200
    assert client.get(job["result"]["report_html"]).status_code == 200
    assert client.get("/api/history").json()[0]["top"] == "Warm Pad"


def test_one_job_at_a_time_and_cancel(client):
    job = client.post("/api/instruments/demo/build", json={}).json()
    assert client.post("/api/instruments/demo/build", json={}).status_code == 409
    client.post(f"/api/jobs/{job['id']}/cancel")
    job = wait(client, job)
    assert job["status"] == "cancelled"
    # 中止までに録れた分は反映されている
    assert client.get("/api/instruments/demo").json()["recorded"] == job["progress"]


def test_static_page(client):
    r = client.get("/")
    assert r.status_code == 200 and "synthmatch" in r.text
    assert client.get("/app.js").headers["cache-control"] == "no-cache"
