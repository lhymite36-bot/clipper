package app.clipper.pipeline

import org.json.JSONArray
import org.json.JSONObject
import java.nio.file.Files
import java.nio.file.Path
import java.time.LocalDate
import java.time.ZoneId
import java.util.UUID

/**
 * Pulls videos by itself from watched channels/playlists/briefs, keyword/trending
 * search (optional Creative Commons filter), and movie trailers by title for Recap.
 *
 * New items are queued for auto-clip or recap and land in the draft-only review
 * queue. Nothing posts unless Autopilot is on. Dedupe + daily cap are enforced here.
 */
class AutoFind(
    private val storeDir: Path,
    private val runner: CommandRunner,
    private val zone: ZoneId = ZoneId.of("Asia/Calcutta"),
    var dailyCap: Int = 8,
    private val ytDlp: String = "yt-dlp",
) {
    private val sourcesFile get() = storeDir.resolve("sources.json")
    private val seenFile get() = storeDir.resolve("seen.json")
    private val capFile get() = storeDir.resolve("daily-cap.json")

    fun listSources(): List<WatchSource> = loadArray(sourcesFile).map { WatchSource.fromJson(it) }

    fun saveSources(sources: List<WatchSource>) {
        Files.createDirectories(storeDir)
        val arr = JSONArray()
        sources.forEach { arr.put(it.toJson()) }
        Files.writeString(sourcesFile, arr.toString(2))
    }

    fun addSource(source: WatchSource): WatchSource {
        val all = listSources().toMutableList()
        val withId = if (source.id.isBlank()) source.copy(id = UUID.randomUUID().toString().take(8)) else source
        all.removeAll { it.kind == withId.kind && it.query == withId.query }
        all += withId
        saveSources(all)
        return withId
    }

    fun removeSource(id: String) {
        saveSources(listSources().filterNot { it.id == id })
    }

    fun seenIds(): MutableSet<String> {
        if (!Files.exists(seenFile)) return mutableSetOf()
        val arr = JSONArray(Files.readString(seenFile))
        val set = mutableSetOf<String>()
        for (i in 0 until arr.length()) set += arr.getString(i)
        return set
    }

    fun markSeen(ids: Collection<String>) {
        val set = seenIds()
        set += ids
        Files.createDirectories(storeDir)
        val arr = JSONArray()
        set.forEach { arr.put(it) }
        Files.writeString(seenFile, arr.toString())
    }

    fun usedToday(): Int {
        if (!Files.exists(capFile)) return 0
        val o = JSONObject(Files.readString(capFile))
        val today = LocalDate.now(zone).toString()
        return if (o.optString("date") == today) o.optInt("count") else 0
    }

    fun recordUsed(n: Int) {
        Files.createDirectories(storeDir)
        val today = LocalDate.now(zone).toString()
        val already = usedToday()
        Files.writeString(capFile, JSONObject().put("date", today).put("count", already + n).toString())
    }

    fun remainingToday(): Int = (dailyCap - usedToday()).coerceAtLeast(0)

    /**
     * Check every enabled source, return new unprocessed videos up to the remaining daily cap.
     */
    fun discover(maxPerSource: Int = 5): List<FoundVideo> {
        val remaining = remainingToday()
        if (remaining <= 0) return emptyList()
        val seen = seenIds()
        val found = mutableListOf<FoundVideo>()
        for (src in listSources().filter { it.enabled }) {
            if (found.size >= remaining) break
            val batch = runCatching { poll(src, maxPerSource) }.getOrDefault(emptyList())
            for (v in batch) {
                if (v.videoId.isNotBlank() && v.videoId in seen) continue
                if (found.any { it.videoId == v.videoId }) continue
                found += v
                if (found.size >= remaining) break
            }
        }
        return found
    }

    fun poll(src: WatchSource, maxItems: Int = 5): List<FoundVideo> {
        val query = when (src.kind) {
            SourceKind.CHANNEL, SourceKind.PLAYLIST, SourceKind.BRIEF -> src.query
            SourceKind.KEYWORD -> ytSearchQuery(src.query, src.ccOnly, trending = false)
            SourceKind.TRAILER -> ytSearchQuery("${src.query} official trailer", src.ccOnly, trending = false)
        }
        val extra = mutableListOf<String>()
        if (src.ccOnly && src.kind != SourceKind.KEYWORD && src.kind != SourceKind.TRAILER) {
            extra += listOf("--match-filter", "license *= *Creative Commons")
        }
        val jsonl = extractJson(query, maxItems, extra)
        return jsonl.mapNotNull { o ->
            val id = o.optString("id").ifBlank { videoIdFromUrl(o.optString("webpage_url")) }
            if (id.isBlank()) return@mapNotNull null
            val license = normalizeLicense(o.optString("license"), o.optString("webpage_url"))
            val kind = if (src.recap || src.kind == SourceKind.TRAILER) JobKind.RECAP_SHORT else JobKind.CLIP
            FoundVideo(
                url = o.optString("webpage_url").ifBlank { "https://www.youtube.com/watch?v=$id" },
                title = o.optString("title"),
                videoId = id,
                sourceId = src.id,
                sourceLabel = src.label.ifBlank { src.query },
                license = license,
                kind = kind,
                channel = o.optString("channel").ifBlank { o.optString("uploader") }.ifBlank { null },
                durationSec = if (o.has("duration")) o.optDouble("duration") else null,
            )
        }
    }

    fun ytSearchQuery(keyword: String, ccOnly: Boolean, trending: Boolean): String {
        val q = if (trending && keyword.isBlank()) "ytsearch10:trending" else {
            val prefix = if (ccOnly) "ytsearch10:creativecommons $keyword" else "ytsearch10:$keyword"
            prefix
        }
        return q
    }

    fun ytDlpSearchArgs(query: String, ccOnly: Boolean, maxItems: Int = 10): List<String> {
        // Creative Commons-only uses yt-dlp's native search prefix plus a license match-filter.
        val q = if (query.startsWith("ytsearch") || query.startsWith("http")) query
        else ytSearchQuery(query, ccOnly, trending = false)
        val args = mutableListOf(
            ytDlp, "--flat-playlist", "--dump-json", "--no-download",
            "--playlist-end", maxItems.toString(),
            "--no-warnings",
        )
        if (ccOnly) args += listOf("--match-filter", "license *= *Creative Commons")
        args += q
        return args
    }

    private fun extractJson(query: String, maxItems: Int, extra: List<String>): List<JSONObject> {
        val args = mutableListOf(
            ytDlp, "--flat-playlist", "--dump-json", "--no-download",
            "--playlist-end", maxItems.toString(), "--no-warnings",
        )
        args += extra
        args += query
        val r = runner.run(args, 180)
        if (!r.ok && r.stdout.isBlank()) return emptyList()
        return r.stdout.lineSequence()
            .map { it.trim() }
            .filter { it.startsWith("{") }
            .mapNotNull { runCatching { JSONObject(it) }.getOrNull() }
            .toList()
    }

    fun download(url: String, destDir: Path): Path {
        Files.createDirectories(destDir)
        val out = destDir.resolve("%(id)s.%(ext)s").toString()
        val r = runner.run(
            listOf(
                ytDlp, "-f", "bv*+ba/b", "--no-playlist",
                "-o", out, "--no-warnings", url,
            ),
            900,
        )
        if (!r.ok) error("download failed")
        val files = Files.list(destDir).use { it.toList() }.filter { Files.isRegularFile(it) }
        return files.maxBy { Files.getLastModifiedTime(it).toMillis() }
    }

    fun trailerSearchQuery(title: String): String = "ytsearch5:${title.trim()} official trailer"

    companion object {
        fun videoIdFromUrl(url: String): String {
            val m = Regex("(?:v=|/shorts/|youtu\\.be/)([A-Za-z0-9_-]{11})").find(url)
            return m?.groupValues?.getOrNull(1) ?: ""
        }

        fun normalizeLicense(raw: String, url: String = ""): String {
            val s = raw.trim()
            if (s.isBlank() || s.equals("null", true)) {
                return if (url.contains("creative", true)) "Creative Commons" else "unknown"
            }
            return when {
                s.contains("creative commons", true) || s.equals("cc", true) -> "Creative Commons"
                s.contains("cc by", true) -> s
                else -> s
            }
        }

        fun looksLikeBriefUrl(url: String): Boolean {
            val u = url.lowercase()
            return listOf("contentrewards", "content-rewards", "vyro", "clipster", "indclip", "brief")
                .any { it in u }
        }
    }

    private fun loadArray(path: Path): List<JSONObject> {
        if (!Files.exists(path)) return emptyList()
        val text = Files.readString(path).trim()
        if (text.isBlank()) return emptyList()
        val arr = JSONArray(text)
        return (0 until arr.length()).map { arr.getJSONObject(it) }
    }
}
