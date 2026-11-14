package app.clipper.android.data

import android.content.Context
import app.clipper.pipeline.CommandResult
import app.clipper.pipeline.CommandRunner
import com.arthenica.ffmpegkit.FFmpegKit
import com.arthenica.ffmpegkit.FFprobeKit
import org.json.JSONObject
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.nio.file.Path
import javax.net.ssl.HttpsURLConnection

class FfmpegKitRunner : CommandRunner {
    override fun run(args: List<String>, timeoutSec: Long): CommandResult {
        val rest = when (args.firstOrNull()) {
            "ffmpeg", "ffprobe" -> args.drop(1)
            else -> args
        }.toTypedArray()
        return if (args.firstOrNull() == "ffprobe") {
            val s = FFprobeKit.executeWithArguments(rest)
            CommandResult(s.returnCode.value, s.output ?: "", s.failStackTrace ?: "")
        } else {
            val s = FFmpegKit.executeWithArguments(rest)
            CommandResult(s.returnCode.value, s.output ?: "", s.failStackTrace ?: "")
        }
    }
}

/**
 * URL / search client that does not depend on a JitPack yt-dlp wrapper.
 * Channels and playlists use YouTube's public Atom RSS. Keyword / trailer
 * search and file downloads use public Piped / Invidious JSON APIs, with
 * instance fallbacks. If every instance is blocked, the user can still share
 * or pick a file.
 */
class YoutubeDlRunner(@Suppress("UNUSED_PARAMETER") context: Context) {
    private val piped = listOf(
        "https://pipedapi.kavin.rocks",
        "https://pipedapi.adminforge.de",
        "https://api.piped.private.coffee",
    )
    private val invidious = listOf(
        "https://inv.nadeko.net",
        "https://yewtu.be",
        "https://invidious.fdn.fr",
    )

    fun download(url: String, destDir: Path): Path {
        destDir.toFile().mkdirs()
        val id = videoId(url) ?: error("Need a YouTube watch URL, or pick the file instead.")
        val stream = streamUrl(id) ?: error("Could not get a download URL. Share or pick the video file instead.")
        val dest = destDir.resolve("$id.mp4")
        httpDownload(stream, dest.toFile())
        if (!dest.toFile().exists() || dest.toFile().length() < 1000) {
            error("Download was empty. Try picking the file instead.")
        }
        return dest
    }

    fun dumpJson(query: String, extra: List<String> = emptyList()): String {
        val ccOnly = extra.any { it.contains("Creative Commons", true) }
        return when {
            query.startsWith("ytsearch") -> search(query.substringAfter(":"), ccOnly)
            query.contains("list=") || query.contains("/playlist") -> playlist(query)
            query.contains("/@") || query.contains("/channel/") || query.contains("channel_id=") -> channel(query)
            query.startsWith("http") -> listOfNotNull(videoMeta(query)).joinToString("\n")
            else -> search(query, ccOnly)
        }
    }

    fun asCommandRunner(): CommandRunner = CommandRunner { args, _ ->
        val isYtdlp = args.firstOrNull()?.contains("yt-dlp") == true || args.firstOrNull() == "yt-dlp"
        if (!isYtdlp) return@CommandRunner FfmpegKitRunner().run(args, 300)
        val query = args.last()
        val extra = args.drop(1).dropLast(1)
        val out = runCatching { dumpJson(query, extra) }.getOrDefault("")
        CommandResult(if (out.isBlank()) 1 else 0, out, "")
    }

    private fun search(raw: String, ccOnly: Boolean): String {
        var q = raw.removePrefix("ytsearch10:").removePrefix("ytsearch5:").removePrefix("ytsearch:")
        if (ccOnly && !q.contains("creativecommons", true)) q = "creativecommons $q"
        val encoded = URLEncoder.encode(q, "UTF-8")
        for (base in piped) {
            val body = getOrNull("$base/search?q=$encoded&filter=videos") ?: continue
            val arr = runCatching { org.json.JSONArray(body) }.getOrNull()
                ?: runCatching { JSONObject(body).optJSONArray("items") }.getOrNull()
                ?: continue
            val lines = mutableListOf<String>()
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                val type = o.optString("type")
                if (type.isNotBlank() && type != "video" && type != "stream") continue
                val id = o.optString("url").substringAfter("/watch?v=").substringAfter("/shorts/")
                    .ifBlank { o.optString("id") }.ifBlank { o.optString("videoId") }
                if (id.isBlank()) continue
                lines += JSONObject()
                    .put("id", id)
                    .put("title", o.optString("title"))
                    .put("webpage_url", "https://www.youtube.com/watch?v=$id")
                    .put("license", if (ccOnly) "Creative Commons" else "unknown")
                    .put("channel", o.optString("uploaderName").ifBlank { o.optString("uploader") })
                    .put("duration", o.optLong("duration"))
                    .toString()
                if (lines.size >= 10) break
            }
            if (lines.isNotEmpty()) return lines.joinToString("\n")
        }
        return ""
    }

    private fun channel(url: String): String {
        val id = channelId(url) ?: return search(url, false)
        return rss("https://www.youtube.com/feeds/videos.xml?channel_id=$id")
    }

    private fun playlist(url: String): String {
        val id = Regex("list=([A-Za-z0-9_-]+)").find(url)?.groupValues?.get(1)
            ?: return search(url, false)
        return rss("https://www.youtube.com/feeds/videos.xml?playlist_id=$id")
    }

    private fun rss(feed: String): String {
        val xml = getOrNull(feed) ?: return ""
        val blocks = Regex("<entry>([\\s\\S]*?)</entry>").findAll(xml).toList()
        val lines = mutableListOf<String>()
        for (b in blocks.take(10)) {
            val e = b.groupValues[1]
            val id = Regex("yt:videoId>([^<]+)").find(e)?.groupValues?.get(1) ?: continue
            val title = Regex("<title>([^<]+)").find(e)?.groupValues?.get(1) ?: id
            val author = Regex("<name>([^<]+)").find(e)?.groupValues?.get(1) ?: ""
            lines += JSONObject()
                .put("id", id)
                .put("title", unescape(title))
                .put("webpage_url", "https://www.youtube.com/watch?v=$id")
                .put("license", "unknown")
                .put("channel", unescape(author))
                .toString()
        }
        return lines.joinToString("\n")
    }

    private fun videoMeta(url: String): String? {
        val id = videoId(url) ?: return null
        return JSONObject()
            .put("id", id)
            .put("title", id)
            .put("webpage_url", "https://www.youtube.com/watch?v=$id")
            .put("license", "unknown")
            .toString()
    }

    private fun streamUrl(id: String): String? {
        for (base in piped) {
            val body = getOrNull("$base/streams/$id") ?: continue
            val o = runCatching { JSONObject(body) }.getOrNull() ?: continue
            val muxed = o.optJSONArray("videoStreams") ?: o.optJSONArray("adaptiveStreams")
            // Prefer a progressive muxed stream if present
            val progressive = o.optJSONArray("videoStreams")
            var best: String? = null
            var bestScore = -1
            if (progressive != null) {
                for (i in 0 until progressive.length()) {
                    val s = progressive.getJSONObject(i)
                    if (s.optString("videoOnly", "false") == "true" || s.optBoolean("videoOnly")) continue
                    val q = s.optInt("height", s.optString("quality").filter { it.isDigit() }.toIntOrNull() ?: 0)
                    val url = s.optString("url")
                    if (url.isNotBlank() && q >= bestScore) {
                        bestScore = q
                        best = url
                    }
                }
            }
            if (best != null) return best
            val fmt = o.optString("hls")
            if (fmt.isNotBlank()) return fmt
        }
        for (base in invidious) {
            val body = getOrNull("$base/api/v1/videos/$id") ?: continue
            val o = runCatching { JSONObject(body) }.getOrNull() ?: continue
            val fmts = o.optJSONArray("formatStreams") ?: continue
            var best: String? = null
            var bestScore = -1
            for (i in 0 until fmts.length()) {
                val s = fmts.getJSONObject(i)
                val q = s.optString("resolution").filter { it.isDigit() }.toIntOrNull() ?: 0
                val url = s.optString("url")
                if (url.isNotBlank() && q >= bestScore) {
                    bestScore = q
                    best = url
                }
            }
            if (best != null) return best
        }
        return null
    }

    private fun httpDownload(url: String, dest: java.io.File) {
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            instanceFollowRedirects = true
            connectTimeout = 20_000
            readTimeout = 300_000
            setRequestProperty("User-Agent", "Clipper/1.2.0")
        }
        conn.inputStream.use { inp -> FileOutputStream(dest).use { inp.copyTo(it) } }
        conn.disconnect()
    }

    private fun getOrNull(url: String): String? = runCatching {
        val conn = (URL(url).openConnection() as HttpsURLConnection).apply {
            instanceFollowRedirects = true
            connectTimeout = 12_000
            readTimeout = 20_000
            setRequestProperty("User-Agent", "Clipper/1.2.0")
            setRequestProperty("Accept", "application/json, application/atom+xml, text/xml, */*")
        }
        val code = conn.responseCode
        val text = (if (code in 200..299) conn.inputStream else conn.errorStream)
            ?.bufferedReader()?.readText()
        conn.disconnect()
        if (code in 200..299) text else null
    }.getOrNull()

    private fun videoId(url: String): String? =
        Regex("(?:v=|/shorts/|youtu\\.be/)([A-Za-z0-9_-]{11})").find(url)?.groupValues?.get(1)

    private fun channelId(url: String): String? {
        Regex("channel/(UC[A-Za-z0-9_-]{20,})").find(url)?.groupValues?.get(1)?.let { return it }
        Regex("channel_id=(UC[A-Za-z0-9_-]{20,})").find(url)?.groupValues?.get(1)?.let { return it }
        // @handles need a resolve; try Piped
        val handle = Regex("youtube\\.com/@([^/?]+)").find(url)?.groupValues?.get(1) ?: return null
        for (base in piped) {
            val body = getOrNull("$base/channel/@$handle") ?: getOrNull("$base/c/$handle") ?: continue
            val o = runCatching { JSONObject(body) }.getOrNull() ?: continue
            val id = o.optString("id").ifBlank { o.optString("uploaderId") }
            if (id.startsWith("UC")) return id
        }
        return null
    }

    private fun unescape(s: String): String = s
        .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        .replace("&quot;", "\"").replace("&#39;", "'")
}
