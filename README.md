# Clipper

Turn a long YouTube video (or a file on your PC) into vertical YouTube Shorts.

Clipper runs **entirely on your computer**. It uses free tools only: `yt-dlp`, local [faster-whisper](https://github.com/SYSTRAN/faster-whisper), optional Gemini / Groq free keys, and a loudness / laughter / keyword fallback when no key is set. There are no paid APIs and nothing is billed.

For each clip it:

1. Downloads the video (or uses your file)
2. Transcribes it locally with word-level timestamps
3. Picks the top N viral moments (15–60 seconds)
4. Reframes to **9:16 1080×1920** (fill layout for 16:9, tight crop, letterbox bars, or blur)
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

1. Open the [releases page](https://github.com/lhymite36-bot/clipper/releases) and pick the build you want (v1.1.0 is a pre-release).
2. Download **Clipper-Setup.exe** and run it. No admin account is required; it installs into your user folder.
3. Open **Clipper** from the Start menu (web UI) or **Clipper (Terminal)** for the command line.
4. The first run downloads the Whisper **small** speech model (~500 MB, one time; you can switch to `base` or `tiny` in settings). FFmpeg is bundled.

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
| `--model` | Whisper size: `tiny`, `base`, `small`, `medium`, `large-v3` | `small` |
| `--hook` | Hook text on every clip. If omitted, one is written per clip | auto |
| `--preset` | Look: `auto`, `cinematic-edit`, `story-skit`, `sports-montage` | `auto` |
| `--layout` | `auto`, `fill` (blur background + sharp 16:9 under the hook), `tight`, `bars`, `blur` | `auto` |
| `--grade` | `auto`, `none`, `moody`, `contrast`, `warm` | `auto` |
| `--style` | Crop hint when the layout is tight: `auto`, `face`, `center`, `blur` | `auto` |
| `--captions` | `auto` (words for speech, none for montages), `words`, `minimal`, `none` | `auto` |
| `--language` | Whisper language, or `auto` (re-runs in English if Latin-heavy audio was misdetected) | `auto` |
| `--brief` | Campaign brief text or file (source, duration, hook rules, geo) | unset |
| `--music` | Optional copyright-safe music bed (a local file you have rights to) | unset |
| `--music-dir` / `--sounds-dir` | Folders of YouTube Audio Library / CC0 / CC-BY tracks, or audio you have rights to | user library |
| `--auto-music` / `--no-music` | Auto-pick a copyright-safe or original bed, ducked under speech | on |
| `--sfx` / `--no-sfx` | Stock whoosh / riser / impact at the hook and payoff | on |
| `--enqueue` / `--no-enqueue` | Add clips to the review queue | on |
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

Get a free Gemini key at [Google AI Studio](https://aistudio.google.com/apikey), or a free Groq key at [console.groq.com](https://console.groq.com/keys). If the model is busy or the key is missing, Clipper falls back to loudness, laughter and keyword scoring on your PC. Keys are read from `.env` and **never printed** in logs or the UI.

On Windows you can also save that `.env` at `%LOCALAPPDATA%\Clipper\.env`. On Linux/macOS: `~/.config/clipper/.env`.

### Campaign briefs

Paste a brief in the UI or pass `--brief brief.txt` / `--brief "Duration: 15-30s\nGeo: US, UK\nHook: curiosity question"`. Clipper reads the source URL, clip count, duration window, hook rules, language, preset, and target regions, and puts the regions in the description.

### Music and sound (copyright-safe only)

Clipper **does not download or rip music or sounds from YouTube videos**. Background music comes from, in order:

1. A file you pass with `--music`
2. Your library folders (`%LOCALAPPDATA%\Clipper\music`, `sounds`, and `my-sounds` — drop YouTube Audio Library, CC0, or CC-BY tracks you have the rights to)
3. An original bed Clipper generates on your machine

The bed is ducked under speech. Credits are added to the description automatically. Stock whoosh / riser / impact effects (original, generated) hit at the hook and the payoff. The sports-montage preset also snaps cut points to a beat grid.

### YouTube auto-posting (review first)

New clips go into a **review queue**. Draft-only is **on** and autopilot is **off** until you change settings, so nothing publishes by itself.

```text
clipper queue
clipper approve <id>
clipper reject <id>
clipper publish --draft
```

The default path is **Buffer**, the same idea as Quiet Brain / Voice to Short: a Buffer API key plus a **public HTTPS URL** for the MP4 (Clipper can upload the file to a public GitHub repo such as `lhymite36-bot/qb-media` or a `clipper-autopost-media` prerelease). You can also use the YouTube Data API as an optional upload path (private/draft by default).

Add to `.env` (never commit these):

```text
BUFFER_API_KEY=
CLIPPER_GITHUB_TOKEN=
# Optional direct YouTube upload:
# YOUTUBE_CLIENT_ID=
# YOUTUBE_CLIENT_SECRET=
# YOUTUBE_REFRESH_TOKEN=
```

In the UI (`clipper --ui`) set the Buffer YouTube channel id, the public GitHub repo, schedule times (Asia/Calcutta), and posts per day. Load channels once the Buffer key is in `.env`. Turn **Draft only** off and **Autopilot** on only when you are ready for clips to go out after you approve them. Buffer's free plan typically holds 10 scheduled posts.

## How moment picking works without a key

Clipper only keeps a clip when it can find a real payoff: a punchline, a laugh or reaction in the transcript, a loud spike, a scene change, or an action beat. It starts a little before the setup and **ends 2–4 seconds after that payoff**, so the peak sits in the last 30% of the clip. If it cannot find that many payoffs, it returns fewer clips rather than padding the count with dead air.

Hooks are written from words that were actually spoken (or left off when there is no speech). It will not put a generic “WAIT FOR IT” on screen unless that phrase is in the transcript *and* a verified payoff lands in the last 30% of the clip.

A short punch-in zoom hits at the payoff (disable with `--no-punch`).

### Style presets

Pick a look with `--preset`, or leave `auto` and Clipper will choose from the transcript and the frame:

- **story-skit** — dialogue and sketches. Wide 16:9 is placed under a compact hook bar with a blurred 9:16 fill so more of the frame is used, word-by-word captions, a light warm grade, and a punch-in at the payoff. No speed ramps (they would break lipsync).
- **cinematic-edit** — letterboxed, moody/desaturated grade, hook on the bar, few or no captions.
- **sports-montage** — full 9:16 subject-tracked crop, high-contrast grade, ~1.5× on dead time and ~0.5× slow-mo for 1–2 seconds on the peak, punch-in, minimal captions.

Layout is picked automatically when you leave `--layout auto`: a tight 9:16 crop when the action is close or already vertical; for wide 16:9, a **fill** layout (blurred background, sharp 16:9 picture under the hook bar) so the frame isn't mostly black. `bars` is still available if you want a letterbox.

The hook is a **static banner** in the top ~20% (bold white sans-serif, one or two keywords in yellow, an emoji is ok). It reframes the clip as a curiosity gap — “When developers forget it's just a game”, “This man is richer than billionaires” — and must stay true to the payoff. Clipper will not invent a promise the clip doesn't deliver. Suggested titles follow the same rule, including a “Don't check the sound” option only when the payoff is really on the soundtrack.

Each clip tries to **end on a calm frame** and then freezes that last frame for a beat so it loops back to the start cleanly (`--no-loop` to keep the original out-point).

See **Music and sound** above for copyright-safe beds. Do not rip audio from YouTube videos — that risks Content ID claims.

## Movie recaps

`clipper recap` (also installed as `recapper`) turns a film or trailer you have the rights to use into a voiceover recap, in the style of popular YouTube recap channels.

```text
clipper recap movie.mp4 --title "Sintel" --format short --out recap
clipper recap movie.mp4 --title "Sintel" --format long --target-seconds 150
```

| Flag | Meaning | Default |
| --- | --- | --- |
| `--title` | Movie title (required) | |
| `--format` | `short` (45–60s, 9:16) or `long` (16:9, 8–15 min) | `short` |
| `--target-seconds` | Override length (use `150` for a ~2.5 min demo) | |
| `--voice` | Gemini TTS or an edge-tts neural voice (`--list-voices`) | Andrew / Fenrir |
| `--spoilers` / `--no-spoilers` | Reveal the ending, or keep it hidden | on for long, off for short |
| `--subs` | `.srt` subtitles (used instead of a fresh transcription) | |
| `--plot` | Optional plot notes (text file) | |
| `--music` | User-supplied or royalty-free bed only | unset |
| `--grade` | `moody`, `contrast`, `warm`, `none` | `moody` |

The pipeline writes a gripping hook-and-story script with a free Gemini/Groq key (or a local fallback), narrates it with Gemini TTS when the free tier allows and otherwise an edge-tts neural voice, then matches each sentence to a short 2–5 s shot using the transcript plus PySceneDetect. Original audio is ducked under the voice. Cuts, a slight zoom, optional mirror, a colour grade and a 1.05× playback rate are applied as a transformative edit — this reduces (it does **not** guarantee the absence of) Content ID claims.

Shorts get a blurred 9:16 frame, a top hook bar, and word-by-word captions. Long recaps are 16:9 and include a chapter list in the sidecar. If you omit the film (or a shot fails), Clipper falls back to illustrated stills / stick-figure scenes.

Each run writes an MP4 plus a `.txt` sidecar with title, description (including a commentary/review note and credit), tags, and chapters.

Only recap content you have the rights to use. Public-domain and Creative Commons films are the safe test case.


## License

MIT. Bundled fonts (Anton, Montserrat) are SIL Open Font License 1.1. The face-detection cascade is the standard OpenCV Haar cascade (Intel License). See `src/clipper/data/`.
