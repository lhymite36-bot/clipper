package app.clipper.pipeline

import java.nio.file.Files
import java.nio.file.Path
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.PI
import kotlin.math.sin

/**
 * Copyright-safe beds: we generate a short original wav loop (never rip YouTube audio).
 * Same idea as the desktop Clipper library / generated beds.
 */
object Music {
    fun generateBed(output: Path, seconds: Double = 20.0, bpm: Int = 96, sr: Int = 44100) {
        Files.createDirectories(output.parent)
        val n = (seconds * sr).toInt()
        val samples = ShortArray(n)
        val freqRoot = 196.0 // G3
        val beat = 60.0 / bpm
        for (i in 0 until n) {
            val t = i.toDouble() / sr
            val env = 0.35 * (0.55 + 0.45 * sin(2 * PI * t / 4.0))
            val bass = sin(2 * PI * freqRoot * t)
            val fifth = 0.4 * sin(2 * PI * freqRoot * 1.5 * t)
            val hat = if ((t % beat) < 0.03) 0.15 * (1.0 - (t % beat) / 0.03) * ((i % 7) / 7.0 - 0.5) else 0.0
            val v = ((bass + fifth) * env + hat).coerceIn(-0.95, 0.95)
            samples[i] = (v * 30000).toInt().toShort()
        }
        writeWav(output, samples, sr)
    }

    fun generateClick(output: Path, sr: Int = 44100) {
        val n = (0.09 * sr).toInt()
        val samples = ShortArray(n)
        for (i in 0 until n) {
            val env = 1.0 - i.toDouble() / n
            val v = sin(2 * PI * 1200 * i / sr) * env * env
            samples[i] = (v * 20000).toInt().toShort()
        }
        writeWav(output, samples)
    }

    private fun writeWav(path: Path, samples: ShortArray, sr: Int = 44100) {
        val dataBytes = samples.size * 2
        val buf = ByteBuffer.allocate(44 + dataBytes).order(ByteOrder.LITTLE_ENDIAN)
        buf.put("RIFF".toByteArray())
        buf.putInt(36 + dataBytes)
        buf.put("WAVE".toByteArray())
        buf.put("fmt ".toByteArray())
        buf.putInt(16)
        buf.putShort(1) // PCM
        buf.putShort(1) // mono
        buf.putInt(sr)
        buf.putInt(sr * 2)
        buf.putShort(2)
        buf.putShort(16)
        buf.put("data".toByteArray())
        buf.putInt(dataBytes)
        val pcm = ByteBuffer.allocate(dataBytes).order(ByteOrder.LITTLE_ENDIAN)
        samples.forEach { pcm.putShort(it) }
        buf.put(pcm.array())
        Files.write(path, buf.array())
    }
}
