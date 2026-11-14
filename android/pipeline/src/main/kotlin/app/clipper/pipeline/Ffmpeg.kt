package app.clipper.pipeline

import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.TimeUnit

fun interface CommandRunner {
    fun run(args: List<String>, timeoutSec: Long): CommandResult
}

data class CommandResult(val exit: Int, val stdout: String, val stderr: String) {
    val ok: Boolean get() = exit == 0
}

/** Desktop / JVM ffmpeg runner. Android supplies its own via ffmpeg-kit. */
class ProcessRunner(
    private val ffmpeg: String = "ffmpeg",
    private val ffprobe: String = "ffprobe",
) : CommandRunner {
    override fun run(args: List<String>, timeoutSec: Long): CommandResult {
        val cmd = when (args.firstOrNull()) {
            "ffmpeg" -> listOf(ffmpeg) + args.drop(1)
            "ffprobe" -> listOf(ffprobe) + args.drop(1)
            else -> args
        }
        val pb = ProcessBuilder(cmd).redirectErrorStream(false)
        val proc = pb.start()
        val outT = proc.inputStream.bufferedReader()
        val errT = proc.errorStream.bufferedReader()
        val stdout = StringBuilder()
        val stderr = StringBuilder()
        val t1 = Thread { stdout.append(outT.readText()) }
        val t2 = Thread { stderr.append(errT.readText()) }
        t1.start(); t2.start()
        val finished = proc.waitFor(timeoutSec, TimeUnit.SECONDS)
        if (!finished) {
            proc.destroyForcibly()
            t1.join(1000); t2.join(1000)
            return CommandResult(124, stdout.toString(), stderr.toString() + "\ntimeout after ${timeoutSec}s")
        }
        t1.join(); t2.join()
        return CommandResult(proc.exitValue(), stdout.toString(), stderr.toString())
    }
}

class Ffmpeg(private val runner: CommandRunner) {
    var fontsDir: Path? = null

    fun probe(path: Path): Probe {
        val r = runner.run(
            listOf(
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration:stream=index,codec_type,width,height",
                "-of", "json", path.toString(),
            ),
            60,
        )
        if (!r.ok) error("ffprobe failed: ${r.stderr.take(400)}")
        val o = org.json.JSONObject(r.stdout)
        val duration = o.optJSONObject("format")?.optDouble("duration") ?: 0.0
        var w = 0
        var h = 0
        var hasAudio = false
        val streams = o.optJSONArray("streams") ?: org.json.JSONArray()
        for (i in 0 until streams.length()) {
            val s = streams.getJSONObject(i)
            when (s.optString("codec_type")) {
                "video" -> {
                    if (w == 0) {
                        w = s.optInt("width")
                        h = s.optInt("height")
                    }
                }
                "audio" -> hasAudio = true
            }
        }
        return Probe(duration, w, h, hasAudio)
    }

    fun extractWav(input: Path, output: Path, start: Double? = null, duration: Double? = null) {
        Files.createDirectories(output.parent)
        val args = mutableListOf("ffmpeg", "-y", "-hide_banner", "-loglevel", "error")
        if (start != null) args += listOf("-ss", start.toString())
        args += listOf("-i", input.toString())
        if (duration != null) args += listOf("-t", duration.toString())
        args += listOf("-ac", "1", "-ar", "16000", "-vn", output.toString())
        val r = runner.run(args, 300)
        if (!r.ok) error("wav extract failed: ${r.stderr.take(400)}")
    }

    fun loudnessPeaks(input: Path, everySec: Double = 0.5): List<Pair<Double, Double>> {
        val r = runner.run(
            listOf(
                "ffmpeg", "-hide_banner", "-i", input.toString(),
                "-af", "astats=metadata=1:reset=$everySec,ametadata=print:key=lavfi.astats.Overall.RMS_level",
                "-f", "null", "-",
            ),
            300,
        )
        val peaks = mutableListOf<Pair<Double, Double>>()
        val re = Regex("pts_time:([0-9.]+)")
        val reRms = Regex("Overall.RMS_level=([-0-9.]+)")
        val lines = (r.stderr + "\n" + r.stdout).lines()
        var t = 0.0
        for (line in lines) {
            re.find(line)?.let { t = it.groupValues[1].toDouble() }
            reRms.find(line)?.let {
                val rms = it.groupValues[1].toDouble()
                // louder (closer to 0) scores higher
                val score = ((rms + 60.0) / 60.0).coerceIn(0.0, 1.5)
                peaks += t to score
            }
        }
        return peaks
    }

    fun renderClip(
        spec: ClipSpec,
        assPath: Path,
        output: Path,
        videoCodec: String = "libx264",
        audioCodec: String = "aac",
    ) {
        Files.createDirectories(output.parent)
        val music = spec.musicPath != null
        val filter = LayoutVt.clipFilter(
            layout = spec.layout,
            width = spec.width,
            height = spec.height,
            hookBar = true,
            includeAudio = true,
            music = music,
            sfx = false,
        )
        val vf = filter.replace("[vout]", "[vbase]") + ";[vbase]${assFilter(assPath)}[vout]"
        val args = mutableListOf(
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", spec.moment.start.toString(),
            "-t", spec.moment.duration.toString(),
            "-i", spec.sourcePath.toString(),
        )
        if (music) args += listOf("-i", spec.musicPath!!.toString())
        args += listOf("-filter_complex", vf, "-map", "[vout]", "-map", "[aout]")
        args += videoArgs(videoCodec)
        args += listOf("-c:a", audioCodec, "-b:a", "192k", "-movflags", "+faststart", "-pix_fmt", "yuv420p", output.toString())
        val r = runner.run(args, 900)
        if (!r.ok) error("render failed: ${r.stderr.take(800)}")
    }

    private fun assFilter(assPath: Path): String {
        val assEsc = assPath.toAbsolutePath().toString().replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        val font = fontsDir?.let {
            val d = it.toAbsolutePath().toString().replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
            ":fontsdir='$d'"
        } ?: ""
        return "ass='$assEsc'$font"
    }

    private fun videoArgs(videoCodec: String): List<String> =
        if (videoCodec.contains("mediacodec")) listOf("-c:v", videoCodec, "-b:v", "5M")
        else listOf("-c:v", videoCodec, "-preset", "veryfast", "-crf", "20")

    fun renderRecap(
        spec: RecapSpec,
        assPath: Path,
        concatFile: Path,
        output: Path,
        videoCodec: String = "libx264",
        audioCodec: String = "aac",
    ) {
        Files.createDirectories(output.parent)
        val music = spec.musicPath != null
        val filter = LayoutVt.recapFilter(spec.isShort, spec.width, spec.height, music)
            .replace("[vout]", "[vbase]") + ";[vbase]${assFilter(assPath)}[vout]"
        val args = mutableListOf(
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", concatFile.toString(),
            "-i", spec.voiceoverPath.toString(),
        )
        if (music) args += listOf("-i", spec.musicPath!!.toString())
        args += listOf("-filter_complex", filter, "-map", "[vout]", "-map", "[aout]")
        args += videoArgs(videoCodec)
        args += listOf("-c:a", audioCodec, "-b:a", "192k", "-shortest", "-movflags", "+faststart", "-pix_fmt", "yuv420p", output.toString())
        val r = runner.run(args, 1800)
        if (!r.ok) error("recap render failed: ${r.stderr.take(800)}")
    }
}
