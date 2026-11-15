package app.clipper.pipeline

import org.json.JSONArray
import org.json.JSONObject
import java.io.FileOutputStream
import java.io.IOException
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption

/** Minimal HTTP surface so the fetcher can be unit-tested with a fake. */
interface Http {
    data class Resp(val code: Int, val body: String, val contentType: String? = null)
    data class RangeResult(val code: Int, val total: Long?, val written: Long, val contentType: String?)

    fun get(url: String, headers: Map<String, String> = emptyMap(), timeoutMs: Int = 15_000): Resp
    fun post(url: String, json: String, headers: Map<String, String> = emptyMap(), timeoutMs: Int = 15_000): Resp

    /** Write bytes [start, endInclusive] of [url] to [out]. A server that ignores Range returns 200 + the whole body. */
    fun range(
        url: String,
        headers: Map<String, String>,
        start: Long,
        endInclusive: Long,
        out: OutputStream,
        onBytes: (Long) -> Unit,
    ): RangeResult
}

class UrlConnectionHttp(private val userAgent: String = "Mozilla/5.0 (Linux; Android 14) Clipper/1.2.1") : Http {
    private fun open(url: String, headers: Map<String, String>, timeoutMs: Int): HttpURLConnection =
        (URL(url).openConnection() as HttpURLConnection).apply {
            instanceFollowRedirects = true
            connectTimeout = timeoutMs.coerceAtMost(15_000)
            readTimeout = timeoutMs
            setRequestProperty("User-Agent", userAgent)
            setRequestProperty("Accept-Language", "en-US,en;q=0.8")
            headers.forEach { (k, v) -> setRequestProperty(k, v) }
        }

    private fun readBody(c: HttpURLConnection): Http.Resp {
        val code = c.responseCode
        val stream = if (code in 200..299) c.inputStream else c.errorStream
        val text = stream?.bufferedReader()?.use { it.readText() } ?: ""
        val ct = c.contentType
        c.disconnect()
        return Http.Resp(code, text, ct)
    }

    override fun get(url: String, headers: Map<String, String>, timeoutMs: Int): Http.Resp =
        readBody(open(url, headers, timeoutMs))

    override fun post(url: String, json: String, headers: Map<String, String>, timeoutMs: Int): Http.Resp {
        val c = open(url, headers + ("Content-Type" to "application/json"), timeoutMs)
        c.requestMethod = "POST"
        c.doOutput = true
        c.outputStream.use { it.write(json.toByteArray()) }
        return readBody(c)
    }

    override fun range(
        url: String,
        headers: Map<String, String>,
        start: Long,
        endInclusive: Long,
        out: OutputStream,
        onBytes: (Long) -> Unit,
    ): Http.RangeResult {
        val c = open(url, headers + ("Range" to "bytes=$start-$endInclusive"), 45_000)
        try {
            val code = c.responseCode
            val ct = c.contentType
            if (code !in 200..299) return Http.RangeResult(code, null, 0, ct)
            val total = c.getHeaderField("Content-Range")?.substringAfter('/')?.toLongOrNull()
                ?: if (code == 200) c.contentLengthLong.takeIf { it > 0 } else null
            var written = 0L
            c.inputStream.use { inp ->
                val buf = ByteArray(64 * 1024)
                while (true) {
                    val n = inp.read(buf)
                    if (n < 0) break
                    out.write(buf, 0, n)
                    written += n
                    onBytes(n.toLong())
                }
            }
            return Http.RangeResult(code, total, written, ct)
        } finally {
            c.disconnect()
        }
    }
}

class FetchFailed(message: String, val attempts: List<String> = emptyList()) : Exception(message)

data class FetchResult(val path: Path, val title: String?, val videoId: String?, val via: String)

/**
 * Downloads a YouTube video (or a direct video file link) with several independent
 * routes, so one dead server never makes the app silently do nothing:
 *
 * 1. YouTube's own app API (Android, iOS, VR clients) straight from the phone.
 * 2. Public Piped servers (built-in list + live list refreshed every 12 h).
 * 3. Public Invidious servers (built-in list + live list, proxied streams).
 *
 * Every step is reported through [log]; download progress through [progress].
 * Failure always ends in a [FetchFailed] with a plain-English message.
 */
class VideoFetcher(
    private val http: Http = UrlConnectionHttp(),
    private val cacheDir: Path? = null,
    /** Merge a video-only and an audio-only file into [out]. Null = only use ready-made (muxed) streams. */
    private val muxer: ((video: Path, audio: Path, out: Path) -> Unit)? = null,
    private val log: (String) -> Unit = {},
    private val progress: (Int?) -> Unit = {},
    private val maxHeight: Int = 720,
    private val pipedInstances: List<String> = DEFAULT_PIPED,
    private val invidiousInstances: List<String> = DEFAULT_INVIDIOUS,
    private val refreshInstanceLists: Boolean = true,
    private val maxServersPerKind: Int = 6,
    private val chunkSize: Long = 8L * 1024 * 1024,
) {
    data class Pick(
        val via: String,
        val title: String?,
        val muxedUrl: String?,
        val videoUrl: String?,
        val audioUrl: String?,
        val headers: Map<String, String> = emptyMap(),
        val muxedLabel: String = "",
        val adaptiveLabel: String = "",
    )

    private class Unavailable(msg: String) : Exception(msg)

    fun fetch(input: String, destDir: Path): FetchResult {
        Files.createDirectories(destDir)
        return when (val p = YoutubeUrl.parse(input)) {
            is YoutubeUrl.Parsed.Invalid -> throw FetchFailed(p.reason)
            is YoutubeUrl.Parsed.OtherSite -> throw FetchFailed(
                "Clipper on the phone can download YouTube links only (${p.host} isn't supported). " +
                    "Save that video to your phone first, then tap \"Pick a file\".",
            )
            is YoutubeUrl.Parsed.DirectFile -> {
                log("Downloading the video file…")
                val name = "direct-${System.currentTimeMillis()}.mp4"
                val dest = destDir.resolve(name)
                downloadTo(p.url, emptyMap(), dest, 0, 1)
                FetchResult(dest, null, null, "direct link")
            }
            is YoutubeUrl.Parsed.YouTube -> fetchYoutube(p.videoId, destDir)
        }
    }

    fun fetchYoutube(id: String, destDir: Path): FetchResult {
        log("Video ID: $id")
        val attempts = mutableListOf<String>()
        var youtubeSaid: String? = null
        val routes: List<Pair<String, () -> List<Pick>>> = listOf(
            "YouTube (direct)" to { innertubePicks(id, attempts) { youtubeSaid = it } },
            "Piped servers" to { pipedPicks(id, attempts) },
            "Invidious servers" to { invidiousPicks(id, attempts) },
        )
        for ((label, resolve) in routes) {
            log("Trying $label…")
            val picks = runCatching { resolve() }.getOrElse {
                attempts += "$label: ${it.message ?: it.javaClass.simpleName}"
                log("  $label failed: ${it.message}")
                emptyList()
            }
            for (pick in picks) {
                val result = tryDownload(pick, id, destDir, attempts)
                if (result != null) return result
            }
        }
        val reason = youtubeSaid
        val msg = buildString {
            append("Couldn't download this video. ")
            if (reason != null) append("YouTube said: \"$reason\". ")
            append("Every download route failed (${attempts.size} tries). ")
            append("Check your internet and try again in a few minutes. If it keeps failing, download the video to your phone and tap \"Pick a file\".")
        }
        throw FetchFailed(msg, attempts)
    }

    private fun tryDownload(pick: Pick, id: String, destDir: Path, attempts: MutableList<String>): FetchResult? {
        val dest = destDir.resolve("$id.mp4")
        if (muxer != null && pick.videoUrl != null && pick.audioUrl != null) {
            log("  ${pick.via}: downloading ${pick.adaptiveLabel.ifBlank { "video + audio" }}")
            val v = destDir.resolve("$id.video.part")
            val a = destDir.resolve("$id.audio.part")
            try {
                downloadTo(pick.videoUrl, pick.headers, v, 0, 2)
                downloadTo(pick.audioUrl, pick.headers, a, 1, 2)
                log("  Merging video and audio…")
                progress(null)
                val tmp = destDir.resolve("$id.merge.mp4")
                muxer.invoke(v, a, tmp)
                if (!Files.exists(tmp) || Files.size(tmp) < 50_000) throw IOException("merge produced no file")
                Files.move(tmp, dest, StandardCopyOption.REPLACE_EXISTING)
                log("  Done via ${pick.via}.")
                return FetchResult(dest, pick.title, id, pick.via)
            } catch (e: Exception) {
                attempts += "${pick.via} (video+audio): ${e.message}"
                log("  ${pick.via} video+audio failed: ${e.message}")
            } finally {
                runCatching { Files.deleteIfExists(v) }
                runCatching { Files.deleteIfExists(a) }
            }
        }
        if (pick.muxedUrl != null) {
            log("  ${pick.via}: downloading ${pick.muxedLabel.ifBlank { "video" }}")
            try {
                downloadTo(pick.muxedUrl, pick.headers, dest, 0, 1)
                log("  Done via ${pick.via}.")
                return FetchResult(dest, pick.title, id, pick.via)
            } catch (e: Exception) {
                attempts += "${pick.via}: ${e.message}"
                log("  ${pick.via} failed: ${e.message}")
                runCatching { Files.deleteIfExists(dest) }
            }
        }
        if (pick.muxedUrl == null && (pick.videoUrl == null || pick.audioUrl == null || muxer == null)) {
            attempts += "${pick.via}: no usable stream"
            log("  ${pick.via}: no usable stream")
        }
        return null
    }

    /** Chunked Range download with progress; rejects HTML/error pages. */
    fun downloadTo(url: String, headers: Map<String, String>, dest: Path, part: Int, parts: Int) {
        Files.createDirectories(dest.parent)
        var done = 0L
        var total: Long? = null
        var lastPct = -1
        FileOutputStream(dest.toFile()).use { out ->
            while (true) {
                val end = done + chunkSize - 1
                val r = http.range(url, headers, done, end, out) { n ->
                    done += n
                    val t = total
                    if (t != null && t > 0) {
                        val pct = (((part + done.toDouble() / t) / parts) * 100).toInt().coerceIn(0, 100)
                        if (pct != lastPct) { lastPct = pct; progress(pct) }
                    }
                }
                if (r.code == 416 && done > 0) break
                if (r.code !in 200..299) throw IOException("server answered HTTP ${r.code}")
                if (r.contentType?.contains("text/html", true) == true || r.contentType?.contains("json", true) == true) {
                    throw IOException("server sent a web page instead of a video")
                }
                if (total == null) total = r.total
                if (r.code == 200) break // whole body in one go
                if (r.written <= 0) break
                val t = total ?: break
                if (done >= t) break
            }
        }
        val size = Files.size(dest)
        if (size < 20_000) throw IOException("download was empty ($size bytes)")
        val head = ByteArray(16)
        Files.newInputStream(dest).use { it.read(head) }
        val asText = String(head, Charsets.ISO_8859_1)
        if (asText.trimStart().startsWith("<") || asText.trimStart().startsWith("{")) {
            throw IOException("server sent an error page instead of a video")
        }
    }

    // ---------- YouTube app API ----------

    private data class Client(
        val name: String,
        val version: String,
        val id: Int,
        val ua: String,
        val extra: Map<String, Any>,
    )

    private val clients = listOf(
        Client(
            "ANDROID", "20.10.38", 3,
            "com.google.android.youtube/20.10.38 (Linux; U; Android 14) gzip",
            mapOf("androidSdkVersion" to 34, "osName" to "Android", "osVersion" to "14"),
        ),
        Client(
            "IOS", "20.10.4", 5,
            "com.google.ios.youtube/20.10.4 (iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X;)",
            mapOf("deviceMake" to "Apple", "deviceModel" to "iPhone16,2", "osName" to "iPhone", "osVersion" to "18.3.2.22D82"),
        ),
        Client(
            "ANDROID_VR", "1.65.10", 28,
            "com.google.android.apps.youtube.vr.oculus/1.65.10 (Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip",
            mapOf("androidSdkVersion" to 32, "osName" to "Android", "osVersion" to "12L", "deviceMake" to "Oculus", "deviceModel" to "Quest 3"),
        ),
    )

    private fun innertubePicks(id: String, attempts: MutableList<String>, onReason: (String) -> Unit): List<Pick> {
        val picks = mutableListOf<Pick>()
        for (c in clients) {
            val via = "YouTube ${c.name.lowercase()} API"
            try {
                val client = JSONObject().put("clientName", c.name).put("clientVersion", c.version)
                    .put("hl", "en").put("gl", "US")
                c.extra.forEach { (k, v) -> client.put(k, v) }
                val body = JSONObject()
                    .put("videoId", id)
                    .put("context", JSONObject().put("client", client))
                    .put("contentCheckOk", true)
                    .put("racyCheckOk", true)
                val r = http.post(
                    "https://www.youtube.com/youtubei/v1/player?prettyPrint=false",
                    body.toString(),
                    mapOf(
                        "User-Agent" to c.ua,
                        "X-YouTube-Client-Name" to c.id.toString(),
                        "X-YouTube-Client-Version" to c.version,
                        "Origin" to "https://www.youtube.com",
                    ),
                )
                if (r.code !in 200..299) throw IOException("HTTP ${r.code}")
                val o = JSONObject(r.body)
                val ps = o.optJSONObject("playabilityStatus")
                val status = ps?.optString("status").orEmpty()
                if (status != "OK") {
                    val reason = ps?.optString("reason").orEmpty().ifBlank { status }
                    if (!reason.contains("bot", true)) onReason(reason)
                    throw Unavailable("YouTube said \"$reason\"")
                }
                val details = o.optJSONObject("videoDetails")
                if (details?.optBoolean("isLive") == true || details?.optBoolean("isLiveContent") == true && details.optBoolean("isUpcoming")) {
                    onReason("This is a live stream")
                    throw Unavailable("live streams can't be clipped; wait until it has finished")
                }
                val sd = o.optJSONObject("streamingData") ?: throw IOException("no streams")
                val muxed = bestMuxed(sd.optJSONArray("formats"))
                val (video, audio) = bestAdaptive(sd.optJSONArray("adaptiveFormats"))
                if (muxed == null && (video == null || audio == null)) throw IOException("no downloadable streams")
                log("  $via: found streams")
                picks += Pick(
                    via = via,
                    title = details?.optString("title"),
                    muxedUrl = muxed?.optString("url"),
                    videoUrl = video?.optString("url"),
                    audioUrl = audio?.optString("url"),
                    headers = mapOf("User-Agent" to c.ua),
                    muxedLabel = muxed?.let { "${it.optString("qualityLabel", "")} video".trim() } ?: "",
                    adaptiveLabel = video?.let { "${it.optString("qualityLabel", "")} video + audio".trim() } ?: "",
                )
                // One working client is usually enough; keep one more as a spare.
                if (picks.size >= 2) break
            } catch (e: Exception) {
                attempts += "$via: ${e.message}"
                log("  $via: ${e.message}")
            }
        }
        return picks
    }

    private fun bestMuxed(arr: JSONArray?): JSONObject? {
        if (arr == null) return null
        var best: JSONObject? = null
        for (i in 0 until arr.length()) {
            val f = arr.optJSONObject(i) ?: continue
            if (f.optString("url").isBlank()) continue
            if (!f.optString("mimeType").startsWith("video/mp4")) continue
            val h = f.optInt("height")
            if (h > maxHeight) continue
            if (best == null || h > best.optInt("height")) best = f
        }
        return best
    }

    private fun bestAdaptive(arr: JSONArray?): Pair<JSONObject?, JSONObject?> {
        if (arr == null) return null to null
        var v: JSONObject? = null
        var a: JSONObject? = null
        for (i in 0 until arr.length()) {
            val f = arr.optJSONObject(i) ?: continue
            if (f.optString("url").isBlank()) continue
            val mime = f.optString("mimeType")
            if (mime.startsWith("video/mp4") && mime.contains("avc1")) {
                val h = f.optInt("height")
                if (h in 1..maxHeight && (v == null || h > v.optInt("height"))) v = f
            } else if (mime.startsWith("audio/mp4")) {
                // Skip dubbed/auto-translated tracks when YouTube marks them.
                val track = f.optJSONObject("audioTrack")
                if (track != null && !track.optBoolean("audioIsDefault", true)) continue
                if (a == null || f.optInt("bitrate") > a.optInt("bitrate")) a = f
            }
        }
        return v to a
    }

    // ---------- Piped ----------

    private fun pipedPicks(id: String, attempts: MutableList<String>): List<Pick> {
        val bases = (pipedInstances + liveList("piped") { fetchPipedList() }).map { it.trimEnd('/') }.distinct()
        val picks = mutableListOf<Pick>()
        var tried = 0
        for (base in bases) {
            if (tried >= maxServersPerKind || picks.size >= 2) break
            tried++
            val via = "Piped ${hostLabel(base)}"
            try {
                val r = http.get("$base/streams/$id", mapOf("Accept" to "application/json"), 15_000)
                val o = runCatching { JSONObject(r.body) }.getOrNull()
                if (r.code !in 200..299 || o == null) {
                    val m = o?.optString("message")?.ifBlank { null } ?: o?.optString("error")?.ifBlank { null }
                    throw IOException(if (m != null) shorten(m) else "HTTP ${r.code}")
                }
                if (o.optBoolean("livestream")) throw Unavailable("live streams can't be clipped")
                var muxed: JSONObject? = null
                var video: JSONObject? = null
                val vs = o.optJSONArray("videoStreams") ?: JSONArray()
                for (i in 0 until vs.length()) {
                    val s = vs.optJSONObject(i) ?: continue
                    val url = s.optString("url")
                    if (url.isBlank()) continue
                    val mime = s.optString("mimeType")
                    val h = s.optInt("height").takeIf { it > 0 } ?: s.optString("quality").takeWhile { it.isDigit() }.toIntOrNull() ?: 0
                    if (h > maxHeight) continue
                    if (!s.optBoolean("videoOnly")) {
                        if (mime.startsWith("video/mp4") && (muxed == null || h > muxed.optInt("_h"))) muxed = s.put("_h", h)
                    } else if (mime.startsWith("video/mp4") && s.optString("codec").startsWith("avc1")) {
                        if (video == null || h > video.optInt("_h")) video = s.put("_h", h)
                    }
                }
                var audio: JSONObject? = null
                val au = o.optJSONArray("audioStreams") ?: JSONArray()
                for (i in 0 until au.length()) {
                    val s = au.optJSONObject(i) ?: continue
                    if (s.optString("url").isBlank() || !s.optString("mimeType").startsWith("audio/mp4")) continue
                    if (s.optString("audioTrackType").let { it.isNotBlank() && it != "ORIGINAL" && it != "null" }) continue
                    if (audio == null || s.optInt("bitrate") > audio.optInt("bitrate")) audio = s
                }
                if (muxed == null && (video == null || audio == null)) throw IOException("no downloadable streams")
                log("  $via: found streams")
                picks += Pick(
                    via, o.optString("title"), muxed?.optString("url"), video?.optString("url"), audio?.optString("url"),
                    muxedLabel = muxed?.let { "${it.optString("quality")} video" } ?: "",
                    adaptiveLabel = video?.let { "${it.optString("quality")} video + audio" } ?: "",
                )
            } catch (e: Exception) {
                attempts += "$via: ${e.message ?: e.javaClass.simpleName}"
                log("  $via: ${e.message ?: e.javaClass.simpleName}")
            }
        }
        return picks
    }

    private fun fetchPipedList(): List<String> {
        val r = http.get("https://piped-instances.kavin.rocks/", mapOf("Accept" to "application/json"), 10_000)
        if (r.code !in 200..299) return emptyList()
        val arr = JSONArray(r.body)
        return (0 until arr.length()).mapNotNull { arr.optJSONObject(it)?.optString("api_url")?.ifBlank { null } }
            .filter { it.startsWith("https://") }
    }

    // ---------- Invidious ----------

    private fun invidiousPicks(id: String, attempts: MutableList<String>): List<Pick> {
        val bases = (invidiousInstances + liveList("invidious") { fetchInvidiousList() }).map { it.trimEnd('/') }.distinct()
        val picks = mutableListOf<Pick>()
        var tried = 0
        for (base in bases) {
            if (tried >= maxServersPerKind || picks.size >= 2) break
            tried++
            val via = "Invidious ${hostLabel(base)}"
            try {
                val r = http.get("$base/api/v1/videos/$id?local=true", mapOf("Accept" to "application/json"), 15_000)
                val o = runCatching { JSONObject(r.body) }.getOrNull()
                if (r.code !in 200..299 || o == null) {
                    val m = o?.optString("error")?.ifBlank { null }
                    throw IOException(if (m != null) shorten(m) else "HTTP ${r.code}")
                }
                if (o.optBoolean("liveNow")) throw Unavailable("live streams can't be clipped")
                var muxed: JSONObject? = null
                val fs = o.optJSONArray("formatStreams") ?: JSONArray()
                for (i in 0 until fs.length()) {
                    val s = fs.optJSONObject(i) ?: continue
                    if (s.optString("url").isBlank() || !s.optString("type").startsWith("video/mp4")) continue
                    val h = s.optString("resolution").takeWhile { it.isDigit() }.toIntOrNull() ?: 0
                    if (h > maxHeight) continue
                    if (muxed == null || h > muxed.optInt("_h")) muxed = s.put("_h", h)
                }
                var video: JSONObject? = null
                var audio: JSONObject? = null
                val af = o.optJSONArray("adaptiveFormats") ?: JSONArray()
                for (i in 0 until af.length()) {
                    val s = af.optJSONObject(i) ?: continue
                    if (s.optString("url").isBlank()) continue
                    val type = s.optString("type")
                    if (type.startsWith("video/mp4") && type.contains("avc1")) {
                        val h = s.optString("resolution").takeWhile { it.isDigit() }.toIntOrNull() ?: 0
                        if (h in 1..maxHeight && (video == null || h > video.optInt("_h"))) video = s.put("_h", h)
                    } else if (type.startsWith("audio/mp4")) {
                        if (audio == null || s.optString("bitrate").toLongOrNull() ?: 0 > (audio.optString("bitrate").toLongOrNull() ?: 0)) audio = s
                    }
                }
                if (muxed == null && (video == null || audio == null)) throw IOException("no downloadable streams")
                log("  $via: found streams")
                picks += Pick(
                    via, o.optString("title"),
                    muxed?.optString("url")?.let { absolutize(base, it) },
                    video?.optString("url")?.let { absolutize(base, it) },
                    audio?.optString("url")?.let { absolutize(base, it) },
                    muxedLabel = muxed?.let { "${it.optString("resolution")} video" } ?: "",
                    adaptiveLabel = video?.let { "${it.optString("resolution")} video + audio" } ?: "",
                )
            } catch (e: Exception) {
                attempts += "$via: ${e.message ?: e.javaClass.simpleName}"
                log("  $via: ${e.message ?: e.javaClass.simpleName}")
            }
        }
        return picks
    }

    private fun fetchInvidiousList(): List<String> {
        val r = http.get("https://api.invidious.io/instances.json?sort_by=health", mapOf("Accept" to "application/json"), 10_000)
        if (r.code !in 200..299) return emptyList()
        val arr = JSONArray(r.body)
        val out = mutableListOf<String>()
        for (i in 0 until arr.length()) {
            val pair = arr.optJSONArray(i) ?: continue
            val info = pair.optJSONObject(1) ?: continue
            if (info.optString("type") != "https") continue
            if (info.opt("api") != true) continue
            info.optString("uri").takeIf { it.startsWith("https://") }?.let { out += it }
        }
        return out
    }

    // ---------- helpers ----------

    /** Cached live server list (12 h), so dead built-in servers get replaced without an app update. */
    private fun liveList(kind: String, fetch: () -> List<String>): List<String> {
        if (!refreshInstanceLists) return emptyList()
        val file = cacheDir?.resolve("instances-$kind.json")
        if (file != null && Files.exists(file)) {
            val o = runCatching { JSONObject(Files.readString(file)) }.getOrNull()
            if (o != null && System.currentTimeMillis() - o.optLong("at") < 12 * 3600_000L) {
                val arr = o.optJSONArray("list") ?: JSONArray()
                return (0 until arr.length()).map { arr.getString(it) }
            }
        }
        val list = runCatching { fetch() }.getOrDefault(emptyList())
        if (file != null && list.isNotEmpty()) {
            runCatching {
                Files.createDirectories(file.parent)
                Files.writeString(file, JSONObject().put("at", System.currentTimeMillis()).put("list", JSONArray(list)).toString())
            }
        }
        return list
    }

    private fun absolutize(base: String, url: String): String =
        if (url.startsWith("http")) url else base.trimEnd('/') + "/" + url.trimStart('/')

    private fun hostLabel(base: String): String = runCatching { URI(base).host }.getOrNull() ?: base

    private fun shorten(s: String): String = s.lineSequence().first().take(140)

    companion object {
        val DEFAULT_PIPED = listOf(
            "https://api.piped.private.coffee",
            "https://pipedapi.kavin.rocks",
            "https://pipedapi.ducks.party",
            "https://pipedapi.adminforge.de",
            "https://pipedapi.reallyaweso.me",
            "https://pipedapi.leptons.xyz",
            "https://piped-api.privacy.com.de",
            "https://pipedapi.drgns.space",
        )
        val DEFAULT_INVIDIOUS = listOf(
            "https://yt.chocolatemoo53.com",
            "https://inv.nadeko.net",
            "https://invidious.nerdvpn.de",
            "https://yewtu.be",
            "https://invidious.f5.si",
        )
    }
}
