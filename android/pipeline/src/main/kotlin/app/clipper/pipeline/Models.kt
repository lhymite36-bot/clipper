package app.clipper.pipeline

import org.json.JSONArray
import org.json.JSONObject
import java.nio.file.Path

data class TranscriptWord(
    val start: Double,
    val end: Double,
    val word: String,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("start", start)
        .put("end", end)
        .put("word", word)

    companion object {
        fun fromJson(o: JSONObject) = TranscriptWord(
            start = o.optDouble("start"),
            end = o.optDouble("end"),
            word = o.optString("word"),
        )
    }
}

data class Transcript(
    val language: String = "en",
    val text: String = "",
    val words: List<TranscriptWord> = emptyList(),
) {
    fun slice(start: Double, end: Double): List<TranscriptWord> =
        words.filter { it.end > start && it.start < end }

    fun textIn(start: Double, end: Double): String =
        slice(start, end).joinToString(" ") { it.word }.replace(Regex("\\s+"), " ").trim()

    fun toJson(): JSONObject = JSONObject()
        .put("language", language)
        .put("text", text)
        .put("words", JSONArray().also { arr -> words.forEach { arr.put(it.toJson()) } })

    companion object {
        fun fromJson(o: JSONObject): Transcript {
            val words = mutableListOf<TranscriptWord>()
            val arr = o.optJSONArray("words") ?: JSONArray()
            for (i in 0 until arr.length()) words += TranscriptWord.fromJson(arr.getJSONObject(i))
            val text = o.optString("text").ifBlank {
                words.joinToString(" ") { it.word }
            }
            return Transcript(o.optString("language", "en"), text, words)
        }
    }
}

enum class Layout { FILL, BARS, TIGHT }

enum class JobKind { CLIP, RECAP_SHORT, RECAP_LONG }

enum class QueueStatus {
    PENDING_REVIEW, APPROVED, SCHEDULED, POSTED, REJECTED, DRAFT
}

data class Moment(
    val start: Double,
    val end: Double,
    val hook: String,
    val reason: String = "",
    val score: Double = 0.0,
) {
    val duration: Double get() = (end - start).coerceAtLeast(0.0)
}

data class ClipSpec(
    val sourcePath: Path,
    val moment: Moment,
    val layout: Layout = Layout.FILL,
    val width: Int = 1080,
    val height: Int = 1920,
    val musicPath: Path? = null,
    val sfxHits: List<Double> = emptyList(),
    val brand: String? = null,
)

data class RecapSpec(
    val sourcePath: Path,
    val kind: JobKind,
    val title: String,
    val scriptText: String,
    val voiceoverPath: Path,
    val captions: List<CaptionEvent>,
    val shots: List<Shot>,
    val layout: Layout = Layout.FILL,
    val musicPath: Path? = null,
    val narratorName: String = "en-US-AriaNeural",
    val width: Int = 1080,
    val height: Int = 1920,
) {
    val isShort: Boolean get() = kind == JobKind.RECAP_SHORT
}

data class Shot(
    val start: Double,
    val end: Double,
    val sourceStart: Double,
    val fallback: Boolean = false,
)

data class CaptionEvent(
    val start: Double,
    val end: Double,
    val text: String,
    val hook: Boolean = false,
)

data class QueueItem(
    val id: String,
    val kind: JobKind = JobKind.CLIP,
    val path: String,
    val title: String,
    val description: String,
    val tags: List<String> = emptyList(),
    val hook: String = "",
    var status: QueueStatus = QueueStatus.PENDING_REVIEW,
    val createdAt: String = "",
    val sourceUrl: String? = null,
    val sourceLabel: String? = null,
    val license: String? = null,
    val foundBy: String? = null,
    val durationSec: Double? = null,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("id", id)
        .put("kind", kind.name)
        .put("path", path)
        .put("title", title)
        .put("description", description)
        .put("tags", JSONArray(tags))
        .put("hook", hook)
        .put("status", status.name.lowercase())
        .put("created_at", createdAt)
        .put("source_url", sourceUrl)
        .put("source_label", sourceLabel)
        .put("license", license)
        .put("found_by", foundBy)
        .put("duration_sec", durationSec)

    companion object {
        fun fromJson(o: JSONObject): QueueItem {
            val tags = mutableListOf<String>()
            val arr = o.optJSONArray("tags") ?: JSONArray()
            for (i in 0 until arr.length()) tags += arr.getString(i)
            val kind = runCatching { JobKind.valueOf(o.optString("kind", "CLIP").uppercase()) }
                .getOrDefault(JobKind.CLIP)
            val statusName = o.optString("status", "pending_review").uppercase().replace("-", "_")
            val status = runCatching { QueueStatus.valueOf(statusName) }.getOrDefault(QueueStatus.PENDING_REVIEW)
            return QueueItem(
                id = o.getString("id"),
                kind = kind,
                path = o.optString("path"),
                title = o.optString("title"),
                description = o.optString("description"),
                tags = tags,
                hook = o.optString("hook"),
                status = status,
                createdAt = o.optString("created_at"),
                sourceUrl = o.optString("source_url").ifBlank { null },
                sourceLabel = o.optString("source_label").ifBlank { null },
                license = o.optString("license").ifBlank { null },
                foundBy = o.optString("found_by").ifBlank { null },
                durationSec = if (o.has("duration_sec") && !o.isNull("duration_sec")) o.optDouble("duration_sec") else null,
            )
        }
    }
}

enum class SourceKind { CHANNEL, PLAYLIST, BRIEF, KEYWORD, TRAILER }

data class WatchSource(
    val id: String,
    val kind: SourceKind,
    val query: String,
    val label: String = query,
    val ccOnly: Boolean = false,
    val recap: Boolean = false,
    val enabled: Boolean = true,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("id", id)
        .put("kind", kind.name.lowercase())
        .put("query", query)
        .put("label", label)
        .put("cc_only", ccOnly)
        .put("recap", recap)
        .put("enabled", enabled)

    companion object {
        fun fromJson(o: JSONObject): WatchSource {
            val kind = runCatching {
                SourceKind.valueOf(o.optString("kind", "KEYWORD").uppercase())
            }.getOrDefault(SourceKind.KEYWORD)
            return WatchSource(
                id = o.optString("id"),
                kind = kind,
                query = o.optString("query"),
                label = o.optString("label").ifBlank { o.optString("query") },
                ccOnly = o.optBoolean("cc_only"),
                recap = o.optBoolean("recap") || kind == SourceKind.TRAILER,
                enabled = o.optBoolean("enabled", true),
            )
        }
    }
}

data class FoundVideo(
    val url: String,
    val title: String,
    val videoId: String,
    val sourceId: String,
    val sourceLabel: String,
    val license: String = "unknown",
    val kind: JobKind = JobKind.CLIP,
    val channel: String? = null,
    val durationSec: Double? = null,
)

data class Probe(
    val duration: Double,
    val width: Int,
    val height: Int,
    val hasAudio: Boolean,
)

data class Settings(
    val geminiKey: String? = null,
    val groqKey: String? = null,
    val bufferToken: String? = null,
    val bufferProfile: String? = null,
    val githubToken: String? = null,
    val githubRepo: String? = null,
    val youtubeClientId: String? = null,
    val youtubeClientSecret: String? = null,
    val autopilot: Boolean = false,
    val layout: Layout = Layout.FILL,
    val dailyCap: Int = 8,
    val autoFindEnabled: Boolean = false,
    val autoFindIntervalHours: Int = 6,
    val wifiOnly: Boolean = true,
    val chargingOnly: Boolean = false,
    val ccOnlyDefault: Boolean = false,
    val whisperModel: String = "base",
)
