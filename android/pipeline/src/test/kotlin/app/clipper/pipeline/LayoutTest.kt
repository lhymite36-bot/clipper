package app.clipper.pipeline

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class LayoutTest {
    @Test
    fun fillUsesBlurAndSharpOverlay() {
        val f = LayoutVt.fill(1080, 1920, hookBar = true)
        assertTrue(f.contains("boxblur"))
        assertTrue(f.contains("overlay"))
        assertTrue(f.contains("1080"))
        assertTrue(f.contains("1920"))
        assertFalse(f.contains("hflip"))
        assertFalse(f.contains("1.05"))
        // Sharp layer keeps the source aspect (16:9 sits over the blur), it is not cropped to 9:16.
        assertTrue(f.contains("force_original_aspect_ratio=decrease"))
        assertFalse(Regex("\\[fg\\]scale=1080:1920:force_original_aspect_ratio=increase").containsMatchIn(f))
    }

    @Test
    fun recapShortDucksMusic() {
        val f = LayoutVt.recapFilter(isShort = true, width = 1080, height = 1920, music = true)
        assertTrue(f.contains("sidechaincompress"))
        assertTrue(f.contains("loudnorm"))
        assertFalse(f.contains("hflip"))
    }

    @Test
    fun longIsSixteenNine() {
        val f = LayoutVt.longWide(1920, 1080)
        assertTrue(f.contains("1920"))
        assertTrue(f.contains("1080"))
        assertTrue(f.contains("eq=contrast"))
    }
}
