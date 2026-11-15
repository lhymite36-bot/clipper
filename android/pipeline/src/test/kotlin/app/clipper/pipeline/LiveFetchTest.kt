package app.clipper.pipeline

import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable
import java.nio.file.Files

/** Real-network check. Run with LIVE_FETCH=1 (optionally LIVE_URLS="url1 url2"). Skipped in CI. */
@EnabledIfEnvironmentVariable(named = "LIVE_FETCH", matches = "1")
class LiveFetchTest {
    @Test
    fun downloadsRealVideos() {
        val urls = (System.getenv("LIVE_URLS") ?: "https://youtu.be/9bZkp7q19f0 https://www.youtube.com/shorts/jNQXAC9IVRw").split(' ').filter { it.isNotBlank() }
        val dir = Files.createTempDirectory("live")
        val muxer: (java.nio.file.Path, java.nio.file.Path, java.nio.file.Path) -> Unit = { v, a, out ->
            val p = ProcessBuilder("ffmpeg", "-y", "-loglevel", "error", "-i", v.toString(), "-i", a.toString(), "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-movflags", "+faststart", out.toString())
                .inheritIO().start()
            check(p.waitFor() == 0) { "ffmpeg mux failed" }
        }
        for (u in urls) {
            var last = -1
            val real = UrlConnectionHttp()
            val http: Http = if (System.getenv("LIVE_SKIP_YT") == "1") object : Http by real {
                override fun post(url: String, json: String, headers: Map<String, String>, timeoutMs: Int) = Http.Resp(503, "")
            } else real
            val f = VideoFetcher(http = http, cacheDir = dir, muxer = muxer, log = { println("[log] $it") }, progress = { p -> if (p != null && p / 25 != last / 25) { last = p; println("[progress] $p%") } })
            val r = runCatching { f.fetch(u, dir.resolve("dl")) }
            r.onSuccess { println("OK $u -> ${it.path} ${Files.size(it.path)} bytes via ${it.via} title=${it.title}") }
            r.onFailure { println("FAIL $u: ${it.message}"); (it as? FetchFailed)?.attempts?.forEach { a -> println("   - $a") } }
            assertTrue(r.isSuccess, "download failed for $u")
        }
    }
}
