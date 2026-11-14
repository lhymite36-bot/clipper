package app.clipper.pipeline

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class MomentsTest {
    private fun words(text: String, start: Double = 0.0, pace: Double = 0.4): Transcript {
        val list = mutableListOf<TranscriptWord>()
        var t = start
        for (w in text.split(" ")) {
            list += TranscriptWord(t, t + pace, w)
            t += pace
        }
        return Transcript("en", text, list)
    }

    @Test
    fun picksWindowsAroundHookWords() {
        val t = words(
            "hello there everyone this is a calm intro " +
                "wait what just happened this is crazy insane never seen before " +
                "and later we walk quietly through the garden path again " +
                "oh no the door slams boom what a payoff for the crowd"
        )
        val dur = t.words.last().end
        val moments = Moments.pick(t, dur, count = 2, minLen = 8.0, maxLen = 20.0)
        assertTrue(moments.isNotEmpty())
        assertTrue(moments.all { it.duration >= 7.9 })
        assertTrue(moments.any { it.hook.contains("Wait", true) || it.hook.contains("What", true) || it.reason == "heuristic" })
    }

    @Test
    fun energyFallbackWithoutWords() {
        val peaks = listOf(10.0 to 1.2, 40.0 to 0.8)
        val ms = Moments.pick(Transcript(), 60.0, count = 2, peaks = peaks)
        assertEquals(2, ms.size)
        assertTrue(ms.first().start < 15.0)
    }
}
