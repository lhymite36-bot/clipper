package app.clipper.pipeline

import java.nio.file.Files
import java.nio.file.Path

object RecapScript {
    fun heuristic(title: String, transcript: String, kind: JobKind): String {
        val short = kind == JobKind.RECAP_SHORT
        val wordsTarget = if (short) 130 else 1200
        val hook = "Here's what happens in $title — no spoilers up front."
        val bodySrc = transcript.ifBlank { title }.replace(Regex("\\s+"), " ").trim()
        val sentences = bodySrc.split(Regex("(?<=[.!?])\\s+")).filter { it.isNotBlank() }
        val chunks = if (sentences.isNotEmpty()) sentences else listOf(bodySrc)
        val sb = StringBuilder(hook)
        var i = 0
        while (sb.toString().split(Regex("\\s+")).size < wordsTarget) {
            val piece = chunks[i % chunks.size].trim()
            if (piece.isNotBlank()) {
                sb.append(' ')
                sb.append(if (piece.endsWith('.') || piece.endsWith('!') || piece.endsWith('?')) piece else "$piece.")
            }
            i++
            if (i > wordsTarget * 2) break
        }
        val words = sb.toString().split(Regex("\\s+")).filter { it.isNotBlank() }
        val cut = words.take(wordsTarget).joinToString(" ")
        return cut.trim()
    }

    fun wordTarget(kind: JobKind): Int = if (kind == JobKind.RECAP_SHORT) 130 else 1200
}

object Scenes {
    const val MIN_SHOT = 2.0
    const val MAX_SHOT = 5.0

    /** Evenly pack 2–5s shots covering [0, audioDur], mapped onto the source duration. */
    fun pack(audioDur: Double, sourceDur: Double, sceneCuts: List<Double> = emptyList()): List<Shot> {
        if (audioDur <= 0 || sourceDur <= 0) return emptyList()
        val shots = mutableListOf<Shot>()
        var t = 0.0
        val cuts = (sceneCuts + sourceDur).distinct().sorted()
        var srcCursor = 0.0
        var cutIdx = 0
        while (t < audioDur - 0.05) {
            val remain = audioDur - t
            val len = when {
                remain <= MAX_SHOT && remain >= MIN_SHOT -> remain
                remain < MIN_SHOT && shots.isNotEmpty() -> {
                    // fold remainder into last shot
                    val last = shots.removeAt(shots.lastIndex)
                    shots += last.copy(end = last.end + remain)
                    break
                }
                else -> MIN_SHOT + (MAX_SHOT - MIN_SHOT) * 0.5
            }.coerceAtMost(remain)
            // advance source: prefer next scene cut if within window, else walk sequentially
            while (cutIdx < cuts.size && cuts[cutIdx] <= srcCursor + 0.05) cutIdx++
            val srcStart = srcCursor.coerceIn(0.0, (sourceDur - MIN_SHOT).coerceAtLeast(0.0))
            val srcEndCandidate = if (cutIdx < cuts.size) cuts[cutIdx] else srcStart + len
            val srcLen = (srcEndCandidate - srcStart).coerceIn(MIN_SHOT, MAX_SHOT)
            shots += Shot(t, t + len, srcStart, fallback = false)
            t += len
            srcCursor = (srcStart + srcLen) % maxOf(sourceDur, 0.1)
        }
        return shots.filter { it.end > it.start + 0.05 }
    }
}

object RecapConcat {
    fun write(shots: List<Shot>, source: Path, work: Path, ffmpeg: Ffmpeg, fallbackStill: Path? = null): Path {
        Files.createDirectories(work)
        val list = work.resolve("concat.txt")
        val lines = mutableListOf<String>()
        shots.forEachIndexed { i, shot ->
            val clip = work.resolve("shot-%03d.ts".format(i))
            val dur = shot.end - shot.start
            // Re-encode each shot to a common mpegts so concat is reliable
            val args = if (shot.fallback && fallbackStill != null) {
                listOf(
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-loop", "1", "-i", fallbackStill.toString(),
                    "-t", dur.toString(),
                    "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,format=yuv420p",
                    "-c:v", "libx264", "-preset", "veryfast", "-an",
                    clip.toString(),
                )
            } else {
                listOf(
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", shot.sourceStart.toString(),
                    "-t", dur.toString(),
                    "-i", source.toString(),
                    "-vf", "fps=30,scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,format=yuv420p",
                    "-c:v", "libx264", "-preset", "veryfast", "-an",
                    clip.toString(),
                )
            }
            // Use runner through a tiny helper: we expose via Ffmpeg.render by shelling here? 
            // Store requested command on a side channel — see runVia.
            runVia(ffmpeg, args)
            lines += "file '${clip.toAbsolutePath().toString().replace("'", "'\\''")}'"
        }
        Files.writeString(list, lines.joinToString("\n") + "\n")
        return list
    }

    private fun runVia(ffmpeg: Ffmpeg, args: List<String>) {
        // Reach the runner with a package-visible hook.
        FfmpegAccess.run(ffmpeg, args)
    }
}
