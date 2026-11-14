package app.clipper.pipeline

import org.json.JSONObject
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class GroqParseTest {
    @Test
    fun parsesVerboseJsonWords() {
        val o = JSONObject("""{"language":"en","text":"hello world","words":[{"word":"hello","start":0.0,"end":0.4},{"word":"world","start":0.4,"end":0.9}]}""")
        val t = GroqTranscriber.parseVerbose(o)
        assertEquals("hello world", t.text)
        assertEquals(2, t.words.size)
        assertEquals(0.4, t.words[0].end)
    }
}
