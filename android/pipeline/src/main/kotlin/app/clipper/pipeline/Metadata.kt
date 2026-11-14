package app.clipper.pipeline

object Metadata {
    private val BLOCK_TAGS = setOf(
        "fyp", "foryou", "foryoupage", "viral", "xyzbca", "fy", "fypシ",
    )
    private val SOUND_CUES = listOf(
        Regex("(?i)\\b(boom|bang|crash|slap|punch|scream|wow|oh no|oh my|wait|what|no way)\\b"),
        Regex("(?i)\\b(laugh|cheer|gasp|applause)\\b"),
    )
    private val GENERIC = setOf(
        "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "is", "it", "this", "that",
        "you", "we", "they", "i", "he", "she", "for", "with", "at", "as", "be", "was", "were",
        "are", "not", "so", "if", "just", "like", "from", "my", "your", "our",
    )
    private val TRAILING_JUNK = Regex("(?i)[\\s,;:]+(subscribe|like and subscribe|follow for more|link in bio)+\\s*$")

    fun sentenceCase(text: String): String {
        val cleaned = TRAILING_JUNK.replace(text.trim(), "").trim().trim('"', '\'', '“', '”')
        if (cleaned.isBlank()) return cleaned
        val lower = cleaned.lowercase()
        return lower.replaceFirstChar { it.titlecase() }
    }

    fun hookFrom(text: String, maxWords: Int = 8): String {
        val words = text.replace(Regex("[\\r\\n]+"), " ")
            .replace(Regex("[^\\w'\\s?]"), " ")
            .trim()
            .split(Regex("\\s+"))
            .filter { it.isNotBlank() }
        if (words.isEmpty()) return "Wait for it"
        val cut = words.take(maxWords).joinToString(" ")
        return sentenceCase(cut).trimEnd('.', ',', ';', ':')
    }

    fun titleFrom(hook: String, transcriptSlice: String): String {
        val base = hook.ifBlank { hookFrom(transcriptSlice) }
        val titled = sentenceCase(base)
        return if (titled.length <= 70) titled else titled.take(67).trimEnd() + "…"
    }

    fun hashtags(text: String, extra: List<String> = emptyList()): List<String> {
        val counts = mutableMapOf<String, Int>()
        val tokens = text.lowercase().replace(Regex("[^a-z0-9\\s]"), " ").split(Regex("\\s+"))
        for (t in tokens) {
            if (t.length < 4 || t in GENERIC || t in BLOCK_TAGS) continue
            counts[t] = (counts[t] ?: 0) + 1
        }
        val picked = counts.entries.sortedByDescending { it.value }.take(5).map { it.key }
        val all = (extra + picked).map { it.trim().trimStart('#').lowercase() }
            .filter { it.isNotBlank() && it !in BLOCK_TAGS }
            .distinct()
            .take(8)
        return all.map { "#$it" }
    }

    fun description(title: String, hook: String, tags: List<String>, sourceUrl: String? = null, license: String? = null): String {
        val lines = mutableListOf<String>()
        lines += sentenceCase(title)
        if (hook.isNotBlank() && !title.equals(hook, ignoreCase = true)) {
            lines += sentenceCase(hook)
        }
        val tagLine = tags.filter { it.trimStart('#').lowercase() !in BLOCK_TAGS }.joinToString(" ")
        if (tagLine.isNotBlank()) lines += tagLine
        if (!sourceUrl.isNullOrBlank()) lines += "Source: $sourceUrl"
        if (!license.isNullOrBlank()) lines += "Licence: $license"
        return lines.joinToString("\n")
    }

    fun hasSoundPayoff(text: String): Boolean = SOUND_CUES.any { it.containsMatchIn(text) }

    fun sfxHits(words: List<TranscriptWord>, windowStart: Double): List<Double> {
        val hits = mutableListOf<Double>()
        for (w in words) {
            if (SOUND_CUES.any { it.containsMatchIn(w.word) }) {
                hits += (w.start - windowStart).coerceAtLeast(0.0)
            }
        }
        return hits.distinct().take(6)
    }
}
