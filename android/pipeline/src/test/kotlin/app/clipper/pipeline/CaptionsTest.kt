package app.clipper.pipeline

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class CaptionsTest {
    @Test
    fun assHasHookStyleAndSafeMargin() {
        val ev = listOf(CaptionEvent(3.0, 5.0, "hello world"))
        val ass = Captions.assForClip(ev, hook = "Wait for it")
        assertTrue(ass.contains("Style: Hook,Anton"))
        assertTrue(ass.contains("Style: Body,Montserrat"))
        assertTrue(ass.contains(",180,1")) // YT_TOP_SAFE margin
        assertTrue(ass.contains("WAIT FOR IT"))
        assertTrue(ass.contains("0:00:00.00"))
        assertFalse(ass.contains("hflip"))
        assertFalse(ass.contains("PLAY_SPEED"))
    }

    @Test
    fun longRecapHasNoHookBar() {
        val ev = Captions.eventsFromScript("One two three four five six", 6.0)
        assertTrue(ev.isNotEmpty())
        val ass = Captions.assForRecap(ev, 1920, 1080, hook = "Ignore me", isShort = false)
        assertFalse(ass.contains("Dialogue: 0,0:00:00.00,0:00:03.00,Hook"))
        val shortAss = Captions.assForRecap(ev, 1080, 1920, hook = "Watch this", isShort = true)
        assertTrue(shortAss.contains("WATCH THIS"))
    }

    @Test
    fun timestampFormat() {
        assertEquals("0:00:03.50", Captions.ts(3.5))
        assertEquals("0:01:00.00", Captions.ts(60.0))
    }
}
