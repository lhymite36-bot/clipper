from clipper.autofind import (
    looks_like_brief,
    normalize_license,
    trailer_query,
    video_id_from_url,
    ytsearch_query,
    ytdlp_search_args,
    add_source,
    discover,
    mark_seen,
    record_used,
    remaining_today,
    used_today,
)
from clipper.publish import enqueue, load_queue, save_queue


def test_search_query_and_cc_filter():
    q = ytsearch_query("funny cats", cc_only=True)
    assert q.startswith("ytsearch10:")
    assert "creativecommons" in q
    assert "funny cats" in q
    args = ytdlp_search_args("funny cats", cc_only=True)
    assert args[0] == "yt-dlp"
    assert "--match-filter" in args
    assert any("Creative Commons" in a for a in args)
    plain = ytdlp_search_args("funny cats", cc_only=False)
    assert "--match-filter" not in plain
    assert trailer_query("Sintel") == "ytsearch5:Sintel official trailer"


def test_brief_hosts_and_ids():
    assert looks_like_brief("https://app.contentrewards.com/campaigns/abc")
    assert looks_like_brief("https://vyro.ai/brief/1")
    assert looks_like_brief("https://clipster.io/x")
    assert looks_like_brief("https://indclip.com/b/1")
    assert not looks_like_brief("https://youtube.com/watch?v=dQw4w9WgXcQ")
    assert video_id_from_url("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert normalize_license("creative commons") == "Creative Commons"


def test_dedupe_daily_cap_and_queue_fields(tmp_path, monkeypatch):
    from clipper import autofind
    from clipper import publish
    from clipper import config

    monkeypatch.setattr(autofind, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(publish, "queue_path", lambda: tmp_path / "queue.json")
    monkeypatch.setattr(config, "load_settings", lambda: {"autofind_daily_cap": 1, "autopilot": False})
    monkeypatch.setattr(autofind, "load_settings", lambda: {"autofind_daily_cap": 1, "autopilot": False})

    add_source("keyword", "cats", label="Cats")
    jsonl = (
        '{"id":"aaaaaaaaaaa","title":"One","webpage_url":"https://youtu.be/aaaaaaaaaaa","license":"Creative Commons"}\n'
        '{"id":"bbbbbbbbbbb","title":"Two","webpage_url":"https://youtu.be/bbbbbbbbbbb","license":""}\n'
    )
    found = discover(runner=lambda args: jsonl)
    assert len(found) == 1
    assert found[0]["license"] == "Creative Commons"
    mark_seen([found[0]["video_id"]])
    record_used(1)
    assert used_today() == 1
    assert remaining_today() == 0
    assert discover(runner=lambda args: jsonl) == []

    item = enqueue({
        "path": str(tmp_path / "out.mp4"),
        "title": "One",
        "description": "One",
        "hashtags": ["#cats"],
        "hook": "Wait",
        "source_url": found[0]["url"],
        "source_label": found[0]["source_label"],
        "license": found[0]["license"],
        "found_by": "keyword",
    })
    assert item["status"] == "pending_review"
    loaded = load_queue()[0]
    assert loaded["license"] == "Creative Commons"
    assert loaded["source_label"] == "Cats"
    assert loaded["found_by"] == "keyword"
    assert loaded["status"] != "posted"
