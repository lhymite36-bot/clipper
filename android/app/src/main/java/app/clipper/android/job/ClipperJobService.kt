package app.clipper.android.job

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import app.clipper.android.ClipperApp
import app.clipper.android.R
import app.clipper.android.data.DeviceTts
import app.clipper.android.data.FfmpegKitRunner
import app.clipper.android.data.YoutubeDlRunner
import app.clipper.android.data.fontsDir
import app.clipper.android.data.queueFile
import app.clipper.android.data.workRoot
import app.clipper.pipeline.Ffmpeg
import app.clipper.pipeline.GroqTranscriber
import app.clipper.pipeline.JobKind
import app.clipper.pipeline.Pipeline
import app.clipper.pipeline.QueueStore
import java.nio.file.Path
import kotlin.concurrent.thread

/**
 * Foreground service for long recaps and one-off clip jobs so they survive
 * the app moving to the background on a budget phone.
 */
class ClipperJobService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val title = intent?.getStringExtra(EXTRA_TITLE) ?: "Clipper is working"
        startAsForeground(title)
        val kind = intent?.getStringExtra(EXTRA_KIND) ?: KIND_CLIP
        val source = intent?.getStringExtra(EXTRA_SOURCE) ?: return startAndStop()
        val recapTitle = intent?.getStringExtra(EXTRA_RECAP_TITLE) ?: "Recap"
        val url = intent?.getStringExtra(EXTRA_URL)
        val label = intent?.getStringExtra(EXTRA_LABEL)
        val license = intent?.getStringExtra(EXTRA_LICENSE)
        thread(name = "clipper-job") {
            try {
                runJob(kind, source, recapTitle, url, label, license)
            } finally {
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf(startId)
            }
        }
        return START_NOT_STICKY
    }

    private fun startAndStop(): Int {
        stopSelf()
        return START_NOT_STICKY
    }

    private fun startAsForeground(text: String) {
        val n = NotificationCompat.Builder(this, ClipperApp.CHANNEL_ID)
            .setContentTitle("Clipper")
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_launcher)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(7, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(7, n)
        }
    }

    private fun runJob(kind: String, source: String, recapTitle: String, url: String?, label: String?, license: String?) {
        val settings = (application as ClipperApp).store.settings()
        val ffmpeg = Ffmpeg(FfmpegKitRunner()).also { it.fontsDir = fontsDir(this) }
        val transcriber = settings.groqKey?.let { GroqTranscriber(it) }
        val pipeline = Pipeline(
            ffmpeg, workRoot(this), QueueStore(queueFile(this)), transcriber, settings,
            videoCodec = "h264_mediacodec",
        )
        val path: Path = if (source.startsWith("http://") || source.startsWith("https://")) {
            YoutubeDlRunner(this).download(source, workRoot(this).resolve("downloads"))
        } else {
            Path.of(source)
        }
        when (kind) {
            KIND_RECAP_SHORT, KIND_RECAP_LONG -> {
                val jobKind = if (kind == KIND_RECAP_LONG) JobKind.RECAP_LONG else JobKind.RECAP_SHORT
                val vo = workRoot(this).resolve("tts/${System.currentTimeMillis()}.wav")
                val script = app.clipper.pipeline.RecapScript.heuristic(recapTitle, "", jobKind)
                DeviceTts(this).synthesize(script, vo.toFile())
                pipeline.recapFile(
                    path, jobKind, recapTitle, voiceover = vo,
                    sourceUrl = url ?: source, sourceLabel = label, license = license,
                )
            }
            else -> pipeline.clipFile(
                path, count = 1, sourceUrl = url ?: source.takeIf { it.startsWith("http") },
                sourceLabel = label, license = license,
            )
        }
    }

    companion object {
        const val KIND_CLIP = "clip"
        const val KIND_RECAP_SHORT = "recap_short"
        const val KIND_RECAP_LONG = "recap_long"
        private const val EXTRA_KIND = "kind"
        private const val EXTRA_SOURCE = "source"
        private const val EXTRA_TITLE = "title"
        private const val EXTRA_RECAP_TITLE = "recap_title"
        private const val EXTRA_URL = "url"
        private const val EXTRA_LABEL = "label"
        private const val EXTRA_LICENSE = "license"

        fun startClip(ctx: Context, source: String, url: String? = null, label: String? = null, license: String? = null) {
            ctx.startForegroundService(Intent(ctx, ClipperJobService::class.java).apply {
                putExtra(EXTRA_KIND, KIND_CLIP)
                putExtra(EXTRA_SOURCE, source)
                putExtra(EXTRA_TITLE, "Clipping video")
                putExtra(EXTRA_URL, url)
                putExtra(EXTRA_LABEL, label)
                putExtra(EXTRA_LICENSE, license)
            })
        }

        fun startRecap(
            ctx: Context,
            source: String,
            recapTitle: String,
            url: String? = null,
            label: String? = null,
            license: String? = null,
            long: Boolean = false,
        ) {
            ctx.startForegroundService(Intent(ctx, ClipperJobService::class.java).apply {
                putExtra(EXTRA_KIND, if (long) KIND_RECAP_LONG else KIND_RECAP_SHORT)
                putExtra(EXTRA_SOURCE, source)
                putExtra(EXTRA_TITLE, "Rendering recap")
                putExtra(EXTRA_RECAP_TITLE, recapTitle)
                putExtra(EXTRA_URL, url)
                putExtra(EXTRA_LABEL, label)
                putExtra(EXTRA_LICENSE, license)
            })
        }
    }
}
