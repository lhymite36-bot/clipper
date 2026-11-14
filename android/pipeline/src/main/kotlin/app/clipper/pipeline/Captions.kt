package app.clipper.pipeline

object Captions {
    const val YT_TOP_SAFE = 180  // keep hook below YouTube UI
    const val HOOK_FONT = "Anton"
    const val BODY_FONT = "Montserrat"

    fun assForClip(
        events: List<CaptionEvent>,
        width: Int = 1080,
        height: Int = 1920,
        hook: String? = null,
        hookUntil: Double = 3.0,
    ): String {
        val sb = StringBuilder()
        sb.append(
            """[Script Info]
Title: Clipper
ScriptType: v4.00+
PlayResX: $width
PlayResY: $height
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,$HOOK_FONT,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,0,8,40,40,$YT_TOP_SAFE,1
Style: Body,$BODY_FONT,54,&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,5,0,2,50,50,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        )
        if (!hook.isNullOrBlank()) {
            sb.append("Dialogue: 0,${ts(0.0)},${ts(hookUntil)},Hook,,0,0,0,,${esc(hook.uppercase())}\n")
        }
        for (e in events) {
            if (e.hook) continue
            val text = e.text.trim()
            if (text.isBlank()) continue
            sb.append("Dialogue: 0,${ts(e.start)},${ts(e.end)},Body,,0,0,0,,${esc(text)}\n")
        }
        return sb.toString()
    }

    fun assForRecap(
        events: List<CaptionEvent>,
        width: Int,
        height: Int,
        hook: String?,
        isShort: Boolean,
    ): String {
        val hookMargin = if (isShort) YT_TOP_SAFE else 40
        val alignHook = if (isShort) 8 else 8
        val bodyAlign = 2
        val bodyMarginV = if (isShort) 220 else 80
        val sb = StringBuilder()
        sb.append(
            """[Script Info]
Title: Clipper Recap
ScriptType: v4.00+
PlayResX: $width
PlayResY: $height
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,$HOOK_FONT,${if (isShort) 72 else 64},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,0,$alignHook,40,40,$hookMargin,1
Style: Body,$BODY_FONT,${if (isShort) 54 else 48},&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,5,0,$bodyAlign,50,50,$bodyMarginV,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        )
        if (isShort && !hook.isNullOrBlank()) {
            sb.append("Dialogue: 0,${ts(0.0)},${ts(3.0)},Hook,,0,0,0,,${esc(hook.uppercase())}\n")
        }
        for (e in events) {
            val text = e.text.trim()
            if (text.isBlank()) continue
            sb.append("Dialogue: 0,${ts(e.start)},${ts(e.end)},Body,,0,0,0,,${esc(text)}\n")
        }
        return sb.toString()
    }

    fun eventsFromWords(words: List<TranscriptWord>, windowStart: Double, windowEnd: Double, chunk: Int = 3): List<CaptionEvent> {
        val inWin = words.filter { it.end > windowStart && it.start < windowEnd }
        if (inWin.isEmpty()) return emptyList()
        val events = mutableListOf<CaptionEvent>()
        var i = 0
        while (i < inWin.size) {
            val group = inWin.subList(i, (i + chunk).coerceAtMost(inWin.size))
            val start = (group.first().start - windowStart).coerceAtLeast(0.0)
            val end = (group.last().end - windowStart).coerceAtLeast(start + 0.35)
            val text = group.joinToString(" ") { it.word }.trim()
            events += CaptionEvent(start, end, text)
            i += chunk
        }
        return events
    }

    fun eventsFromScript(script: String, totalDur: Double): List<CaptionEvent> {
        val tokens = script.split(Regex("\\s+")).filter { it.isNotBlank() }
        if (tokens.isEmpty() || totalDur <= 0) return emptyList()
        val per = totalDur / tokens.size
        val events = mutableListOf<CaptionEvent>()
        var i = 0
        while (i < tokens.size) {
            val group = tokens.subList(i, (i + 3).coerceAtMost(tokens.size))
            val start = i * per
            val end = ((i + group.size) * per).coerceAtMost(totalDur)
            events += CaptionEvent(start, maxOf(end, start + 0.2), group.joinToString(" "))
            i += group.size
        }
        return events
    }

    fun ts(sec: Double): String {
        val s = sec.coerceAtLeast(0.0)
        val h = (s / 3600).toInt()
        val m = ((s % 3600) / 60).toInt()
        val rest = s % 60
        val whole = rest.toInt()
        val cs = ((rest - whole) * 100).toInt().coerceIn(0, 99)
        return "%d:%02d:%02d.%02d".format(h, m, whole, cs)
    }

    private fun esc(text: String): String =
        text.replace("\\", "\\\\").replace("\n", "\\N").replace("{", "\\{").replace("}", "\\}")
}
