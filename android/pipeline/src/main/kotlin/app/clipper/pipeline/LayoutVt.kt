package app.clipper.pipeline

object LayoutVt {
    /**
     * FFmpeg filter graph for a single clip or recap short (9:16 fill by default).
     * Fill: mild 1.5x zoom of a blurred 16:9 under the hook bar, sharp centre crop.
     */
    fun clipFilter(
        layout: Layout,
        width: Int = 1080,
        height: Int = 1920,
        hookBar: Boolean = true,
        includeAudio: Boolean = true,
        music: Boolean = false,
        sfx: Boolean = false,
    ): String {
        val video = when (layout) {
            Layout.BARS -> bars(width, height)
            Layout.TIGHT -> tight(width, height)
            Layout.FILL -> fill(width, height, hookBar)
        }
        val audio = audioChain(includeAudio, music, sfx)
        return if (audio.isBlank()) video else "$video;$audio"
    }

    fun recapFilter(isShort: Boolean, width: Int, height: Int, music: Boolean): String {
        val video = if (isShort) fill(width, height, hookBar = true) else longWide(width, height)
        val audio = if (music) {
            "[1:a]volume=1.0,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[vo];" +
                "[2:a]volume=0.12,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[mus];" +
                "[vo][mus]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=250,loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
        } else {
            "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
        }
        return "$video;$audio"
    }

    fun fill(width: Int, height: Int, hookBar: Boolean): String {
        // Blurred 9:16 backdrop (mild 1.5x zoom) + sharp 16:9 column centered under the hook bar.
        val zoom = 1.5
        val bgW = (width * zoom).toInt()
        val bgH = (height * zoom).toInt()
        return "[0:v]split=2[bg][fg];" +
            "[bg]scale=${bgW}:${bgH}:force_original_aspect_ratio=increase,crop=$bgW:$bgH,boxblur=20:8,scale=$width:$height[bb];" +
            "[fg]scale=$width:-2:force_original_aspect_ratio=decrease[sharp];" +
            "[bb][sharp]overlay=(W-w)/2:(H-h)/2,format=yuv420p[vout]"
    }

    fun bars(width: Int, height: Int): String =
        "[0:v]scale=$width:$height:force_original_aspect_ratio=decrease," +
            "pad=$width:$height:(ow-iw)/2:(oh-ih)/2,format=yuv420p[vout]"

    fun tight(width: Int, height: Int): String =
        "[0:v]scale=$width:$height:force_original_aspect_ratio=increase,crop=$width:$height,format=yuv420p[vout]"

    fun longWide(width: Int, height: Int): String {
        // 16:9 long recap: gentle zoom + grade
        return "[0:v]scale=$width:$height:force_original_aspect_ratio=increase,crop=$width:$height," +
            "eq=contrast=1.04:saturation=1.08,format=yuv420p[vout]"
    }

    private fun audioChain(includeAudio: Boolean, music: Boolean, sfx: Boolean): String {
        if (!includeAudio) return ""
        // input 0 = video+orig, 1 = music optional, 2 = sfx optional
        return when {
            music && sfx ->
                "[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,volume=1.0[oa];" +
                    "[1:a]volume=0.14[mus];[2:a]volume=0.5[fx];" +
                    "[oa][mus]amix=inputs=2:duration=first:dropout_transition=2[mix];" +
                    "[mix][fx]amix=inputs=2:duration=first:dropout_transition=1,loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
            music ->
                "[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[oa];" +
                    "[1:a]volume=0.14[mus];" +
                    "[oa][mus]amix=inputs=2:duration=first:dropout_transition=2,loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
            else -> "[0:a]loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
        }
    }
}
