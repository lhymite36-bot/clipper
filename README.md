# Clipper

Turn a long YouTube video (or a file on your PC) into vertical YouTube Shorts.

Clipper runs **entirely on your computer**. It uses free tools only: `yt-dlp`, local [faster-whisper](https://github.com/SYSTRAN/faster-whisper), optional Gemini / Groq free keys, and a loudness / laughter / keyword fallback when no key is set. There are no paid APIs and nothing is billed.

For each clip it:

1. Downloads the video (or uses your file)
2. Transcribes it locally with word-level timestamps
3. Picks the top N viral moments (15–60 seconds)
4. Reframes to **9:16 1080×1920** (face crop, center crop, or blurred background)
5. Burns in **bold word-by-word captions** and an optional hook line on top
6. Writes an **H.264 MP4** plus a suggested title, description and hashtags

```text
clip https://www.youtube.com/watch?v=VIDEO --count 5
```

On Windows the system already has a `clip` command (it copies text to the clipboard), so use `clipper` instead — it is the same program:

```text
clipper https://www.youtube.com/watch?v=VIDEO --count 5
```

## What you need to know about rights

Only clip videos you have the right to use: your own content, public-domain / Creative Commons videos (and follow the license, including credit), or a creator's official clipping program. Reposting someone else's video as Shorts can get the clip taken down.

## Windows: one-click installer

1. Open the [latest release](https://github.com/lhymite36-bot/clipper/releases/latest).
2. Download **Clipper-Setup.exe** and run it. No admin account is required; it installs into your user folder.
3. Open **Clipper** from the Start menu (web UI) or **Clipper (Terminal)** for the command line.
4. The first run downloads a small Whisper speech model (~75 MB, one time). FFmpeg is bundled.

Then in a new terminal:

```text
clipper https://www.youtube.com/watch?v=VIDEO --count 5 --out %USERPROFILE%\Videos\Clips
```

Or type `clipper --ui` (or just open the Start menu shortcut) and paste a URL in the browser window.

## Windows: install from source

If you prefer not to use the installer:

1. Install [Python 3.11 or 3.12](https://www.python.org/downloads/) and tick **Add python.exe to PATH**.
2. Install [FFmpeg](https://www.gyan.dev/ffmpeg/builds/) (get the *essentials* zip, then add its `bin` folder to your PATH), or with winget: `winget install Gyan.FFmpeg`.
3. Open PowerShell in a folder of your choice:

```powershell
git clone https://github.com/lhymite36-bot/clipper.git
cd clipper
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e .
clipper --selftest
clipper https://www.youtube.com/watch?v=VIDEO --count 5 --out .\clips
```

If PowerShell blocks the venv script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then activate again.

## macOS / Linux

```bash
sudo apt install ffmpeg   # Debian/Ubuntu. macOS: brew install ffmpeg
git clone https://github.com/lhymite36-bot/clipper.git
cd clipper
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
clip --selftest
clip https://www.youtube.com/watch?v=VIDEO --count 5 --out ./clips
```

## Usage

```text
clipper SOURCE --count 5 --out clips
```

`SOURCE` is a YouTube (or other yt-dlp) URL, or a local video file.

| Flag | Meaning | Default |
| --- | --- | --- |
| `--count`, `-n` | How many clips to make | `5` |
| `--out`, `-o` | Output folder | `./clips` |
| `--model` | Whisper size: `tiny`, `base`, `small`, `medium`, `large-v3` | `tiny` |
| `--hook` | Hook text on every clip. If omitted, one is written per clip | auto |
| `--style` | `auto`, `face`, `center`, or `blur` | `auto` |
| `--min-duration` / `--max-duration` | Clip length in seconds | `15` / `60` |
| `--no-captions` | Skip burned-in captions | off |
| `--gemini-key` / `--groq-key` | Optional free LLM keys for smarter moment picks | unset |
| `--ui` | Open the local web UI (http://127.0.0.1:8766) | |
| `--selftest` | Check that FFmpeg and the app are installed | |

Each clip folder contains:

- `01-some-title.mp4` — 1080×1920 H.264 Short
- `01-some-title.txt` — title, description, hashtags, hook, timestamp
- `clips.json` — a machine-readable manifest of every clip

### Optional free LLM keys

Clipper works with **no keys**. To let a free model pick the moments instead of the local heuristic, create a `.env` file in the folder you run from (see `.env.example`):

```text
GEMINI_API_KEY=your_free_key
GROQ_API_KEY=your_free_key
```

Get a free Gemini key at [Google AI Studio](https://aistudio.google.com/apikey), or a free Groq key at [console.groq.com](https://console.groq.com/keys). If the model is busy or the key is missing, Clipper falls back to loudness, laughter and keyword scoring on your PC.

On Windows you can also save that `.env` at `%LOCALAPPDATA%\Clipper\.env`.

## How moment picking works without a key

The local heuristic scores the video in half-second bins using:

- Word hits such as *wait*, *insane*, *haha*, *secret*, questions and exclamations
- Loudness peaks (laughter and reactions are usually louder)
- A small boost for the opening seconds

It then grows each peak to a 15–60 s window on sentence boundaries and drops overlaps.

## License

MIT. Bundled fonts (Anton, Montserrat) are SIL Open Font License 1.1. The face-detection cascade is the standard OpenCV Haar cascade (Intel License). See `src/clipper/data/`.
