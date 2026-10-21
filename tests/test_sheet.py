"""楽譜にする機能の確認（重い採譜モデルは使わず、答えがわかっている音符から楽譜を作る）。"""

import json
import shutil

import numpy as np
import pytest

pytest.importorskip("music21")
pytest.importorskip("verovio")
pytest.importorskip("pymupdf")

from synthmatch import audio  # noqa: E402
from synthmatch.notes import Note, read_pedals, write_midi  # noqa: E402
from synthmatch.sheet.pipeline import rebuild, sheet_from_transcription  # noqa: E402
from synthmatch.sheet.quantize import QNote, quantize, split_hands  # noqa: E402
from synthmatch.sheet.playback import render_midi  # noqa: E402
from synthmatch.sheet.render import _flatten_for_pdf  # noqa: E402
from synthmatch.sheet.score import build_score  # noqa: E402
from synthmatch.sheet.transcribe import Transcription, synth_preview  # noqa: E402

BPM = 100
BEAT = 60 / BPM


def scale_piece(jitter=0.01, seed=0):
    """右手: ドレミファソラシド↑↓（8分音符）、左手: 全音符の和音 C / G を交互に4小節。"""
    rng = np.random.default_rng(seed)
    t0, notes = 0.5, []
    for i, p in enumerate([60, 62, 64, 65, 67, 69, 71, 72, 72, 71, 69, 67, 65, 64, 62, 60]):
        s = t0 + i * 0.5 * BEAT + rng.normal(0, jitter)
        notes.append(Note(p, s, s + 0.45 * BEAT, 90))
    for bar in range(4):
        for p in [48, 52, 55] if bar % 2 == 0 else [43, 47, 50]:
            s = t0 + bar * 4 * BEAT + rng.normal(0, jitter)
            notes.append(Note(p, s, s + 3.8 * BEAT, 70))
    return notes


def test_quantize_to_eighths_and_split_hands():
    notes = scale_piece()
    beats = 0.5 + np.arange(40) * BEAT
    q = quantize(notes, beats, grid=4)
    right, left = split_hands(q)
    assert [n.start for n in right] == [i * 0.5 for i in range(16)]
    assert all(n.length == 0.5 for n in right)
    assert {n.pitch for n in left} == {43, 47, 48, 50, 52, 55}
    assert sorted({n.start for n in left}) == [0.0, 4.0, 8.0, 12.0]


def test_wide_chord_is_split_between_hands():
    chord = [QNote(p, 0.0, 1.0) for p in (36, 43, 64, 67, 72)]  # 低いCとG + 高いEGC（すべて境目の上でも下でもない）
    right, left = split_hands(chord, split=30)
    assert [n.pitch for n in left] == [36, 43] and [n.pitch for n in right] == [64, 67, 72]


def test_sheet_files_and_pdf(tmp_path):
    notes = scale_piece()
    y = synth_preview(notes, sr=22050)
    audio.save(tmp_path / "audio.wav", y, 22050)
    write_midi(notes, tmp_path / "transcription.mid", [(0.4, 2.0)])
    render_midi(tmp_path / "transcription.mid", tmp_path / "preview.wav", log=lambda *_: None)
    meta = sheet_from_transcription(Transcription(notes), y, 22050, tmp_path, title="テスト", log=lambda *_: None)

    assert meta["key"] == "C major" and meta["time_signature"] == "4/4"
    assert abs(meta["bpm"] - BPM) < 3
    assert meta["measures"] == 4
    for f in meta["files"].values():
        assert (tmp_path / f).exists(), f
    assert (tmp_path / meta["pages"][0]).read_text().startswith("<svg")

    import pymupdf

    page = pymupdf.open(tmp_path / "score.pdf")[0]
    drawings = page.get_drawings()
    assert len(drawings) > 50
    # 楽譜が用紙の中に描かれている（PDF 変換で縮尺が崩れていない）
    assert all(page.rect.contains(d["rect"]) or d["rect"].is_empty for d in drawings)

    # 楽譜どおりの音は、楽譜の先頭（最初の音 0.5 秒）に頭をそろえてある
    sc, sr = audio.load(tmp_path / "score.wav", sr=22050)
    first = np.argmax(np.abs(sc) > 0.02) / sr
    assert 0.4 < first < 0.65, first

    # 設定を変えて作り直す（ペダルは採譜 MIDI から引き継ぐ）
    meta2 = rebuild(tmp_path, time_signature="3/4", bpm=BPM, key_sharps=-1, log=lambda *_: None)
    assert meta2["time_signature"] == "3/4" and meta2["bpm_fixed"]
    assert meta2["key_sharps"] == -1 and meta2["key_fixed"]
    assert np.allclose(read_pedals(tmp_path / "transcription.mid"), [(0.4, 2.0)], atol=0.01)
    assert json.loads((tmp_path / "sheet.json").read_text())["time_signature"] == "3/4"


def test_key_uses_fewer_accidentals():
    """変ニ長調（♭5）の曲を、同じ音の嬰ハ長調（♯7）と書かない。"""
    db_major = [61, 63, 65, 66, 68, 70, 72, 73]  # D♭ E♭ F G♭ A♭ B♭ C D♭
    q = [QNote(p, i * 1.0, 1.0) for i, p in enumerate(db_major * 2)]
    q += [QNote(p, i * 4.0, 4.0) for i in range(4) for p in (49, 53, 56)]  # 左手で D♭ の和音
    right, left = split_hands(q)
    _, info = build_score(right, left, bpm=90)
    assert info.key == "Db major" and info.key_sharps == -5
    assert all(abs(c["sharps"]) <= 6 for c in info.key_candidates)
    _, info = build_score(right, left, bpm=90, key_sharps=-4)  # 手で調号を指定
    assert info.key_sharps == -4


def test_flatten_for_pdf_inlines_stroke_and_scale():
    svg = (
        '<svg width="840px" height="1188px"><defs></defs>'
        '<svg class="definition-scale" color="black" viewBox="0 0 21000 29700"><path d="M0 0L10 10" stroke-width="2"/></svg></svg>'
    )
    out = _flatten_for_pdf(svg)
    assert 'transform="scale(0.04)"' in out
    assert out.count("<svg") == 1 and out.count("</svg>") == 1
    assert '<path stroke="#000"' in out


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が必要")
def test_sheet_api_with_basic_transcriber(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from synthmatch.ui.server import create_app

    from .test_ui import wait

    melody = [Note(p, 0.5 + i * BEAT, 0.5 + (i + 0.9) * BEAT, 100) for i, p in enumerate([60, 64, 67, 72, 67, 64, 60, 60])]
    wav = tmp_path / "melody.wav"
    audio.save(wav, synth_preview(melody, sr=22050), 22050)
    (tmp_path / "instruments").mkdir()
    client = TestClient(create_app(tmp_path))

    job = client.post(
        "/api/sheet",
        data={"title": "メロディ", "transcriber": "basic", "bpm": str(BPM)},
        files={"file": ("melody.wav", wav.read_bytes(), "audio/wav")},
    ).json()
    job = wait(client, job)
    assert job["status"] == "done", job
    result = job["result"]
    assert result["title"] == "メロディ" and result["notes"] >= 6
    assert client.get(result["urls"]["pdf"]).status_code == 200
    assert client.get(result["page_urls"][0]).status_code == 200

    sheets = client.get("/api/sheets").json()
    assert sheets[0]["name"] == result["name"]
    job = wait(client, client.post(f"/api/sheets/{result['name']}/rebuild", json={"time_signature": "3/4", "bpm": None, "grid": 2, "split": 60}).json())
    assert job["status"] == "done" and job["result"]["time_signature"] == "3/4"


def test_triplets_detected_with_rubato():
    """採譜テスト音源１の小節5：拍の中で 0.40・0.76 の位置（少し揺れた3連符）。"""
    from fractions import Fraction

    from synthmatch.sheet.quantize import detect_triplets

    on = np.array([2.0, 2.40, 2.76, 3.0])
    assert detect_triplets(on) == {2}
    # まっすぐな16分音符や「8分＋16分16分」は3連符にしない
    assert detect_triplets(np.array([0, 0.25, 0.5, 0.75, 1.0])) == set()
    assert detect_triplets(np.array([0, 0.5, 0.75, 1.0])) == set()
    beats = np.arange(10.0)  # 1拍 = 1秒
    q = quantize([Note(60, 2.0, 2.3), Note(62, 2.4, 2.7), Note(64, 2.76, 3.0)], beats, grid=4)
    assert [n.start - q[0].start for n in q] == [0, Fraction(1, 3), Fraction(2, 3)]


def test_rests_are_split_at_beats():
    from synthmatch.sheet.score import _rest_pieces

    # 16分音符のあとの休符（0.25〜4.0）→ 16分休符・8分休符・四分休符・二分休符
    assert _rest_pieces(0.25, 4.0, 1.0, 0.5, 4.0, True) == [(0.25, 0.25), (0.5, 0.5), (1.0, 1.0), (2.0, 2.0)]
    # 小節まるごと → 全休符1つ
    assert _rest_pieces(0.0, 4.0, 1.0, 0.5, 4.0, True) == [(0.0, 4.0)]
    # 3連符の位置からの休符は半拍で分けない
    assert np.allclose(_rest_pieces(1 / 3, 1.0, 1.0, 0.5, 4.0, True), [(1 / 3, 2 / 3)])


def test_pedal_and_recording_end_extend_notes():
    from synthmatch.sheet.quantize import extend_by_pedal

    notes = [Note(60, 0.0, 0.3), Note(64, 1.0, 1.2)]
    ext = extend_by_pedal(notes, [(0.1, 0.9)])
    assert ext[0].end == 0.9 and ext[1].end == 1.2  # ペダル中に離した音だけ伸びる
    beats = np.arange(10.0)
    q = quantize([Note(60, 0.0, 1.0), Note(64, 2.0, 2.1)], beats, held_until=2.1)
    assert [n.to_end for n in q] == [False, True]
    right, left = split_hands(q)
    _, info = build_score(right, left, bpm=60)
    assert info.measures == 1


def _scale_block(tonic, start_bar, bars):
    """tonic の長音階を右手で、主和音を左手で、bars 小節ぶん弾く。"""
    steps = [0, 2, 4, 5, 7, 9, 11, 12]
    out = []
    for b in range(bars):
        t0 = (start_bar + b) * 4
        for i in range(4):
            out.append(QNote(tonic + 12 + steps[(b * 4 + i) % 8], t0 + i, 1))
        out += [QNote(p, t0, 4) for p in (tonic - 12, tonic - 5, tonic - 8 + 12)]
    return out


def test_modulation_is_detected_and_key_changes_inserted():
    import re
    import tempfile

    # 変ニ長調 16小節 → 変ホ長調 16小節 → 変ニ長調 16小節（全音上へ転調して戻る）
    q = _scale_block(61, 0, 16) + _scale_block(63, 16, 16) + _scale_block(61, 32, 16)
    right, left = split_hands(q)
    sc, info = build_score(right, left, bpm=120)
    assert info.key_sharps == -5
    assert [(m["measure"], m["sharps"]) for m in info.modulations] == [(17, -3), (33, -5)]
    f = tempfile.mktemp(suffix=".musicxml")
    sc.write("musicxml", fp=f)
    xml = open(f, encoding="utf-8").read()
    assert re.findall(r"<fifths>(-?\d+)</fifths>", xml) == ["-5", "-3", "-5"] * 2  # 右手・左手それぞれ


def test_no_redundant_accidentals_in_long_piece():
    """長い曲でも、調号どおりの♭に♭を書かない（music21 の印の問題の回帰テスト）。"""
    import re
    import tempfile

    q = _scale_block(63, 0, 120)  # 変ホ長調だけで120小節
    right, left = split_hands(q)
    sc, info = build_score(right, left, bpm=120)
    assert info.key_sharps == -3 and not info.modulations
    f = tempfile.mktemp(suffix=".musicxml")
    sc.write("musicxml", fp=f)
    assert "<accidental" not in open(f, encoding="utf-8").read()


def test_key_plan_changes_only_that_section():
    """区間ごとの調号指定：選び直した区間だけ変わり、ほかの転調は残る。"""
    q = _scale_block(61, 0, 16) + _scale_block(63, 16, 16) + _scale_block(61, 32, 16)
    right, left = split_hands(q)
    _, auto = build_score(right, left, bpm=120)
    plan = [(p["beat"], p["sharps"]) for p in auto.key_plan]
    assert plan == [(0.0, -5), (64.0, -3), (128.0, -5)]

    plan[1] = (64.0, -4)  # 2つ目の区間だけ♭4つに
    _, info = build_score(right, left, bpm=120, key_plan=plan)
    assert [(m["measure"], m["sharps"]) for m in info.modulations] == [(17, -4), (33, -5)]

    _, info = build_score(right, left, bpm=120, key_plan=[plan[0], plan[2]])  # 2つ目の転調をなくす
    assert info.modulations == []  # ♭5→♭5 は1つの区間にまとまる


def _modulating_sheet(tmp_path):
    """変ニ長調8小節 → 変ホ長調8小節 → 変ニ長調8小節（120 BPM）の採譜結果から楽譜を作る。"""
    beat = 0.5
    notes = []
    for q in _scale_block(61, 0, 8) + _scale_block(63, 8, 8) + _scale_block(61, 16, 8):
        s = 0.5 + float(q.start) * beat
        notes.append(Note(q.pitch, s, s + float(q.length) * beat * 0.95, 80))
    y = synth_preview(notes, sr=22050)
    audio.save(tmp_path / "audio.wav", y, 22050)
    write_midi(notes, tmp_path / "transcription.mid")
    render_midi(tmp_path / "transcription.mid", tmp_path / "preview.wav", log=lambda *_: None)
    return sheet_from_transcription(Transcription(notes), y, 22050, tmp_path, title="転調", bpm=120, log=lambda *_: None)


def test_rebuild_keeps_manual_key_plan(tmp_path):
    quiet = lambda *_: None  # noqa: E731
    meta = _modulating_sheet(tmp_path)
    assert [(m["measure"], m["sharps"]) for m in meta["modulations"]] == [(9, -3), (17, -5)]
    assert not meta["key_plan_fixed"]

    # 2つ目の区間（小節9〜）だけ ♭4つに直す → ほかの転調はそのまま
    plan = [(p["beat"], p["sharps"]) for p in meta["key_plan"]]
    plan[1] = (plan[1][0], -4)
    meta = rebuild(tmp_path, key=plan, log=quiet)
    assert [(m["measure"], m["sharps"]) for m in meta["modulations"]] == [(9, -4), (17, -5)]
    assert meta["key_plan_fixed"]

    # 拍子以外の設定を変えて作り直しても、手で直した調号は残る（既定は「前回のまま」）
    meta = rebuild(tmp_path, grid=2, log=quiet)
    assert [(m["measure"], m["sharps"]) for m in meta["modulations"]] == [(9, -4), (17, -5)]

    # 曲全体を1つの調号 → 転調なし。自動に戻すと転調が戻る
    meta = rebuild(tmp_path, key=-5, log=quiet)
    assert meta["modulations"] == [] and meta["key_fixed"]
    meta = rebuild(tmp_path, key="auto", log=quiet)
    assert [(m["measure"], m["sharps"]) for m in meta["modulations"]] == [(9, -3), (17, -5)]
    assert not meta["key_fixed"] and not meta["key_plan_fixed"]


def test_no_double_dots_and_tidy_long_notes():
    """鍵盤を少し早く離した長い音を、三重付点ではなく読みやすい長さで書く。"""
    import tempfile
    import xml.etree.ElementTree as ET
    from fractions import Fraction

    from synthmatch.sheet.score import _PLAIN, _note_pieces, _tidy_length

    assert _tidy_length(Fraction(0), Fraction(15, 4), Fraction(4)) == 4  # 3¾拍 → 全音符
    assert _tidy_length(Fraction(0), Fraction(15, 4), Fraction(15, 4)) == Fraction(15, 4)  # 次の音にぶつかるなら伸ばさない
    # 1¾拍（複付点四分）は、付点1つまでの音符をタイでつないで書く
    pieces = _note_pieces(Fraction(0), Fraction(7, 4), Fraction(1))
    assert len(pieces) == 2 and all(ln in _PLAIN for _, ln in pieces) and sum(ln for _, ln in pieces) == Fraction(7, 4)

    q = [QNote(64, Fraction(0), Fraction(15, 4)), QNote(60, Fraction(4), Fraction(7, 4)), QNote(62, Fraction(6), Fraction(2))]
    right, left = split_hands(q, split=40)
    sc, _ = build_score(right, left, bpm=100)
    f = tempfile.mktemp(suffix=".musicxml")
    sc.write("musicxml", fp=f)
    root = ET.parse(f).getroot()
    assert max(len(n.findall("dot")) for n in root.iter("note")) <= 1


def test_double_barline_before_modulation():
    import tempfile
    import xml.etree.ElementTree as ET

    q = _scale_block(61, 0, 16) + _scale_block(63, 16, 16)
    right, left = split_hands(q)
    sc, info = build_score(right, left, bpm=120)
    assert [m["measure"] for m in info.modulations] == [17]
    f = tempfile.mktemp(suffix=".musicxml")
    sc.write("musicxml", fp=f)
    part = ET.parse(f).getroot().find("part")
    styles = {m.get("number"): b.findtext("bar-style") for m in part.findall("measure") for b in m.findall("barline")}
    assert styles.get("16") == "light-light"
