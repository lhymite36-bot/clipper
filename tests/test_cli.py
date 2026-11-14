from clipper.cli import build_parser, main, selftest
from clipper.download import is_url


def test_parser_defaults():
    args = build_parser().parse_args(["https://youtu.be/dQw4w9wgWcQ", "--count", "5"])
    assert args.source.startswith("https://")
    assert args.count == 5
    assert args.model == "tiny"
    assert args.style == "auto"
    assert args.min_duration == 15
    assert args.max_duration == 60


def test_is_url():
    assert is_url("https://www.youtube.com/watch?v=1")
    assert is_url("http://example.com/a.mp4")
    assert not is_url("/tmp/video.mp4")
    assert not is_url("video.mp4")


def test_selftest_runs():
    assert selftest() == 0


def test_version_and_help(capsys):
    try:
        build_parser().parse_args(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    assert main([]) in {0, 1}  # prints help
