package app.clipper.pipeline

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class MetadataTest {
    @Test
    fun sentenceCaseAndBlockedTags() {
        assertEquals("Wait for it", Metadata.sentenceCase("WAIT FOR IT"))
        val tags = Metadata.hashtags("this viral fyp smile typhoid hospital story smile")
        assertTrue(tags.none { it.equals("#fyp", true) || it.equals("#viral", true) })
        assertTrue(tags.any { it.contains("smile") || it.contains("hospital") || it.contains("typhoid") })
    }

    @Test
    fun descriptionIncludesSourceAndLicence() {
        val d = Metadata.description(
            "Is that a smile",
            "Is that a smile",
            listOf("#history"),
            sourceUrl = "https://youtube.com/watch?v=abc",
            license = "CC BY 3.0",
        )
        assertTrue(d.contains("Source: https://youtube.com/watch?v=abc"))
        assertTrue(d.contains("Licence: CC BY 3.0"))
    }

    @Test
    fun hookIsShort() {
        val hook = Metadata.hookFrom("Wait until you see what happens when the typhoid ward opens the door")
        assertTrue(hook.split(" ").size <= 8)
        assertFalse(hook.startsWith("WAIT ") && hook == hook.uppercase()) // sentence case, not all-caps
    }

    @Test
    fun soundPayoffDetected() {
        assertTrue(Metadata.hasSoundPayoff("and then boom it happens"))
        assertFalse(Metadata.hasSoundPayoff("a quiet walk in the park"))
    }
}
