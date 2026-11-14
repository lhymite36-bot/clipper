from pathlib import Path

from clipper.recap import build_recap_parser
from clipper.recap_scenes import Scene, align_shots, load_srt
from clipper.recap_script import (
    RecapLine,
    _parse_script,
    plot_card_for,
    target_word_count,
    write_script,
)
from clipper.recap_tts import _estimate_words, list_voices, resolve_voice
from clipper.transcribe import Transcript, Word


def test_sintel_fallback_script_has_hook_and_cta():
    tr = Transcript("Scales, come back!", "en", [], [Word("Scales", 20, 20.4), Word("come", 20.4, 20.6), Word("back!", 20.6, 21.0)], 100)
    script = write_script("Sintel", tr, fmt="short", spoilers=False, llm=False)
    assert script.lines
    assert script.hook
    assert "wait for it" not in script.hook.lower()
    assert any(ln.beat == "cta" for ln in script.lines)
    assert script.source_used == "heuristic"
    # Spoiler-free should not dump the mother-dragon ending.
    blob = script.full_text.lower()
    assert "mother" not in blob


def test_parse_script_splits_sentences_and_beats():
    data = {
        "hook": "This girl lost everything",
        "youtube_title": "This girl lost everything | Sintel Recap",
        "description": "A commentary/review recap of Sintel.",
        "tags": ["sintel", "recap"],
        "lines": [
            {"text": "This girl would burn the world down. She found a dragon.", "beat": "hook", "keywords": ["girl", "dragon"]},
            {"text": "Then the hunt begins.", "beat": "conflict"},
            {"text": "Like and subscribe.", "beat": "cta"},
        ],
    }
    script = _parse_script(data, "Sintel", "short", True)
    assert script is not None
    assert script.hook.startswith("This girl")
    assert len(script.lines) >= 4  # first item split into two sentences
    assert script.lines[0].beat == "hook"
    assert script.lines[-1].beat == "cta"


def test_plot_card_and_word_windows():
    assert "dragon" in plot_card_for("Sintel (2010)").lower()
    assert plot_card_for("Unknown Movie 2") == ""
    lo, hi = target_word_count("short")
    assert lo <= 155 <= hi or (lo < 160 and hi - lo < 80)
    lo, hi = target_word_count("long", target_seconds=150)
    # 150s * 150 wpm / 60 = 375, window around that
    assert 280 <= lo <= 375 <= hi <= 480


def test_load_srt(tmp_path: Path):
    srt = tmp_path / "a.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nHello world!\n\n"
        "2\n00:00:04,500 --> 00:00:06,000\nA baby dragon.\n"
    )
    tr = load_srt(srt)
    assert "Hello" in tr.text
    assert "dragon" in tr.text.lower()
    assert tr.words[0].start == 1.0
    assert tr.duration >= 6.0


def test_align_shots_are_short_and_cover_every_line():
    lines = [
        RecapLine("This girl finds a dragon.", "hook", ["dragon", "girl"]),
        RecapLine("She hunts across the mountains.", "conflict", ["mountains"]),
        RecapLine("The twist changes everything.", "twist", ["twist"]),
        RecapLine("Watch the film and subscribe.", "cta", []),
    ]
    durs = [3.0, 5.5, 3.2, 2.5]
    scenes = [Scene(i * 10, i * 10 + 8) for i in range(12)]
    words = [Word("dragon", 12.0, 12.4), Word("mountains", 45.0, 45.5)]
    tr = Transcript("dragon mountains", "en", [], words, 120)
    shots = align_shots(lines, durs, scenes, tr, 120, mirror=True)
    assert shots
    # Every line has at least one shot
    covered = {s.line_index for s in shots}
    assert covered == {0, 1, 2, 3}
    # No long continuous raw scene
    for s in shots:
        assert 1.2 <= (s.src_end - s.src_start) <= 5.01
    # The longer 5.5s line should be split into more than one shot
    assert sum(1 for s in shots if s.line_index == 1) >= 2
    # At least one shot should have used the dragon keyword near 12s
    hook_shots = [s for s in shots if s.line_index == 0]
    assert hook_shots
    assert min(abs(s.src_start - 12.0) for s in hook_shots) < 8


def test_voices_and_word_estimate():
    names = [v["id"] for v in list_voices()]
    assert "en-US-AndrewNeural" in names
    assert "Fenrir" in names
    assert resolve_voice("andrew") == "en-US-AndrewNeural"
    assert resolve_voice("fenrir") == "Fenrir"
    words = _estimate_words("This girl finds a dragon!", 2.0)
    assert [w.word for w in words] == ["This", "girl", "finds", "a", "dragon"]
    assert words[-1].end <= 2.01


def test_recap_parser_requires_title():
    p = build_recap_parser()
    args = p.parse_args(["movie.mp4", "--title", "Sintel", "--format", "long", "--target-seconds", "150"])
    assert args.title == "Sintel"
    assert args.format == "long"
    assert args.target_seconds == 150
