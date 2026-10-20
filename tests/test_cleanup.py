"""幽霊の音の除去と、和音へのまとめの確認。"""

from synthmatch.notes import Note
from synthmatch.sheet.cleanup import clean, merge_chords, remove_ghosts

TEMPO = 62  # 採譜テスト音源１と同じくらい（16分音符 ≒ 0.24秒）


def measure3():
    """採譜テスト音源１の小節3の頭：F・A・C の和音のあとに幽霊の音、直前に少し早い弱い音。"""
    return [
        Note(49, 11.27, 11.41, 39),  # 少し早い弱い音（C#3）
        Note(53, 11.40, 13.31, 60),  # 左手 F2
        Note(65, 11.39, 11.98, 61),  # F4
        Note(69, 11.39, 11.64, 72),  # A4
        Note(72, 11.38, 12.40, 72),  # C5
        Note(69, 11.65, 11.82, 46),  # A4 の再検出（幽霊）
        Note(63, 11.65, 13.28, 35),  # 弱い E♭4（幽霊）
        Note(69, 11.82, 12.40, 45),  # A4 の再検出（幽霊）
        Note(65, 11.99, 13.35, 31),  # 弱い F4（幽霊）
        Note(77, 14.34, 14.35, 54),  # 0.01秒だけの音
        Note(70, 14.35, 15.53, 58),  # 4拍目の和音
        Note(73, 14.35, 15.72, 52),
        Note(67, 14.36, 15.35, 61),
    ]


def test_removes_ghost_notes_but_keeps_chords():
    notes = measure3()
    removed = remove_ghosts(notes, ratio=0.65, min_dur=0.05)
    assert {(notes[i].start, notes[i].pitch) for i in removed} == {
        (11.27, 49), (11.65, 69), (11.65, 63), (11.82, 69), (11.99, 65), (14.34, 77),
    }


def test_clean_aligns_chord_and_reports():
    out, stats = clean(measure3(), TEMPO, "normal")
    starts = sorted({n.start for n in out})
    assert starts == [11.38, 14.36]  # 1拍目の和音と4拍目の和音だけ（それぞれいちばん強い音の時刻）
    assert len(stats.removed) == 6


def test_soft_passage_is_kept():
    """全体が弱い静かなフレーズは、弱くても消さない（比べるのは周りの音）。"""
    soft = [Note(60 + i, i * 0.5, i * 0.5 + 0.4, 25) for i in range(8)]
    out, stats = clean(soft, TEMPO, "normal")
    assert len(out) == 8 and not stats.removed


def test_fast_sixteenths_are_not_merged_into_chords():
    """速い旋律（120 BPM の16分音符・強弱つき）を和音にまとめない。"""
    sixteenth = 60 / 120 / 4
    run = [Note(72 + i % 5, i * sixteenth, (i + 0.9) * sixteenth, 80 if i % 4 == 0 else 62) for i in range(16)]
    out, stats = clean(run, 120, "normal")
    assert len({n.start for n in out}) == 16 and stats.merged == 0


def test_rolled_chord_is_merged():
    """下から少しずらして弾いた和音は1つにまとめる。"""
    rolled = [Note(48, 1.00, 2.0, 50), Note(55, 1.05, 2.0, 55), Note(64, 1.10, 2.0, 80)]
    out, merged = merge_chords(rolled, tight=0.06, loose=0.12)
    assert {n.start for n in out} == {1.10} and merged == 2


def test_off_keeps_everything():
    notes = measure3()
    out, stats = clean(notes, TEMPO, "off")
    assert len(out) == len(notes) and not stats.removed and stats.merged == 0
