package app.clipper.pipeline

/** Package-visible hook so RecapConcat can run raw ffmpeg through the same runner. */
internal object FfmpegAccess {
    private val runnerField = Ffmpeg::class.java.getDeclaredField("runner").apply { isAccessible = true }

    fun run(ffmpeg: Ffmpeg, args: List<String>, timeoutSec: Long = 300): CommandResult {
        val runner = runnerField.get(ffmpeg) as CommandRunner
        val r = runner.run(args, timeoutSec)
        if (!r.ok) error("ffmpeg failed (${r.exit}): ${r.stderr.take(600)}")
        return r
    }
}
