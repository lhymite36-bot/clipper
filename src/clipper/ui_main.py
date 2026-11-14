"""Entry point for the windowed Windows app: always open the local web UI."""

from clipper.web import serve


def main() -> int:
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
