package app.clipper.pipeline

import java.nio.file.Files
import java.nio.file.Path

object RenderSample {
    @JvmStatic
    fun main(args: Array<String>) {
        val source = Path.of(prop("sampleSource") ?: arg(args, 0) ?: error("sampleSource required"))
        val out = Path.of(prop("sampleOut") ?: arg(args, 1) ?: "samples/android/01-android-pipeline.mp4")
        val fonts = prop("sampleFonts")?.let { Path.of(it) }
        val work = Path.of(prop("sampleWork") ?: "/tmp/clipper-android-sample")
        val transcriptPath = prop("sampleTranscript")?.let { Path.of(it) }
        Files.createDirectories(work)
        Files.createDirectories(out.parent)
        val runner = ProcessRunner()
        val ffmpeg = Ffmpeg(runner)
        ffmpeg.fontsDir = fonts
        val queue = QueueStore(work.resolve("queue.json"))
        val pipeline = Pipeline(ffmpeg, work, queue)
        val transcript = when {
            transcriptPath != null && Files.exists(transcriptPath) -> TranscriptIO.load(transcriptPath)
            else -> null
        }
        val items = pipeline.clipFile(
            source,
            transcript = transcript,
            count = 1,
            sourceUrl = prop("sampleUrl"),
            sourceLabel = prop("sampleLabel") ?: "Sample",
            license = prop("sampleLicense") ?: "unknown",
            foundBy = "sample",
        )
        if (items.isEmpty()) error("pipeline produced no clips")
        val produced = Path.of(items.first().path)
        Files.copy(produced, out, java.nio.file.StandardCopyOption.REPLACE_EXISTING)
        val sidecar = out.resolveSibling(out.fileName.toString().removeSuffix(".mp4") + ".json")
        Files.writeString(sidecar, items.first().toJson().toString(2))
        println("Wrote $out (${Files.size(out)} bytes)")
        println("title=${items.first().title}")
        println("hook=${items.first().hook}")
        println("license=${items.first().license}")
    }

    private fun prop(name: String): String? = System.getProperty(name)?.takeIf { it.isNotBlank() }
        ?: System.getenv(name)?.takeIf { it.isNotBlank() }

    private fun arg(args: Array<String>, i: Int): String? = args.getOrNull(i)
}
