package app.clipper.pipeline

import org.json.JSONArray
import org.json.JSONObject
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.time.LocalTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * Visible job status shared between the background job and the screen, so a
 * pasted URL never "does nothing": every step, the progress %, and the final
 * success or error message are written here and shown in the app.
 */
class JobStatus(private val file: Path, private val zone: ZoneId = ZoneId.systemDefault()) {
    enum class State { IDLE, RUNNING, DONE, FAILED }

    data class Snapshot(
        val state: State = State.IDLE,
        val step: String = "",
        val percent: Int? = null,
        val message: String = "",
        val log: List<String> = emptyList(),
        val updatedAt: Long = 0,
    )

    private val lock = Any()
    private val fmt = DateTimeFormatter.ofPattern("HH:mm:ss")

    fun read(): Snapshot = synchronized(lock) {
        if (!Files.exists(file)) return Snapshot()
        val o = runCatching { JSONObject(Files.readString(file)) }.getOrNull() ?: return Snapshot()
        val arr = o.optJSONArray("log") ?: JSONArray()
        Snapshot(
            state = runCatching { State.valueOf(o.optString("state")) }.getOrDefault(State.IDLE),
            step = o.optString("step"),
            percent = if (o.has("percent") && !o.isNull("percent")) o.optInt("percent") else null,
            message = o.optString("message"),
            log = (0 until arr.length()).map { arr.optString(it) },
            updatedAt = o.optLong("updatedAt"),
        )
    }

    private fun write(s: Snapshot) {
        val o = JSONObject()
            .put("state", s.state.name)
            .put("step", s.step)
            .put("percent", s.percent ?: JSONObject.NULL)
            .put("message", s.message)
            .put("log", JSONArray(s.log.takeLast(MAX_LOG)))
            .put("updatedAt", System.currentTimeMillis())
        Files.createDirectories(file.parent)
        val tmp = file.resolveSibling(file.fileName.toString() + ".tmp")
        Files.writeString(tmp, o.toString())
        Files.move(tmp, file, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
    }

    private fun stamp(line: String) = "${LocalTime.now(zone).format(fmt)}  $line"

    fun start(step: String) = synchronized(lock) {
        write(Snapshot(State.RUNNING, step, null, "", listOf(stamp(step))))
    }

    fun step(step: String) = synchronized(lock) {
        val s = read()
        write(s.copy(step = step, percent = null, log = s.log + stamp(step)))
    }

    fun log(line: String) = synchronized(lock) {
        val s = read()
        write(s.copy(log = s.log + stamp(line)))
    }

    fun percent(p: Int?) = synchronized(lock) {
        val s = read()
        if (s.percent != p) write(s.copy(percent = p))
    }

    fun done(message: String) = synchronized(lock) {
        val s = read()
        write(s.copy(state = State.DONE, percent = 100, message = message, log = s.log + stamp(message)))
    }

    fun failed(message: String) = synchronized(lock) {
        val s = read()
        write(s.copy(state = State.FAILED, percent = null, message = message, log = s.log + stamp("ERROR: $message")))
    }

    /** A RUNNING status that hasn't changed in a long time means the job was killed (e.g. by the phone's battery saver). */
    fun isStale(s: Snapshot, now: Long = System.currentTimeMillis()): Boolean =
        s.state == State.RUNNING && now - s.updatedAt > STALE_MS

    companion object {
        const val MAX_LOG = 80
        const val STALE_MS = 10 * 60_000L
    }
}
