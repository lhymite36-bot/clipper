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
| `--preset` | Look: `auto`, `cinematic-edit`, `story-skit`, `sports-montage` | `auto` |
| `--layout` | `auto`, `tight` 9:16 crop, 16:9 `bars`, or `blur` fill | `auto` |
| `--grade` | `auto`, `none`, `moody`, `contrast`, `warm` | `auto` |
| `--style` | Crop hint when the layout is tight: `auto`, `face`, `center`, `blur` | `auto` |
| `--captions` | `auto` (words for speech, none for montages), `words`, `minimal`, `none` | `auto` |
| `--music` | Optional royalty-free or user-supplied music bed (local file only) | unset |
| `--min-duration` / `--max-duration` | Clip length in seconds | `15` / `60` |
| `--no-captions` | Skip burned-in captions | off |
| `--no-punch` | Skip the short zoom at the payoff | off |
| `--no-loop` | Don't snap the out-point to a calm frame | off |
| `--speed-ramps` | Force 1.5× / 0.5× sports ramps (off for story-skit) | off |
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

Clipper only keeps a clip when it can find a real payoff: a punchline, a laugh or reaction in the transcript, a loud spike, a scene change, or an action beat. It starts a little before the setup and **ends 2–4 seconds after that payoff**, so the peak sits in the last 30% of the clip. If it cannot find that many payoffs, it returns fewer clips rather than padding the count with dead air.

Hooks are written from words that were actually spoken (or left off when there is no speech). It will not put a generic “WAIT FOR IT” on screen unless that phrase is in the transcript *and* a verified payoff lands in the last 30% of the clip.

A short punch-in zoom hits at the payoff (disable with `--no-punch`).

### Style presets

Pick a look with `--preset`, or leave `auto` and Clipper will choose from the transcript and the frame:

- **story-skit** — dialogue and sketches. Wide 16:9 picture stays letterboxed in a 9:16 frame, with a static curiosity-gap hook on the top bar, word-by-word captions, a light warm grade, and a punch-in at the payoff. No speed ramps (they would break lipsync).
- **cinematic-edit** — letterboxed, moody/desaturated grade, hook on the bar, few or no captions.
- **sports-montage** — full 9:16 subject-tracked crop, high-contrast grade, ~1.5× on dead time and ~0.5× slow-mo for 1–2 seconds on the peak, punch-in, minimal captions.

Layout is picked automatically when you leave `--layout auto`: a tight 9:16 crop when the action is close or already vertical; a centered 16:9 picture with black bars (hook text sits on the bar) or a blurred fill when the source is wide.

The hook is a **static banner** in the top ~20% (bold white sans-serif, one or two keywords in yellow, an emoji is ok). It reframes the clip as a curiosity gap — “When developers forget it's just a game”, “This man is richer than billionaires” — and must stay true to the payoff. Clipper will not invent a promise the clip doesn't deliver. Suggested titles follow the same rule, including a “Don't check the sound” option only when the payoff is really on the soundtrack.

Each clip tries to **end on a calm frame** so it loops back to the start cleanly (`--no-loop` to keep the original out-point).

You can mix in a music bed with `--music /path/to/track.mp3`. Use a file you have the rights to, or a royalty-free track — Clipper does not bundle copyrighted music. Cuts can snap to detected beats; the bed sits under the original audio.

## License

MIT. Bundled fonts (Anton, Montserrat) are SIL Open Font License 1.1. The face-detection cascade is the standard OpenCV Haar cascade (Intel License). See `src/clipper/data/`.
