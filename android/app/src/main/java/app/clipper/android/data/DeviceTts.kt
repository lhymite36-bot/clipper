package app.clipper.android.data

import android.content.Context
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.io.File
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** On-device Android TTS. Used when no Gemini TTS key is set. One consistent voice per recap. */
class DeviceTts(context: Context) {
    private val app = context.applicationContext

    fun synthesize(text: String, outFile: File, voiceName: String? = null): File {
        outFile.parentFile?.mkdirs()
        val latchReady = CountDownLatch(1)
        var error: String? = null
        val tts = TextToSpeech(app) { status ->
            if (status != TextToSpeech.SUCCESS) error = "TTS init failed"
            latchReady.countDown()
        }
        latchReady.await(15, TimeUnit.SECONDS)
        if (error != null) {
            tts.shutdown()
            error(error!!)
        }
        tts.language = Locale.US
        voiceName?.let { want ->
            tts.voices?.firstOrNull { it.name.contains(want, true) }?.let { tts.voice = it }
        }
        val done = CountDownLatch(1)
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}
            override fun onDone(utteranceId: String?) { done.countDown() }
            @Deprecated("deprecated")
            override fun onError(utteranceId: String?) {
                error = "TTS failed"
                done.countDown()
            }
        })
        val code = tts.synthesizeToFile(text, null, outFile, "clipper-recap")
        if (code != TextToSpeech.SUCCESS) {
            tts.shutdown()
            error("TTS could not start")
        }
        done.await(5, TimeUnit.MINUTES)
        tts.shutdown()
        if (error != null) error(error!!)
        if (!outFile.exists() || outFile.length() < 100) error("TTS produced no audio")
        return outFile
    }
}
