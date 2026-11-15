package app.clipper.pipeline

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class YoutubeUrlTest {
    private fun id(s: String) = (YoutubeUrl.parse(s) as? YoutubeUrl.Parsed.YouTube)?.videoId

    @Test
    fun parsesEveryCommonYoutubeForm() {
        val v = "dQw4w9WgXcQ"
        listOf(
            "https://www.youtube.com/watch?v=$v",
            "https://youtube.com/watch?v=$v&t=42s",
            "https://m.youtube.com/watch?v=$v&feature=share",
            "https://music.youtube.com/watch?v=$v&list=RDAMVM",
            "https://www.youtube.com/watch?feature=share&v=$v",
            "https://youtu.be/$v",
            "https://youtu.be/$v?si=AbCdEf123",
            "https://youtube.com/shorts/$v?si=xyz",
            "https://www.youtube.com/shorts/$v",
            "https://m.youtube.com/shorts/$v",
            "https://www.youtube.com/live/$v?feature=share",
            "https://www.youtube.com/embed/$v",
            "https://www.youtube-nocookie.com/embed/$v",
            "youtube.com/shorts/$v",
            "youtu.be/$v",
            "  https://youtu.be/$v  ",
            "Check this out! https://youtube.com/shorts/$v?si=abc",
            "HTTPS://YOUTU.BE/$v",
            v,
        ).forEach { assertEquals(v, id(it), it) }
    }

    @Test
    fun rejectsNonVideoInput() {
        assertTrue(YoutubeUrl.parse("") is YoutubeUrl.Parsed.Invalid)
        assertTrue(YoutubeUrl.parse("hello there") is YoutubeUrl.Parsed.Invalid)
        assertTrue(YoutubeUrl.parse("https://www.youtube.com/@MrBeast") is YoutubeUrl.Parsed.Invalid)
        assertTrue(YoutubeUrl.parse("https://www.tiktok.com/@a/video/123") is YoutubeUrl.Parsed.OtherSite)
        assertTrue(YoutubeUrl.parse("https://example.com/clip.mp4?x=1") is YoutubeUrl.Parsed.DirectFile)
    }
}
