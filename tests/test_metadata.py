from clipper.metadata import fill_metadata, keywords, render_sidecar
from clipper.moments import Moment
from clipper.transcribe import Transcript, Word


def test_keywords_skips_stopwords():
    text = "The secret secret secret of the crazy crazy plan and the the the"
    keys = keywords(text, limit=5)
    assert "secret" in keys
    assert "the" not in keys


def test_fill_metadata_and_sidecar():
    words = [Word("Wait", 0, 0.3), Word("for", 0.3, 0.5), Word("it", 0.5, 0.8)]
    tr = Transcript("Wait for it", "en", [], words, 30)
    m = Moment(0, 20, 1, "a loud laugh", "")
    fill_metadata(m, tr, source_title="My Talk", source_url="https://example.com/v", uploader="Ada")
    assert m.title
    assert m.hook
    assert "Ada" in m.description or "example.com" in m.description
    assert "shorts" in [t.lower() for t in m.hashtags]
    text = render_sidecar(m, 1)
    assert "Title:" in text
    assert "Hashtags:" in text
    assert "#" in text
