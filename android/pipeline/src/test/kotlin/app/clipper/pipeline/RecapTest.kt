package app.clipper.pipeline

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class RecapTest {
    @Test
    fun shortScriptStaysInRange() {
        val s = RecapScript.heuristic("Sintel", "A girl searches for a baby dragon.", JobKind.RECAP_SHORT)
        val words = s.split(Regex("\\s+")).size
        assertTrue(words in 80..160, "word count $words")
    }

    @Test
    fun longScriptStretchesTowardTarget() {
        val s = RecapScript.heuristic("Sintel", "A girl searches for a baby dragon in a vast world.", JobKind.RECAP_LONG)
        val words = s.split(Regex("\\s+")).size
        assertTrue(words in 900..1300, "word count $words")
    }

    @Test
    fun shotsStayBetweenTwoAndFiveSeconds() {
        val shots = Scenes.pack(audioDur = 52.0, sourceDur = 888.0)
        assertTrue(shots.isNotEmpty())
        for (sh in shots) {
            val d = sh.end - sh.start
            assertTrue(d in 1.9..5.15, "shot $d")
        }
        val covered = shots.last().end
        assertTrue(covered >= 51.0)
    }
}
