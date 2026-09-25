"""デモシンセで全体の流れを確認する。"""

from pathlib import Path

import pytest

from synthmatch import audio
from synthmatch.instruments import load_instrument
from synthmatch.instruments.demo import DemoInstrument, render_patch
from synthmatch.library import Library, build_library
from synthmatch.matcher import match
from synthmatch.notes import Note, read_midi, write_midi
from synthmatch.pipeline import run

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "instruments" / "demo.toml"


def phrase():
    notes, t = [], 0.0
    for chord in ([57, 60, 64], [53, 57, 60]):
        notes += [Note(p, t, t + 1.5, 95) for p in chord]
        t += 2.5
    for p in (69, 72, 76, 74):
        notes.append(Note(p, t, t + 0.4, 105))
        t += 0.6
    return notes


@pytest.fixture(scope="module")
def library(tmp_path_factory) -> Library:
    return build_library(load_instrument(DEMO), tmp_path_factory.mktemp("lib"))


@pytest.mark.parametrize("name", ["Soft Pad", "Pluck", "Brass", "Organ", "Bell"])
def test_finds_original_preset(library, name):
    """少し変えた音でも、元の音色が1位になる。"""
    notes = phrase()
    y = render_patch(DemoInstrument.variant(name, cutoff=DemoInstrument.variant(name).cutoff * 0.85), notes, seed=7)
    inst = load_instrument(DEMO)
    cands = match(y, inst.sample_rate, notes, library, inst, top=3, rerank=3, log=lambda *_: None)
    assert cands[0].name == name


def test_hint_suggests_lower_cutoff(library):
    notes = phrase()
    y = render_patch(DemoInstrument.variant("Saw Lead", cutoff=2500), notes, seed=7)
    inst = load_instrument(DEMO)
    cands = match(y, inst.sample_rate, notes, library, inst, top=5, rerank=5, log=lambda *_: None)
    saw = next(c for c in cands if c.name == "Saw Lead")
    assert any("Cutoff" in h and "下げる" in h for h in saw.hints)


def test_run_end_to_end(library, tmp_path):
    notes = phrase()
    song = tmp_path / "song.wav"
    midi = tmp_path / "song.mid"
    audio.save(song, render_patch(DemoInstrument.variant("String Pad"), notes, seed=3), 44100)
    write_midi(notes, midi)
    report = run(song, DEMO, tmp_path / "out", separator="none", midi=midi, library_dir=library.path, rerank=3, log=lambda *_: None)
    assert report["candidates"][0]["name"] == "String Pad"
    assert (tmp_path / "out" / "report.md").exists()
    assert len(read_midi(tmp_path / "out" / "notes.mid")) == len(notes)
