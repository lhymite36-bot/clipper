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


def test_static_banner_lasts_the_clip_and_colours_keywords(tmp_path: Path):
    words = [Word("Hello", 0.2, 0.5), Word("world!", 0.5, 0.9)]
    tr = Transcript("Hello world!", "en", [], words, 8)
    path = build_ass(
        tr,
        tmp_path / "b.ass",
        hook="When Hello lands",
        hook_keywords=["Hello"],
        duration=8.0,
        word_captions=True,
    )
    text = path.read_text(encoding="utf-8")
    # Banner runs for the full clip, not a 2.8s teaser.
    assert "0:00:08.00" in text or "0:00:08." in text
    yellow = "{\\c&H0000E5FF&}Hello{\\r}"
    assert yellow in text
    assert "When" in text


def test_word_captions_can_be_disabled(tmp_path: Path):
    words = [Word("Hello", 0.2, 0.5), Word("world!", 0.5, 0.9)]
    tr = Transcript("Hello world!", "en", [], words, 5)
    path = build_ass(tr, tmp_path / "c.ass", hook="A title", word_captions=False, duration=5)
    text = path.read_text(encoding="utf-8")
    assert "A title" in text
    # No default-style word events (hook is style Hook).
    assert "Default,," not in text
