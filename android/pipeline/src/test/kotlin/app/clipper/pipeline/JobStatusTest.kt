package app.clipper.pipeline

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.nio.file.Files

class JobStatusTest {
    @Test
    fun recordsStepsProgressAndErrors() {
        val dir = Files.createTempDirectory("status")
        val s = JobStatus(dir.resolve("job-status.json"))
        assertEquals(JobStatus.State.IDLE, s.read().state)
        s.start("Starting")
        s.log("Trying YouTube")
        s.percent(40)
        assertEquals(40, s.read().percent)
        s.failed("Couldn't download")
        val snap = s.read()
        assertEquals(JobStatus.State.FAILED, snap.state)
        assertEquals("Couldn't download", snap.message)
        assertTrue(snap.log.last().contains("ERROR: Couldn't download"))
        assertEquals(3, snap.log.size)
    }
}
