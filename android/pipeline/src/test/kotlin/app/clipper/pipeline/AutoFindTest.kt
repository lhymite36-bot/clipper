package app.clipper.pipeline

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Path

class AutoFindTest {
    @TempDir lateinit var tmp: Path

    private fun fakeRunner(stdout: String, exit: Int = 0) = CommandRunner { args, _ ->
        lastArgs = args
        CommandResult(exit, stdout, "")
    }

    private var lastArgs: List<String> = emptyList()

    @Test
    fun keywordSearchUsesYtDlpAndOptionalCcFilter() {
        val af = AutoFind(tmp, CommandRunner { args, _ -> CommandResult(0, "", "") })
        val args = af.ytDlpSearchArgs("funny cats", ccOnly = true, maxItems = 10)
        assertTrue(args[0].contains("yt-dlp"))
        assertTrue(args.any { it.startsWith("ytsearch") && it.contains("funny cats") })
        assertTrue(args.contains("--match-filter"))
        assertTrue(args.any { it.contains("Creative Commons") })
        val noCc = af.ytDlpSearchArgs("funny cats", ccOnly = false)
        assertFalse(noCc.contains("--match-filter"))
    }

    @Test
    fun trailerQueryAndBriefDetection() {
        val af = AutoFind(tmp, CommandRunner { args, _ -> CommandResult(0, "", "") })
        assertEquals("ytsearch5:Sintel official trailer", af.trailerSearchQuery("Sintel"))
        assertTrue(AutoFind.looksLikeBriefUrl("https://app.contentrewards.com/campaigns/abc"))
        assertTrue(AutoFind.looksLikeBriefUrl("https://vyro.ai/brief/1"))
        assertTrue(AutoFind.looksLikeBriefUrl("https://clipster.io/x"))
        assertTrue(AutoFind.looksLikeBriefUrl("https://indclip.com/b/1"))
        assertFalse(AutoFind.looksLikeBriefUrl("https://youtube.com/watch?v=aaaaaaaaaaa"))
    }

    @Test
    fun dedupeAndDailyCap() {
        val json = """
            {"id":"aaaaaaaaaaa","title":"One","webpage_url":"https://youtu.be/aaaaaaaaaaa","license":"Creative Commons"}
            {"id":"bbbbbbbbbbb","title":"Two","webpage_url":"https://youtu.be/bbbbbbbbbbb","license":""}
        """.trimIndent()
        val runner = fakeRunner(json)
        val af = AutoFind(tmp, runner, dailyCap = 1)
        af.addSource(WatchSource(id = "s1", kind = SourceKind.KEYWORD, query = "cats", label = "cats"))
        val first = af.discover()
        assertEquals(1, first.size, "daily cap 1")
        af.markSeen(first.map { it.videoId })
        af.recordUsed(first.size)
        val second = af.discover()
        assertTrue(second.isEmpty(), "already at cap")
        // Next day wouldn't flip here; same-day cap is the contract.
    }

    @Test
    fun licenseNormalizedAndQueueFieldsRoundTrip(@TempDir qdir: Path) {
        assertEquals("Creative Commons", AutoFind.normalizeLicense("creative commons"))
        val store = QueueStore(qdir.resolve("queue.json"))
        val item = store.enqueue(
            path = qdir.resolve("out.mp4"),
            title = "Is that a smile",
            description = "Is that a smile\nLicence: CC BY 3.0",
            tags = listOf("#history"),
            hook = "Is that a smile",
            sourceUrl = "https://youtu.be/aaaaaaaaaaa",
            sourceLabel = "Watched: AIB",
            license = "CC BY 3.0",
            foundBy = "keyword",
        )
        assertEquals(QueueStatus.PENDING_REVIEW, item.status)
        val loaded = store.all().single()
        assertEquals("CC BY 3.0", loaded.license)
        assertEquals("Watched: AIB", loaded.sourceLabel)
        assertEquals("keyword", loaded.foundBy)
        assertEquals(QueueStatus.PENDING_REVIEW, loaded.status)
        // Autopilot off means we never auto-flip to posted
        assertNotEquals(QueueStatus.POSTED, loaded.status)
    }

    @Test
    fun autopilotStillLandsAsApprovedNotPosted(@TempDir qdir: Path) {
        val store = QueueStore(qdir.resolve("queue.json"))
        val item = store.enqueue(
            path = qdir.resolve("out.mp4"),
            title = "X",
            description = "X",
            tags = emptyList(),
            hook = "X",
            autopilot = true,
        )
        assertEquals(QueueStatus.APPROVED, item.status)
    }

    @Test
    fun videoIdFromUrl() {
        assertEquals("dQw4w9WgXcQ", AutoFind.videoIdFromUrl("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        assertEquals("dQw4w9WgXcQ", AutoFind.videoIdFromUrl("https://youtu.be/dQw4w9WgXcQ"))
    }
}
