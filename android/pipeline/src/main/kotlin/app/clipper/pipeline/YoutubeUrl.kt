package app.clipper.pipeline

import java.net.URI
import java.net.URLDecoder

/**
 * Turns whatever the user pasted or shared into something Clipper can download.
 *
 * Handles youtube.com/watch?v=, m.youtube.com, music.youtube.com, youtu.be/ID,
 * /shorts/ID, /live/ID, /embed/ID, /v/ID, youtube-nocookie.com, tracking params
 * like ?si= / &t=, share text with words around the link, links without
 * https://, and a bare 11-character video ID.
 */
object YoutubeUrl {
    private val ID = Regex("^[A-Za-z0-9_-]{11}$")
    private val URL_IN_TEXT = Regex("""(?i)\b((?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>"']*)?)""")
    private val VIDEO_EXT = Regex("""(?i)\.(mp4|m4v|mov|webm|mkv|3gp)(?:$|[?#])""")

    sealed class Parsed {
        data class YouTube(val videoId: String, val canonicalUrl: String) : Parsed()
        data class DirectFile(val url: String) : Parsed()
        data class OtherSite(val url: String, val host: String) : Parsed()
        data class Invalid(val reason: String) : Parsed()
    }

    fun parse(raw: String?): Parsed {
        val text = raw?.trim().orEmpty()
        if (text.isEmpty()) return Parsed.Invalid("Paste a YouTube link first.")
        if (ID.matches(text)) return youtube(text)
        val candidates = URL_IN_TEXT.findAll(text).map { it.groupValues[1].trimEnd('.', ',', ')', ']', '!', '?') }.toList()
        if (candidates.isEmpty()) {
            return Parsed.Invalid("That doesn't look like a link. Copy the video's Share link from YouTube and paste it here.")
        }
        // Prefer a YouTube link if the shared text has several.
        for (c in candidates) videoId(c)?.let { return youtube(it) }
        val first = candidates.first()
        val url = if (first.startsWith("http", true)) first else "https://$first"
        val host = hostOf(url)
        if (isYoutubeHost(host)) {
            return Parsed.Invalid(
                "This YouTube link isn't a single video (channel, playlist or home page). Open the video, tap Share > Copy link, and paste that.",
            )
        }
        if (VIDEO_EXT.containsMatchIn(url)) return Parsed.DirectFile(url)
        return Parsed.OtherSite(url, host)
    }

    fun videoId(raw: String): String? {
        val s = raw.trim()
        if (ID.matches(s)) return s
        val url = if (s.startsWith("http", true)) s else "https://$s"
        val uri = runCatching { URI(url.replace(" ", "%20")) }.getOrNull() ?: return regexFallback(s)
        val host = (uri.host ?: return regexFallback(s)).lowercase()
        if (!isYoutubeHost(host)) return null
        val path = uri.rawPath.orEmpty()
        if (host.endsWith("youtu.be")) {
            return path.trim('/').substringBefore('/').takeIf { ID.matches(it) }
        }
        val segs = path.split('/').filter { it.isNotBlank() }
        if (segs.size >= 2 && segs[0] in setOf("shorts", "live", "embed", "v", "e")) {
            return segs[1].takeIf { ID.matches(it) }
        }
        val query = uri.rawQuery.orEmpty()
        val params = query.split('&').mapNotNull {
            val k = it.substringBefore('=')
            val v = it.substringAfter('=', "")
            if (k.isBlank()) null else k to runCatching { URLDecoder.decode(v, "UTF-8") }.getOrDefault(v)
        }.toMap()
        params["v"]?.takeIf { ID.matches(it) }?.let { return it }
        // attribution_link?u=/watch%3Fv%3DID
        params["u"]?.let { inner -> Regex("v=([A-Za-z0-9_-]{11})").find(inner)?.let { return it.groupValues[1] } }
        return null
    }

    private fun regexFallback(s: String): String? =
        Regex("(?:v=|/shorts/|/live/|/embed/|youtu\\.be/)([A-Za-z0-9_-]{11})").find(s)?.groupValues?.get(1)

    fun isYoutubeHost(host: String): Boolean {
        val h = host.lowercase().removePrefix("www.")
        return h == "youtu.be" || h == "youtube.com" || h.endsWith(".youtube.com") ||
            h == "youtube-nocookie.com" || h.endsWith(".youtube-nocookie.com")
    }

    private fun hostOf(url: String): String = runCatching { URI(url).host?.lowercase() }.getOrNull().orEmpty()

    private fun youtube(id: String) = Parsed.YouTube(id, "https://www.youtube.com/watch?v=$id")
}
