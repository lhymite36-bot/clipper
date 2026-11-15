import sys
import zipfile

import pytest

from clipper import ytdlp_runtime as r


@pytest.mark.parametrize(
    "text,expected",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("youtu.be/dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"),
        ("Look! https://youtube.com/shorts/dQw4w9WgXcQ?si=abc", "https://youtube.com/shorts/dQw4w9WgXcQ?si=abc"),
        ("dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("  m.youtube.com/watch?v=dQw4w9WgXcQ  ", "https://m.youtube.com/watch?v=dQw4w9WgXcQ"),
    ],
)
def test_normalize_source(text, expected):
    assert r.normalize_source(text) == expected


def test_normalize_rejects_words():
    with pytest.raises(ValueError):
        r.normalize_source("hello there")


def test_local_paths_pass_through(tmp_path):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"x")
    assert r.normalize_source(str(f)) == str(f)


@pytest.mark.parametrize(
    "raw,needle",
    [
        ("ERROR: [youtube] x: Sign in to confirm you're not a bot.", "prove it isn't a bot"),
        ("ERROR: [youtube] x: This video is unavailable", "unavailable"),
        ("ERROR: [youtube] x: Private video. Sign in", "private"),
        ("ERROR: Unsupported URL: https://example.com", "can't download from that link"),
        ("<urlopen error [Errno 11001] getaddrinfo failed>", "internet"),
        ("ERROR: unable to download video data: HTTP Error 403: Forbidden", "403"),
    ],
)
def test_friendly_errors(raw, needle):
    assert needle in r.friendly_error(Exception(raw))


def test_zip_first_finder_serves_package_and_submodules(tmp_path, monkeypatch):
    archive = tmp_path / "fake.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("yt_dlp/__init__.py", "from yt_dlp import version\n")
        z.writestr("yt_dlp/version.py", "__version__ = '9999.01.01'\n")
        z.writestr("yt_dlp_ejs/__init__.py", "")
    for name in [m for m in sys.modules if m == "yt_dlp" or m.startswith("yt_dlp.") or m.startswith("yt_dlp_ejs")]:
        monkeypatch.delitem(sys.modules, name)
    finder = r._ZipFirstFinder(str(archive))
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])
    import yt_dlp  # noqa: F401

    assert yt_dlp.version.__version__ == "9999.01.01"
    assert str(archive) in yt_dlp.__file__
    for name in [m for m in sys.modules if m == "yt_dlp" or m.startswith("yt_dlp.") or m.startswith("yt_dlp_ejs")]:
        del sys.modules[name]
