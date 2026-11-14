package app.clipper.pipeline

import java.nio.file.Files
import java.nio.file.Path
import java.time.Instant

/**
 * Shared clip + recap orchestration used by the Android app, JVM tests, and the
 * desktop sample renderer. Android swaps in ffmpeg-kit and youtubedl runners.
 */
class Pipeline(
    private val ffmpeg: Ffmpeg,
    private val workRoot: Path,
    private val queue: QueueStore,
    private val transcriber: Transcriber? = null,
    var settings: Settings = Settings(),
    var videoCodec: String = "libx264",
    var audioCodec: String = "aac",
) {
    fun clipFile(
        source: Path,
        transcript: Transcript? = null,
        count: Int = 1,
        sourceUrl: String? = null,
        sourceLabel: String? = null,
        license: String? = null,
        foundBy: String? = null,
        onProgress: (String) -> Unit = {},
    ): List<QueueItem> {
        onProgress("Probing source")
        val probe = ffmpeg.probe(source)
        val text = transcript ?: run {
            if (transcriber == null) Transcript()
            else {
                onProgress("Transcribing")
                val wav = workRoot.resolve("audio/${source.fileName}.wav")
                ffmpeg.extractWav(source, wav)
                transcriber.transcribe(wav)
            }
        }
        onProgress("Picking moments")
        val peaks = runCatching { ffmpeg.loudnessPeaks(source) }.getOrDefault(emptyList())
        val moments = Moments.pick(text, probe.duration, count = count, peaks = peaks)
        val items = mutableListOf<QueueItem>()
        val music = workRoot.resolve("music/bed.wav")
        if (!Files.exists(music)) Music.generateBed(music)
        moments.forEachIndexed { i, moment ->
            onProgress("Rendering clip ${i + 1}/${moments.size}")
            val slice = text.slice(moment.start, moment.end)
            val events = Captions.eventsFromWords(slice, moment.start, moment.end)
            val hook = moment.hook.ifBlank { Metadata.hookFrom(text.textIn(moment.start, moment.end)) }
            val title = Metadata.titleFrom(hook, text.textIn(moment.start, moment.end))
            val tags = Metadata.hashtags(text.textIn(moment.start, moment.end))
            val desc = Metadata.description(title, hook, tags, sourceUrl, license)
            val jobDir = workRoot.resolve("jobs/clip-${Instant.now().toEpochMilli()}-$i")
            Files.createDirectories(jobDir)
            val ass = jobDir.resolve("captions.ass")
            Files.writeString(ass, Captions.assForClip(events, hook = hook))
            val out = jobDir.resolve("clip.mp4")
            ffmpeg.renderClip(
                ClipSpec(source, moment, settings.layout, musicPath = music),
                ass, out, videoCodec = videoCodec, audioCodec = audioCodec,
            )
            items += queue.enqueue(
                path = out,
                title = title,
                description = desc,
                tags = tags,
                hook = hook,
                kind = JobKind.CLIP,
                sourceUrl = sourceUrl,
                sourceLabel = sourceLabel,
                license = license,
                foundBy = foundBy,
                durationSec = moment.duration,
                autopilot = settings.autopilot,
            )
        }
        return items
    }

    fun recapFile(
        source: Path,
        kind: JobKind,
        title: String,
        transcript: Transcript? = null,
        voiceover: Path,
        sourceUrl: String? = null,
        sourceLabel: String? = null,
        license: String? = null,
        foundBy: String? = null,
        onProgress: (String) -> Unit = {},
    ): QueueItem {
        onProgress("Probing source")
        val probe = ffmpeg.probe(source)
        val script = RecapScript.heuristic(title, transcript?.text ?: "", kind)
        onProgress("Aligning shots")
        val audioProbe = ffmpeg.probe(voiceover)
        val shots = Scenes.pack(audioProbe.duration, probe.duration)
        val width = if (kind == JobKind.RECAP_SHORT) 1080 else 1920
        val height = if (kind == JobKind.RECAP_SHORT) 1920 else 1080
        val events = Captions.eventsFromScript(script, audioProbe.duration)
        val hook = Metadata.hookFrom(script)
        val jobDir = workRoot.resolve("jobs/recap-${Instant.now().toEpochMilli()}")
        Files.createDirectories(jobDir)
        val concat = RecapConcat.write(shots, source, jobDir.resolve("shots"), ffmpeg)
        val ass = jobDir.resolve("captions.ass")
        Files.writeString(
            ass,
            Captions.assForRecap(events, width, height, hook, isShort = kind == JobKind.RECAP_SHORT),
        )
        val music = workRoot.resolve("music/bed.wav")
        if (!Files.exists(music)) Music.generateBed(music, seconds = audioProbe.duration.coerceAtLeast(8.0))
        val out = jobDir.resolve(if (kind == JobKind.RECAP_SHORT) "recap-short.mp4" else "recap-long.mp4")
        onProgress("Rendering recap")
        ffmpeg.renderRecap(
            RecapSpec(
                sourcePath = source,
                kind = kind,
                title = title,
                scriptText = script,
                voiceoverPath = voiceover,
                captions = events,
                shots = shots,
                musicPath = music,
                width = width,
                height = height,
            ),
            ass, concat, out, videoCodec = videoCodec, audioCodec = audioCodec,
        )
        val tags = Metadata.hashtags(script, extra = listOf("recap", "movie"))
        val desc = Metadata.description(title, hook, tags, sourceUrl, license) +
            "\n\nContent ID can still claim this recap even when you use an original voice and music."
        return queue.enqueue(
            path = out,
            title = title,
            description = desc,
            tags = tags,
            hook = hook,
            kind = kind,
            sourceUrl = sourceUrl,
            sourceLabel = sourceLabel,
            license = license,
            foundBy = foundBy,
            durationSec = audioProbe.duration,
            autopilot = settings.autopilot,
        )
    }
}
