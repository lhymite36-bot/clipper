from clipper.moments import Moment, _hook_from_text, _grow_window, heuristic_moments, word_score
from clipper.transcribe import Transcript, Word


def _tr(pairs, duration=80.0):
    words = [Word(w, s, e) for w, s, e in pairs]
    text = " ".join(w.word for w in words)
    return Transcript(text=text, language="en", segments=[], words=words, duration=duration)


def test_word_score_boosts_laughter_and_hooks():
    assert word_score("haha") > word_score("table")
    assert word_score("WAIT") > word_score("wait")
    assert word_score("What?") > word_score("what")
    assert word_score("secret") > 1


def test_hook_from_text_caps_and_shortens():
    hook, title = _hook_from_text("wait for it. this is the rest of the sentence that is long")
    assert hook
    assert hook.isupper() or hook.endswith("!")
    assert len(hook) <= 60
    assert title


def test_hook_from_empty():
    hook, title = _hook_from_text("")
    assert "WAIT" in hook.upper()
    assert title


def test_heuristic_prefers_keyword_moments():
    # Quiet intro, then a punchy moment around 25s, then more talk.
    words = []
    t = 0.0
    for w in "hello everyone welcome to the channel today we talk about files".split():
        words.append((w, t, t + 0.4))
        t += 0.45
    t = 24.0
    for w in "Wait wait this is insane wow haha unbelievable".split():
        words.append((w, t, t + 0.4))
        t += 0.45
    t = 50.0
    for w in "and then we go back to normal talking about nothing much here".split():
        words.append((w, t, t + 0.4))
        t += 0.45
    moments = heuristic_moments(_tr(words, 80), 80, 2, min_dur=15, max_dur=60)
    assert len(moments) >= 1
    assert all(15 <= m.duration <= 60 + 0.05 for m in moments)
    # The punchy window should be represented
    assert any(m.start <= 24 <= m.end for m in moments)


def test_short_video_returns_whole_clip():
    words = [("hello", 0.2, 0.6), ("world", 0.6, 1.0)]
    moments = heuristic_moments(_tr(words, 12), 12, 3, min_dur=15, max_dur=60)
    assert len(moments) == 1
    assert moments[0].start == 0
    assert moments[0].end == 12


def test_moments_do_not_overlap():
    words = []
    t = 0.0
    phrase = "wait insane crazy wow haha secret actually never unbelievable".split()
    while t < 90:
        for w in phrase:
            words.append((w, t, t + 0.3))
            t += 0.35
    moments = heuristic_moments(_tr(words, 100), 100, 4, min_dur=15, max_dur=25)
    assert 1 <= len(moments) <= 4
    ordered = sorted(moments, key=lambda m: m.start)
    for a, b in zip(ordered, ordered[1:]):
        assert a.end <= b.start + 0.41


def test_grow_window_respects_bounds():
    bounds = [(0, 5), (5, 12), (12, 20), (20, 40)]
    start, end = _grow_window(14, 80, bounds, 15, 60)
    assert end - start >= 15
    assert end - start <= 60
    assert 0 <= start < end <= 80


def test_moment_to_dict():
    m = Moment(1, 20, 2.5, "reason", "HOOK", title="T")
    d = m.to_dict()
    assert d["start"] == 1
    assert d["duration"] == 19
    assert d["hook"] == "HOOK"


def test_leftover_gap_is_packed_as_another_clip():
    # One loud burst at the start usually grows into a long first window;
    # leftover footage at the end should still become a second clip.
    words = []
    t0 = 0.0
    for w in "wait wait insane wow haha unbelievable crazy".split():
        words.append((w, t0, t0 + 0.4))
        t0 += 0.45
    # quiet later speech so the transcript is not empty in the gap
    t0 = 70.0
    for w in "and then later on something else happens here".split():
        words.append((w, t0, t0 + 0.4))
        t0 += 0.45
    moments = heuristic_moments(_tr(words, 90), 90, 2, min_dur=15, max_dur=60)
    assert len(moments) == 2
    moments = sorted(moments, key=lambda m: m.start)
    assert moments[1].start >= moments[0].end - 0.41
    assert moments[1].end <= 90 + 0.01
    assert moments[1].duration >= 15
