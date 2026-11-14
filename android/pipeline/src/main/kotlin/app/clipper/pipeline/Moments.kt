package app.clipper.pipeline

object Moments {
    private val HOOK_WORDS = listOf(
        "wait", "what", "wow", "insane", "crazy", "never", "secret", "actually",
        "because", "but", "however", "suddenly", "then", "oh", "no", "yes",
        "look", "watch", "check", "happened", "truth", "why", "how",
    )

    /**
     * Heuristic moment picker used when no Gemini/Groq key is set, and as a fallback.
     * Scores rolling windows by hook words, punctuation, and optional loudness peaks.
     */
    fun pick(
        transcript: Transcript,
        duration: Double,
        count: Int = 3,
        minLen: Double = 12.0,
        maxLen: Double = 45.0,
        peaks: List<Pair<Double, Double>> = emptyList(),
        preferPayoff: Boolean = true,
    ): List<Moment> {
        if (duration <= 0.0) return emptyList()
        val words = transcript.words
        if (words.isEmpty()) {
            return energyOnly(duration, count, minLen, maxLen, peaks)
        }
        val target = ((minLen + maxLen) / 2.0).coerceIn(minLen, maxLen)
        val candidates = mutableListOf<Moment>()
        var i = 0
        while (i < words.size) {
            val start = words[i].start
            var j = i
            while (j < words.size && words[j].end - start < target) j++
            if (j >= words.size) j = words.size - 1
            var end = words[j].end
            if (end - start < minLen) {
                end = (start + minLen).coerceAtMost(duration)
            }
            if (end - start > maxLen) end = start + maxLen
            val text = transcript.textIn(start, end)
            if (text.isBlank()) {
                i++
                continue
            }
            val score = scoreWindow(text, start, end, peaks)
            val hook = Metadata.hookFrom(text)
            candidates += Moment(start, end, hook, reason = "heuristic", score = score)
            // step ~ half a window
            val stepTo = start + target / 2.0
            val next = words.indexOfFirst { it.start >= stepTo }
            i = if (next <= i) i + 1 else next
        }
        val ranked = candidates.sortedByDescending { it.score }
        val picked = mutableListOf<Moment>()
        for (c in ranked) {
            if (picked.size >= count) break
            if (picked.any { overlap(it, c) > 0.45 }) continue
            if (preferPayoff && Metadata.hasSoundPayoff(transcript.textIn(c.start, c.end))) {
                picked.add(0, c)
            } else {
                picked += c
            }
        }
        return picked.take(count).sortedBy { it.start }
    }

    private fun energyOnly(
        duration: Double,
        count: Int,
        minLen: Double,
        maxLen: Double,
        peaks: List<Pair<Double, Double>>,
    ): List<Moment> {
        val len = ((minLen + maxLen) / 2.0)
        if (peaks.isEmpty()) {
            val start = 0.0
            val end = len.coerceAtMost(duration)
            return listOf(Moment(start, end, "Wait for it", "fallback-start", 0.1))
        }
        return peaks.sortedByDescending { it.second }.take(count).map { (t, s) ->
            val start = (t - 2.0).coerceAtLeast(0.0)
            val end = (start + len).coerceAtMost(duration)
            Moment(start, end, "Wait for it", "loudness", s)
        }.sortedBy { it.start }
    }

    private fun scoreWindow(text: String, start: Double, end: Double, peaks: List<Pair<Double, Double>>): Double {
        val lower = text.lowercase()
        var score = 0.0
        for (w in HOOK_WORDS) if (Regex("\\b${Regex.escape(w)}\\b").containsMatchIn(lower)) score += 1.2
        if (text.contains('?')) score += 1.5
        if (text.contains('!')) score += 0.8
        if (Metadata.hasSoundPayoff(text)) score += 2.0
        val words = text.split(Regex("\\s+")).filter { it.isNotBlank() }
        score += (words.size / 40.0).coerceAtMost(1.5)
        for ((t, energy) in peaks) {
            if (t in start..end) score += energy * 0.5
        }
        return score
    }

    private fun overlap(a: Moment, b: Moment): Double {
        val s = maxOf(a.start, b.start)
        val e = minOf(a.end, b.end)
        val inter = (e - s).coerceAtLeast(0.0)
        val union = (maxOf(a.end, b.end) - minOf(a.start, b.start)).coerceAtLeast(0.0001)
        return inter / union
    }
}
