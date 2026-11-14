from pathlib import Path

from clipper.captions import build_ass, group_words, _ass_time, _esc
from clipper.transcribe import Transcript, Word


def test_ass_time_format():
    assert _ass_time(0) == "0:00:00.00"
    assert _ass_time(65.5) == "0:01:05.50"
    assert _ass_time(3723.04).startswith("1:02:03")


def test_esc_braces():
    assert r"\{" in _esc("{hi}")


def test_group_words_splits_on_count_and_gaps():
    words = [
        Word("one", 0, 0.2),
        Word("two", 0.2, 0.4),
        Word("three", 0.4, 0.6),
        Word("four", 0.6, 0.8),
        Word("five", 0.8, 1.0),
        Word("six", 1.0, 1.2),
        Word("later", 5.0, 5.3),
    ]
    groups = group_words(words, max_words=5, max_duration=2.8)
    assert len(groups) == 3
    assert [w.word for w in groups[0]] == ["one", "two", "three", "four", "five"]
    assert groups[1][0].word == "six"
    assert groups[2][0].word == "later"


def test_build_ass_writes_hook_and_words(tmp_path: Path):
    words = [Word("Hello", 0.2, 0.5), Word("world!", 0.5, 0.9), Word("Wow", 2.0, 2.4)]
    tr = Transcript("Hello world! Wow", "en", [], words, 5)
    path = build_ass(tr, tmp_path / "c.ass", hook="WAIT FOR IT")
    text = path.read_text(encoding="utf-8")
    assert "WAIT FOR IT" in text
    assert "Dialogue:" in text
    assert "Hello" in text
    assert "PlayResX: 1080" in text
    assert "PlayResY: 1920" in text
    # Active word is highlighted in yellow-ish ASS colour
    assert r"\c&H0000E5FF&" in text
