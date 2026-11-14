# Clipper for Android

A native Kotlin app that brings Clipper’s v1.1.0 Shorts clipping and v1.2.0 Movie Recap to a phone — including a Samsung Galaxy A05. The clipping / recap / Auto-find logic lives in the `pipeline` module so the same code can be tested on a desktop JVM.

This is a **pre-release**. It is not on `main` and must never be marked as GitHub’s Latest release.

## What it does

- Paste a YouTube URL, share a video into the app, or pick a file
- Auto-picks hook moments, captions them in 9:16 (1080×1920, fill layout, Anton hook + Montserrat body), and mixes a copyright-safe generated music bed (never a YouTube audio rip)
- Movie Recap: Short (vertical, hook bar) and Long (16:9). One narrator, scene-matched 2–5s shots, word captions, music ducking. Content ID can still claim a recap; Clipper does not flip, speed-shift, or hide a film
- Review queue is draft-only. Nothing posts unless you turn Autopilot on
- **Auto-find** pulls videos by itself:
  - Watched YouTube channels, playlists, and campaign/brief links (Content Rewards, Vyro, Clipster, IndClip-style)
  - Keyword / trending search via yt-dlp, with an optional Creative Commons-only filter
  - Movie trailers by title for Recap mode
  - New items are queued, auto-clipped or recapped, and land in the review queue
  - WorkManager periodic job with optional Wi-Fi-only and charging-only constraints
  - Already-processed videos are deduped; a daily cap is enforced
  - Each queue item shows its source and licence
- API keys (Gemini, Groq, Buffer, GitHub) are entered in Settings and stored in EncryptedSharedPreferences. Values are never logged

## What is limited on a Samsung A05 (~4 GB RAM)

- Full quality is the default (1080×1920, fill layout, the same hook / caption style as desktop). Features are not held back because the phone is budget hardware
- Transcription: when a Groq key is set, the app uses Groq Whisper (recommended). There is no bundled whisper.cpp model in the APK (it would bloat the download and can OOM). Without a key, clips still run using loudness peaks and hook-word heuristics, and you can pick a local file if a YouTube download is blocked
- Recap voice: on-device Android text-to-speech (one voice per recap) when no cloud TTS is used
- Long recaps and Auto-find downloads run as a foreground service / WorkManager job so Android is less likely to kill them. A very long recap can still take a while and needs free storage
- The release APK is **arm64-v8a** only (the A05 is 64-bit). 32-bit phones are not supported
- Encoding uses the phone’s H.264 hardware encoder (`h264_mediacodec`) through a maintained FFmpeg Kit build
- Buffer / YouTube autopost from the phone needs keys in Settings; start with the draft queue

## Install (plain words)

1. Open the GitHub **pre-release** `android-v1.2.0` on a computer or the phone
2. Download `Clipper-1.2.0.apk`
3. On the phone, allow install from the browser / Files app if Android asks
4. Open Clipper. In Settings, optionally paste a free Groq (and/or Gemini, Buffer, GitHub) key. The app hides the value after you save
5. On the Clip tab, paste a YouTube link or pick a video, then wait for the notification to finish. Review the result in the Queue tab
6. To let Clipper pull videos itself, add sources on the Sources tab, set a daily cap and Wi-Fi/charging options, and enable the Auto-find schedule. New drafts still wait in the queue

Build it yourself: open this `android/` folder in Android Studio, or run `./gradlew :app:assembleRelease` (a debug key is used if no release keystore is in the environment). CI signs the official APK with the repo’s existing keystore secrets and never prints them.

Desktop Clipper also gained `clipper find` (same Auto-find sources, Creative Commons filter, trailer search, dedupe, daily cap, and draft-only queue). In the web UI, use the Auto-find sources card.
