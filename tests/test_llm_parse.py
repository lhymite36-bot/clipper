from clipper.llm import _extract_json, _parse_moments


def test_extract_json_from_fence():
    raw = '```json\n{"moments": [{"start": 1, "end": 20, "hook": "HI", "title": "Hi"}]}\n```'
    data = _extract_json(raw)
    assert "moments" in data


def test_parse_clamps_and_fills():
    payload = {
        "moments": [
            {"start": 2, "end": 10, "hook": "WAIT", "title": "Wait", "hashtags": ["shorts", "#funny"]},
            {"start": 8, "end": 90, "reason": "too long"},
            {"start": 50, "end": 40},
        ]
    }
    moments = _parse_moments(payload, duration=80, min_dur=15, max_dur=60, count=5, source="gemini")
    assert moments
    assert all(m.end <= 80 for m in moments)
    assert all(m.end - m.start <= 60 + 0.01 for m in moments)
    assert all(m.end > m.start for m in moments)
    # Overlap dropped
    starts = [m.start for m in moments]
    assert len(starts) == len(set(starts)) or all(
        moments[i].end <= moments[i + 1].start + 0.5 for i in range(len(moments) - 1)
    )
