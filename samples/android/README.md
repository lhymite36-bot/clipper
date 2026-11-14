# Android pipeline sample

This folder holds a sample Short rendered by the same Kotlin pipeline the Android app uses (`android/pipeline`). The MP4 itself is not committed (it is large and regenerated in CI or locally).

```bash
cd android
./gradlew :pipeline:test
# then, with ffmpeg on PATH:
python3 ../scripts/render_android_sample.py
```

See `SOURCE.txt` for the source clip and licence.
