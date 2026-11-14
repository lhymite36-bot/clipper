from clipper.metadata import fill_metadata, keywords, render_sidecar
from clipper.moments import Moment
from clipper.transcribe import Transcript, Word


def test_keywords_skips_stopwords():
    text = "The secret secret secret of the crazy crazy plan and the the the"
    keys = keywords(text, limit=5)
    assert "secret" in keys
    assert "the" not in keys


def test_fill_metadata_and_sidecar():
    words = [
        Word("This", 0, 0.3),
        Word("is", 0.3, 0.5),
        Word("insane", 0.5, 0.9),
        Word("haha", 16.0, 16.4),
    ]
    tr = Transcript("This is insane haha", "en", [], words, 30)
    m = Moment(0, 20, 1, "laughter at 16s", "THIS IS INSANE", title="This is insane", peak=16.2, peak_kind="laugh")
    fill_metadata(m, tr, source_title="My Talk", source_url="https://example.com/v", uploader="Ada")
    assert m.title
    assert m.hook
    assert "WAIT FOR IT" not in m.hook
    assert "Ada" in m.description or "example.com" in m.description
    assert "shorts" in [t.lower() for t in m.hashtags]
    text = render_sidecar(m, 1)
    assert "Title:" in text
    assert "Hashtags:" in text
    assert "#" in text
