from clipper.moments import (
    Moment,
    _hook_from_text,
    _is_generic_hook,
    detect_payoffs,
    heuristic_moments,
    make_hook,
    window_around_payoff,
    word_score,
)
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
    hook, title = _hook_from_text("they all start laughing. this is the rest of the sentence that is long")
    assert hook
    assert "WAIT FOR IT" not in hook
    assert hook.isupper() or hook.endswith("!")
    assert len(hook) <= 60
    assert title


def test_hook_from_empty_is_neutral():
    hook, title = _hook_from_text("")
    assert hook == ""
    assert title
    assert "WAIT" not in hook.upper()


def test_generic_hook_not_invented_without_payoff():
    hook, title = make_hook(
        _tr([("hello", 0.2, 0.6), ("everyone", 0.6, 1.0)], 20),
        0,
        20,
        peak=None,
        has_speech=True,
    )
    assert not _is_generic_hook(hook)
    assert hook.upper() != "WAIT FOR IT"


def test_no_speech_means_no_hook():
    empty = Transcript(text="", language="en", segments=[], words=[], duration=20)
    hook, title = make_hook(empty, 0, 20, peak=15.0, peak_kind="loud", has_speech=False)
    assert hook == ""
    assert title


def test_wait_for_it_allowed_only_with_verified_payoff():
    words = [
        ("Wait", 1.0, 1.3),
        ("for", 1.3, 1.5),
        ("it!", 1.5, 2.0),
        ("This", 12.0, 12.3),
        ("is", 12.3, 12.5),
        ("insane", 12.5, 13.2),
    ]
    tr = _tr(words, 20)
    hook, _title = make_hook(tr, 0, 16, peak=12.7, peak_kind="reaction")
    # Specific payoff line is preferred; a generic hook is only ok because it was spoken
    # and the payoff is in the last 30%. Either "THIS IS INSANE" or "WAIT FOR IT" is honest.
    assert hook
    if _is_generic_hook(hook):
        assert "WAIT FOR IT" in hook
        # still requires last-30% payoff — already passed into make_hook
    else:
        assert "INSANE" in hook or "THIS" in hook


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
    punchy = [m for m in moments if m.start <= 25 <= m.end]
    assert punchy, moments
    m = punchy[0]
    assert m.peak is not None
    assert 22 <= m.peak <= 28
    assert m.payoff_in_last_30()
    # Hold a short reaction, but stop at the pause after the last punchy word.
    assert m.end >= m.peak + 0.5
    assert m.end >= 27.4
    assert m.end <= m.peak + 5.0
    assert "WAIT FOR IT" not in (m.hook or "").upper() or "INSANE" in (m.hook or "").upper() or "HAHA" in (m.hook or "").upper()


def test_short_video_without_payoff_is_dropped():
    words = [("hello", 0.2, 0.6), ("world", 0.6, 1.0)]
    moments = heuristic_moments(_tr(words, 12), 12, 3, min_dur=15, max_dur=60)
    assert moments == []


def test_short_video_with_payoff_keeps_the_whole_clip():
    words = [("hello", 0.2, 0.6), ("wow", 8.0, 8.4), ("haha", 8.5, 9.0)]
    moments = heuristic_moments(_tr(words, 12), 12, 3, min_dur=15, max_dur=60)
    assert len(moments) == 1
    assert moments[0].start == 0
    assert moments[0].end == 12
    assert moments[0].peak is not None


def test_moments_do_not_overlap():
    words = []
    t = 0.0
    phrase = "now this is insane wow haha unbelievable crazy".split()
    while t < 90:
        for w in phrase:
            words.append((w, t, t + 0.3))
            t += 0.35
        t += 8  # keep payoffs from being one continuous blob
    moments = heuristic_moments(_tr(words, 100), 100, 4, min_dur=15, max_dur=25)
    assert 1 <= len(moments) <= 4
    ordered = sorted(moments, key=lambda m: m.start)
    for a, b in zip(ordered, ordered[1:]):
        assert a.end <= b.start + 0.41


def test_window_puts_payoff_in_last_30_percent():
    bounds = [(0, 5), (5, 12), (12, 20), (20, 28)]
    window = window_around_payoff(24, 80, bounds, 15, 60)
    assert window is not None
    start, end = window
    assert end - start >= 15
    assert end - start <= 60
    assert 0 <= start < end <= 80
    assert end >= 24 + 1.4
    assert end <= 24 + 5
    assert 24 + 0.5 >= start + 0.70 * (end - start)


def test_early_peak_without_setup_is_dropped():
    # A payoff at 2s cannot sit in the last 30% of a 15s+ clip that ends just after it.
    assert window_around_payoff(2.0, 80, [(0, 5), (5, 20)], 15, 60) is None


def test_moment_to_dict_includes_peak():
    m = Moment(1, 20, 2.5, "reason", "HOOK", title="T", peak=17.0, peak_kind="laugh")
    d = m.to_dict()
    assert d["start"] == 1
    assert d["duration"] == 19
    assert d["hook"] == "HOOK"
    assert d["peak"] == 17.0
    assert d["peak_kind"] == "laugh"


def test_quiet_leftover_is_not_padded():
    # One real payoff at the start; leftover quiet talk must not become a second clip.
    words = []
    t0 = 0.0
    for w in "this is insane wow haha unbelievable crazy".split():
        words.append((w, t0 + 20, t0 + 20.4))
        t0 += 0.45
    t0 = 70.0
    for w in "and then later on something else happens here".split():
        words.append((w, t0, t0 + 0.4))
        t0 += 0.45
    moments = heuristic_moments(_tr(words, 90), 90, 2, min_dur=15, max_dur=60)
    assert len(moments) == 1
    assert moments[0].peak is not None
    assert 18 <= moments[0].peak <= 26


def test_does_not_pad_count_without_peaks():
    words = []
    t = 0.0
    for w in "today we are going to review the files on the desk and sit down".split() * 8:
        words.append((w, t, t + 0.3))
        t += 0.35
    moments = heuristic_moments(_tr(words, t), t, 5, min_dur=15, max_dur=60)
    assert moments == []


def test_detect_payoffs_ranks_laughter_above_filler():
    words = [
        ("hello", 2.0, 2.3),
        ("everyone", 2.3, 2.7),
        ("wow", 20.0, 20.3),
        ("haha", 20.4, 20.8),
    ]
    peaks = detect_payoffs(_tr(words, 40), 40)
    assert peaks
    assert any(18 <= p.time <= 23 for p in peaks)
    assert peaks[0].kind in {"laugh", "reaction"}


def test_later_punchline_wins_nearby_setup():
    """A mid-clip 'oh/what' must not cut off a laugh a few seconds later."""
    words = [
        ("Wait", 1.0, 1.3),
        ("for", 1.3, 1.5),
        ("it", 1.5, 1.8),
        ("Oh", 10.0, 10.3),
        ("what?", 10.3, 10.6),
        ("I", 15.5, 15.7),
        ("knew", 15.7, 16.0),
        ("it!", 16.0, 16.4),
        ("haha", 16.4, 16.8),
    ]
    peaks = detect_payoffs(_tr(words, 25), 25)
    assert peaks
    # The kept peak in this cluster should be the laugh, not 'oh/what'.
    cluster = [p for p in peaks if 8 <= p.time <= 18]
    assert cluster
    best = cluster[0] if len(cluster) == 1 else max(cluster, key=lambda p: p.score)
    # After later-landing NMS there should be a single peak near the laugh.
    nearby = [p for p in peaks if abs(p.time - best.time) < 8]
    assert len(nearby) == 1
    assert nearby[0].time >= 15.0


def test_window_stops_before_next_sentence():
    """A new sentence after the payoff must not be eaten by the default hold."""
    bounds = [(8.0, 16.0), (16.0, 24.3), (24.5, 27.8)]
    window = window_around_payoff(24.0, 80, bounds, 15, 60)
    assert window is not None
    start, end = window
    assert end <= 24.55
    assert end >= 24.35
    assert end - start >= 15
    assert 24.0 + 0.5 >= start + 0.70 * (end - start)


def test_window_stops_at_scene_cut():
    bounds = [(8.0, 28.0)]
    window = window_around_payoff(24.0, 80, bounds, 15, 60, cuts=[25.0])
    assert window is not None
    start, end = window
    assert 24.85 <= end <= 25.0
    assert end - start >= 15


def test_speech_breaks_mark_pauses():
    from clipper.moments import speech_breaks

    words = [
        ("I", 10.0, 10.2),
        ("knew", 10.2, 10.5),
        ("it", 10.5, 10.8),
        ("The", 12.0, 12.3),
        ("second", 12.3, 12.6),
        ("question", 12.6, 13.0),
    ]
    breaks = speech_breaks(_tr(words, 20), min_gap=0.7)
    assert len(breaks) == 1
    assert 10.8 <= breaks[0] <= 11.1
