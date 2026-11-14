from clipper.style import (
    build_hook_banner,
    choose_layout_mode,
    colorize_keywords,
    normalize_preset,
    output_duration,
    pick_preset,
    plan_layout,
    resolve_spec,
    speed_filter,
    speed_segments,
    src_to_out,
    suggest_titles,
)
from clipper.transcribe import Transcript, Word


def _tr(pairs, duration=20.0, text=""):
    words = [Word(w, s, e) for w, s, e in pairs]
    joined = text or " ".join(w for w, *_ in pairs)
    return Transcript(joined, "en", [], words, duration)


def test_normalize_and_presets():
    assert normalize_preset("Story Skit") == "story-skit"
    assert normalize_preset("cinematic") == "cinematic-edit"
    assert normalize_preset("sports") == "sports-montage"
    spec = resolve_spec("story-skit")
    assert spec.captions == "words"
    assert spec.speed_ramps is False
    assert spec.punch is True
    sports = resolve_spec("sports-montage")
    assert sports.speed_ramps is True
    assert sports.captions == "none"
    cine = resolve_spec("cinematic-edit")
    assert cine.grade == "moody"
    assert cine.layout == "bars"


def test_pick_preset_prefers_story_when_there_is_speech():
    tr = _tr([("Hello", 0, 0.4), ("there", 0.4, 0.8), ("friend", 0.8, 1.2)] * 12, duration=20)
    assert pick_preset(tr, 20, 16 / 9) == "story-skit"


def test_pick_preset_sports_when_little_speech():
    tr = _tr([("go", 1, 1.2)], duration=30)
    assert pick_preset(tr, 30, 16 / 9) in {"sports-montage", "cinematic-edit"}


def test_layout_auto_letterbox_for_wide_and_tight_for_vertical():
    assert choose_layout_mode(1920, 1080, preferred="auto", has_face=False) == "fill"
    assert choose_layout_mode(1080, 1920, preferred="auto", has_face=False) == "tight"
    plan = plan_layout(1920, 1080, preferred="auto")
    assert plan.mode == "fill"
    assert plan.vf.startswith("FILL:")
    # Hook lives in a compact top bar; sharp 16:9 sits under it.
    assert 360 <= plan.top_bar <= 480
    assert plan.hook_margin_v >= 150
    bars = plan_layout(1920, 1080, preferred="bars")
    assert bars.mode == "bars"
    assert "pad=1080:1920" in bars.vf
    assert f":{bars.top_bar}:black" in bars.vf
    tight = plan_layout(1080, 1920, preferred="auto")
    assert tight.mode == "tight"
    assert tight.top_bar >= 300  # hook lives in the top ~20%


def test_speed_remap_puts_peak_later_after_slowmo():
    segs = speed_segments(10.0, 8.0, enabled=True, slow=0.5, fast=1.5, slow_hold=1.6)
    assert any(s.speed == 0.5 for s in segs)
    assert any(s.speed == 1.5 for s in segs)
    # Dead time is sped up, so the output peak is earlier than 8s, and
    # the slow section lasts ~2x its source length.
    out_peak = src_to_out(8.0, segs)
    assert 4.0 < out_peak < 8.0
    assert output_duration(segs) != 10.0
    fc = speed_filter(segs)
    assert fc is not None
    assert "split=" in fc[0] and "atempo=0.500" in fc[1]


def test_no_ramps_when_disabled():
    segs = speed_segments(10.0, 8.0, enabled=False)
    assert segs == speed_segments(10.0, None, enabled=True) or (
        len(segs) == 1 and segs[0].speed == 1.0
    )
    assert speed_filter(segs) is None


def test_curiosity_hook_from_question_and_when_clause():
    tr = _tr(
        [
            ("What", 1.0, 1.2),
            ("can", 1.2, 1.4),
            ("I", 1.4, 1.5),
            ("do?", 1.5, 1.8),
            ("I", 8.0, 8.2),
            ("knew", 8.2, 8.5),
            ("it!", 8.5, 8.8),
        ],
        duration=12,
    )
    banner = build_hook_banner(tr, 0, 12, peak=8.6, peak_kind="laugh", hook_case="title")
    assert banner.display
    assert "wait for it" not in banner.display.lower()
    assert "?" in banner.text or banner.text.lower().startswith("when ")


def test_hook_never_invents_wait_for_it_without_speech():
    tr = Transcript("", "en", [], [], 20)
    banner = build_hook_banner(tr, 0, 20, peak=None, peak_kind="action")
    assert banner.display == ""
    assert "WAIT FOR IT" not in banner.display


def test_colorize_keywords_paints_yellow():
    text = "When developers forget it's just a game"
    out = colorize_keywords(text, ["developers", "game"])
    assert r"{\c&H0000E5FF&}developers{\r}" in out
    assert r"{\c&H0000E5FF&}game{\r}" in out


def test_titles_dont_promise_sound_unless_audio_payoff():
    titles = suggest_titles("When the setup lands", peak_kind="action", has_speech=True)
    assert all("don't check the sound" not in t.lower() for t in titles)
    laugh = suggest_titles("I knew it", peak_kind="laugh", has_speech=True)
    assert all("don't check the sound" not in t.lower() for t in laugh)
    assert "I knew it" in laugh or any("knew" in t.lower() for t in laugh)
    sound = suggest_titles("Don't miss this sound", peak_kind="loud", has_speech=True)
    assert any(t.lower() == "don't check the sound" for t in sound)
    questions = suggest_titles("What can I do?", peak_kind="reaction", has_speech=True)
    assert all(not t.lower().startswith("when what") for t in questions)
    assert any("what can i do" in t.lower() for t in questions)
