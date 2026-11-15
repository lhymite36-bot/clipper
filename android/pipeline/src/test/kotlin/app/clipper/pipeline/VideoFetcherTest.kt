package app.clipper.pipeline

import org.json.JSONArray
import org.json.JSONObject
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.io.OutputStream
import java.nio.file.Files

class VideoFetcherTest {
    private val fakeMp4 = ByteArray(300_000) { if (it < 8) "\u0000\u0000\u0000\u0018ftyp"[it].code.toByte() else (it % 251).toByte() }

    private class FakeHttp(
        val posts: (String, String) -> Http.Resp = { _, _ -> Http.Resp(500, "") },
        val gets: (String) -> Http.Resp = { Http.Resp(503, "") },
        val files: Map<String, ByteArray> = emptyMap(),
    ) : Http {
        val requested = mutableListOf<String>()
        override fun get(url: String, headers: Map<String, String>, timeoutMs: Int): Http.Resp { requested += "GET $url"; return gets(url) }
        override fun post(url: String, json: String, headers: Map<String, String>, timeoutMs: Int): Http.Resp {
            requested += "POST ${JSONObject(json).getJSONObject("context").getJSONObject("client").getString("clientName")}"
            return posts(url, json)
        }
        override fun range(url: String, headers: Map<String, String>, start: Long, endInclusive: Long, out: OutputStream, onBytes: (Long) -> Unit): Http.RangeResult {
            requested += "RANGE $url $start"
            val data = files[url] ?: return Http.RangeResult(403, null, 0, "text/plain")
            if (start >= data.size) return Http.RangeResult(416, data.size.toLong(), 0, null)
            val end = minOf(endInclusive, data.size - 1L).toInt()
            out.write(data, start.toInt(), end - start.toInt() + 1)
            onBytes((end - start + 1))
            return Http.RangeResult(206, data.size.toLong(), end - start + 1, "video/mp4")
        }
    }

    private fun player(status: String, reason: String = "", muxedUrl: String? = null) = JSONObject()
        .put("playabilityStatus", JSONObject().put("status", status).put("reason", reason))
        .put("videoDetails", JSONObject().put("title", "Test video"))
        .apply {
            if (muxedUrl != null) put(
                "streamingData",
                JSONObject().put(
                    "formats",
                    JSONArray().put(JSONObject().put("itag", 18).put("url", muxedUrl).put("mimeType", "video/mp4; codecs=\"avc1\"").put("height", 360)),
                ),
            )
        }.toString()

    private fun fetcher(http: Http, logs: MutableList<String> = mutableListOf()) = VideoFetcher(
        http = http, log = { logs += it }, refreshInstanceLists = false, chunkSize = 100_000,
        pipedInstances = listOf("https://piped.test"), invidiousInstances = listOf("https://inv.test"),
    )

    @Test
    fun downloadsViaYoutubeApiInChunks() {
        val http = FakeHttp(posts = { _, _ -> Http.Resp(200, player("OK", muxedUrl = "https://gv/v18")) }, files = mapOf("https://gv/v18" to fakeMp4))
        val dir = Files.createTempDirectory("fetch")
        val r = fetcher(http).fetch("https://youtube.com/shorts/dQw4w9WgXcQ?si=x", dir)
        assertEquals(fakeMp4.size.toLong(), Files.size(r.path))
        assertEquals("Test video", r.title)
        assertEquals(3, http.requested.count { it.startsWith("RANGE") }, "should download in 100 KB chunks")
    }

    @Test
    fun fallsBackToPipedWhenYoutubeBlocksAndFirstStreamFails() {
        val piped = JSONObject().put("title", "Piped title").put(
            "videoStreams",
            JSONArray().put(JSONObject().put("url", "https://proxy/360").put("mimeType", "video/mp4").put("quality", "360p").put("videoOnly", false)),
        ).toString()
        val http = FakeHttp(
            posts = { _, _ -> Http.Resp(200, player("LOGIN_REQUIRED", "Sign in to confirm you're not a bot")) },
            gets = { if (it.startsWith("https://piped.test/streams/")) Http.Resp(200, piped) else Http.Resp(502, "") },
            files = mapOf("https://proxy/360" to fakeMp4),
        )
        val logs = mutableListOf<String>()
        val r = fetcher(http, logs).fetch("https://youtu.be/dQw4w9WgXcQ", Files.createTempDirectory("fetch"))
        assertTrue(r.via.startsWith("Piped"))
        assertTrue(logs.any { it.contains("Trying YouTube") })
        assertTrue(logs.any { it.contains("Trying Piped") })
    }

    @Test
    fun usesInvidiousProxiedRelativeUrls() {
        val inv = JSONObject().put("title", "Inv").put(
            "formatStreams",
            JSONArray().put(JSONObject().put("url", "/latest_version?id=dQw4w9WgXcQ&itag=18&local=true").put("type", "video/mp4; codecs=\"avc1\"").put("resolution", "360p")),
        ).toString()
        val http = FakeHttp(
            gets = { if (it.startsWith("https://inv.test/api/v1/videos/")) Http.Resp(200, inv) else Http.Resp(500, "{\"error\":\"down\"}") },
            files = mapOf("https://inv.test/latest_version?id=dQw4w9WgXcQ&itag=18&local=true" to fakeMp4),
        )
        val r = fetcher(http).fetch("dQw4w9WgXcQ", Files.createTempDirectory("fetch"))
        assertTrue(r.via.startsWith("Invidious"))
    }

    @Test
    fun clearErrorWhenEverythingFails() {
        val http = FakeHttp(posts = { _, _ -> Http.Resp(200, player("ERROR", "Video unavailable")) })
        val e = assertThrows<FetchFailed> { fetcher(http).fetch("https://www.youtube.com/watch?v=dQw4w9WgXcQ", Files.createTempDirectory("f")) }
        assertTrue(e.message!!.contains("Video unavailable"), e.message)
        assertTrue(e.message!!.contains("Pick a file"))
        assertTrue(e.attempts.isNotEmpty())
    }

    @Test
    fun rejectsHtmlErrorPages() {
        val html = ("<html>" + "x".repeat(50_000)).toByteArray()
        val http = FakeHttp(posts = { _, _ -> Http.Resp(200, player("OK", muxedUrl = "https://gv/bad")) }, files = mapOf("https://gv/bad" to html))
        assertThrows<FetchFailed> { fetcher(http).fetch("dQw4w9WgXcQ", Files.createTempDirectory("f")) }
    }

    @Test
    fun otherSitesGetAPlainMessage() {
        val e = assertThrows<FetchFailed> { fetcher(FakeHttp()).fetch("https://www.instagram.com/reel/abc/", Files.createTempDirectory("f")) }
        assertTrue(e.message!!.contains("Pick a file"))
    }
}
