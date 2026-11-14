package app.clipper.pipeline

import org.json.JSONArray
import org.json.JSONObject
import java.nio.file.Files
import java.nio.file.Path
import java.time.Instant
import java.util.UUID

class QueueStore(private val file: Path) {
    fun all(): List<QueueItem> {
        if (!Files.exists(file)) return emptyList()
        val arr = JSONArray(Files.readString(file))
        return (0 until arr.length()).map { QueueItem.fromJson(arr.getJSONObject(it)) }
    }

    fun save(items: List<QueueItem>) {
        Files.createDirectories(file.parent)
        val arr = JSONArray()
        items.forEach { arr.put(it.toJson()) }
        Files.writeString(file, arr.toString(2))
    }

    fun enqueue(
        path: Path,
        title: String,
        description: String,
        tags: List<String>,
        hook: String,
        kind: JobKind = JobKind.CLIP,
        sourceUrl: String? = null,
        sourceLabel: String? = null,
        license: String? = null,
        foundBy: String? = null,
        durationSec: Double? = null,
        autopilot: Boolean = false,
    ): QueueItem {
        val item = QueueItem(
            id = UUID.randomUUID().toString().take(10),
            kind = kind,
            path = path.toAbsolutePath().toString(),
            title = title,
            description = description,
            tags = tags,
            hook = hook,
            status = if (autopilot) QueueStatus.APPROVED else QueueStatus.PENDING_REVIEW,
            createdAt = Instant.now().toString(),
            sourceUrl = sourceUrl,
            sourceLabel = sourceLabel,
            license = license,
            foundBy = foundBy,
            durationSec = durationSec,
        )
        save(all() + item)
        return item
    }

    fun updateStatus(id: String, status: QueueStatus): QueueItem? {
        val items = all().toMutableList()
        val i = items.indexOfFirst { it.id == id }
        if (i < 0) return null
        items[i] = items[i].copy(status = status)
        save(items)
        return items[i]
    }
}
