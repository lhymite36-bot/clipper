package app.clipper.pipeline

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.nio.file.Files
import java.nio.file.Path

interface Transcriber {
    fun transcribe(wav: Path): Transcript
}

/** Groq Whisper (whisper-large-v3-turbo or whisper-large-v3). Never logs the key. */
class GroqTranscriber(
    private val apiKey: String,
    private val model: String = "whisper-large-v3-turbo",
) : Transcriber {
    override fun transcribe(wav: Path): Transcript {
        val boundary = "----Clipper${System.currentTimeMillis()}"
        val url = URL("https://api.groq.com/openai/v1/audio/transcriptions")
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            setRequestProperty("Authorization", "Bearer $apiKey")
            setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
            connectTimeout = 30_000
            readTimeout = 180_000
        }
        val bytes = Files.readAllBytes(wav)
        val crlf = "\r\n"
        conn.outputStream.use { out ->
            fun writeField(name: String, value: String) {
                out.write("--$boundary$crlf".toByteArray())
                out.write("Content-Disposition: form-data; name=\"$name\"$crlf$crlf".toByteArray())
                out.write(value.toByteArray())
                out.write(crlf.toByteArray())
            }
            writeField("model", model)
            writeField("response_format", "verbose_json")
            writeField("timestamp_granularities[]", "word")
            out.write("--$boundary$crlf".toByteArray())
            out.write("Content-Disposition: form-data; name=\"file\"; filename=\"audio.wav\"$crlf".toByteArray())
            out.write("Content-Type: audio/wav$crlf$crlf".toByteArray())
            out.write(bytes)
            out.write(crlf.toByteArray())
            out.write("--$boundary--$crlf".toByteArray())
        }
        val code = conn.responseCode
        val body = (if (code in 200..299) conn.inputStream else conn.errorStream)
            .bufferedReader().readText()
        if (code !in 200..299) {
            error("Groq Whisper failed (HTTP $code)")
        }
        return parseVerbose(JSONObject(body))
    }

    companion object {
        fun parseVerbose(o: JSONObject): Transcript {
            val words = mutableListOf<TranscriptWord>()
            val arr = o.optJSONArray("words") ?: JSONArray()
            for (i in 0 until arr.length()) {
                val w = arr.getJSONObject(i)
                words += TranscriptWord(
                    start = w.optDouble("start"),
                    end = w.optDouble("end"),
                    word = w.optString("word").trim(),
                )
            }
            // Some responses nest words under segments
            if (words.isEmpty()) {
                val segs = o.optJSONArray("segments") ?: JSONArray()
                for (i in 0 until segs.length()) {
                    val sw = segs.getJSONObject(i).optJSONArray("words") ?: continue
                    for (j in 0 until sw.length()) {
                        val w = sw.getJSONObject(j)
                        words += TranscriptWord(
                            w.optDouble("start"),
                            w.optDouble("end"),
                            w.optString("word").trim(),
                        )
                    }
                }
            }
            return Transcript(o.optString("language", "en"), o.optString("text"), words)
        }
    }
}

/** Load a fixture / sidecar transcript produced elsewhere (e.g. desktop whisper). */
object TranscriptIO {
    fun load(path: Path): Transcript = Transcript.fromJson(org.json.JSONObject(Files.readString(path)))
    fun save(path: Path, t: Transcript) {
        Files.createDirectories(path.parent)
        Files.writeString(path, t.toJson().toString(2))
    }
}
