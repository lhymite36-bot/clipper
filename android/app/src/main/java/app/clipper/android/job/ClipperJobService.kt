package app.clipper.android.job

import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import app.clipper.android.ClipperApp
import app.clipper.android.MainActivity
import app.clipper.android.R
import app.clipper.android.data.DeviceTts
import app.clipper.android.data.FfmpegKitRunner
import app.clipper.android.data.YoutubeDlRunner
import app.clipper.android.data.fontsDir
import app.clipper.android.data.jobStatus
import app.clipper.android.data.queueFile
import app.clipper.android.data.workRoot
import app.clipper.pipeline.FetchFailed
import app.clipper.pipeline.Ffmpeg
import app.clipper.pipeline.GroqTranscriber
import app.clipper.pipeline.JobKind
import app.clipper.pipeline.Pipeline
import app.clipper.pipeline.QueueStore
import java.nio.file.Path
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * Foreground service for long recaps and one-off clip jobs so they survive
 * the app moving to the background on a budget phone.
 *
 * v1.2.1: every step, the download %, and the final result (or a plain error)
 * are written to [app.clipper.pipeline.JobStatus] for the screen and shown in
 * the notification. A failure never crashes the app or fails silently.
 */
class ClipperJobService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val status = jobStatus(this)
        val title = intent?.getStringExtra(EXTRA_TITLE) ?: "Clipper is working"
        try {
            startAsForeground(title, null)
        } catch (t: Throwable) {
            status.failed("Android blocked the background job (${t.javaClass.simpleName}). Keep Clipper open and try again.")
            stopSelf(startId)
            return START_NOT_STICKY
        }
        val source = intent?.getStringExtra(EXTRA_SOURCE)
        if (source == null || !running.compareAndSet(false, true)) {
            if (source != null) status.log("Another job is still running; wait for it to finish, then try again.")
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf(startId)
            return START_NOT_STICKY
        }
        val kind = intent.getStringExtra(EXTRA_KIND) ?: KIND_CLIP
        val recapTitle = intent.getStringExtra(EXTRA_RECAP_TITLE) ?: "Recap"
        val url = intent.getStringExtra(EXTRA_URL)
        val label = intent.getStringExtra(EXTRA_LABEL)
        val license = intent.getStringExtra(EXTRA_LICENSE)
        thread(name = "clipper-job") {
            try {
                runJob(kind, source, recapTitle, url, label, license)
            } catch (t: Throwable) {
                val msg = friendly(t)
                status.failed(msg)
                notifyResult("Clipper couldn't finish", msg)
            } finally {
                running.set(false)
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf(startId)
            }
        }
        return START_NOT_STICKY
    }

    private fun friendly(t: Throwable): String = when (t) {
        is FetchFailed -> t.message ?: "Download failed."
        is OutOfMemoryError -> "The phone ran out of memory. Try a shorter video."
        is java.net.UnknownHostException -> "No internet connection. Check Wi-Fi or mobile data and try again."
        else -> "Something went wrong: ${t.message ?: t.javaClass.simpleName}. Copy the log below and send it for help."
    }

    private fun contentIntent(): PendingIntent = PendingIntent.getActivity(
        this, 0,
        Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    private fun buildProgress(text: String, percent: Int?) =
        NotificationCompat.Builder(this, ClipperApp.CHANNEL_ID)
            .setContentTitle("Clipper")
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_launcher)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(contentIntent())
            .setProgress(100, percent ?: 0, percent == null)
            .build()

    private fun startAsForeground(text: String, percent: Int?) {
        val n = buildProgress(text, percent)
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(NOTIF_ID, n)
        }
    }

    private var lastNotify = 0L
    private fun updateNotification(text: String, percent: Int?) {
        val now = System.currentTimeMillis()
        if (now - lastNotify < 800) return
        lastNotify = now
        runCatching { getSystemService(NotificationManager::class.java).notify(NOTIF_ID, buildProgress(text, percent)) }
    }

    private fun notifyResult(title: String, text: String) {
        runCatching {
            val n = NotificationCompat.Builder(this, ClipperApp.CHANNEL_ID)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(NotificationCompat.BigTextStyle().bigText(text))
                .setSmallIcon(R.drawable.ic_launcher)
                .setAutoCancel(true)
                .setContentIntent(contentIntent())
                .build()
            getSystemService(NotificationManager::class.java).notify(RESULT_ID, n)
        }
    }

    private fun runJob(kind: String, source: String, recapTitle: String, url: String?, label: String?, license: String?) {
        val status = jobStatus(this)
        val settings = (application as ClipperApp).store.settings()
        val ffmpeg = Ffmpeg(FfmpegKitRunner()).also { it.fontsDir = fontsDir(this) }
        val transcriber = settings.groqKey?.let { GroqTranscriber(it) }
        val pipeline = Pipeline(
            ffmpeg, workRoot(this), QueueStore(queueFile(this)), transcriber, settings,
            videoCodec = "h264_mediacodec",
        )
        var currentStep = "Starting"
        val onStep: (String) -> Unit = { s ->
            currentStep = s
            status.step(s)
            updateNotification(s, null)
        }
        val isLink = source.startsWith("http://", true) || source.startsWith("https://", true) ||
            !source.startsWith("/")
        var title: String? = null
        val path: Path = if (isLink) {
            onStep("Downloading the video")
            val r = YoutubeDlRunner(this).fetch(
                source,
                workRoot(this).resolve("downloads"),
                log = { status.log(it) },
                progress = { p ->
                    status.percent(p)
                    updateNotification(if (p != null) "$currentStep… $p%" else currentStep, p)
                },
            )
            title = r.title
            status.log("Downloaded ${(r.path.toFile().length() / 1024 / 1024.0).let { "%.1f".format(it) }} MB via ${r.via}")
            r.path
        } else {
            Path.of(source)
        }
        val sourceUrl = url ?: source.takeIf { isLink }
        when (kind) {
            KIND_RECAP_SHORT, KIND_RECAP_LONG -> {
                val jobKind = if (kind == KIND_RECAP_LONG) JobKind.RECAP_LONG else JobKind.RECAP_SHORT
                onStep("Recording the narration")
                val vo = workRoot(this).resolve("tts/${System.currentTimeMillis()}.wav")
                val script = app.clipper.pipeline.RecapScript.heuristic(recapTitle, "", jobKind)
                DeviceTts(this).synthesize(script, vo.toFile())
                pipeline.recapFile(
                    path, jobKind, recapTitle, voiceover = vo,
                    sourceUrl = sourceUrl, sourceLabel = label ?: title, license = license,
                    onProgress = onStep,
                )
                val msg = "Recap ready. Open the Queue tab to review it."
                status.done(msg)
                notifyResult("Recap ready", msg)
            }
            else -> {
                val items = pipeline.clipFile(
                    path, count = 1, sourceUrl = sourceUrl,
                    sourceLabel = label ?: title, license = license,
                    onProgress = onStep,
                )
                if (items.isEmpty()) error("No clip could be made from this video (it may be too short or silent).")
                val msg = "Clip ready. Open the Queue tab to review it. Nothing posts automatically."
                status.done(msg)
                notifyResult("Clip ready", msg)
            }
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
        private const val NOTIF_ID = 7
        private const val RESULT_ID = 8

        /** True while a job thread is alive in this process. */
        val running = AtomicBoolean(false)

        private fun launch(ctx: Context, intent: Intent, firstStep: String) {
            val status = jobStatus(ctx)
            if (running.get()) throw IllegalStateException("Another job is still running. Wait for it to finish (see the status below).")
            status.start(firstStep)
            try {
                ctx.startForegroundService(intent)
            } catch (t: Throwable) {
                status.failed("Couldn't start the background job: ${t.message ?: t.javaClass.simpleName}")
                throw t
            }
        }

        fun startClip(ctx: Context, source: String, url: String? = null, label: String? = null, license: String? = null) {
            launch(
                ctx,
                Intent(ctx, ClipperJobService::class.java).apply {
                    putExtra(EXTRA_KIND, KIND_CLIP)
                    putExtra(EXTRA_SOURCE, source)
                    putExtra(EXTRA_TITLE, "Clipping video")
                    putExtra(EXTRA_URL, url)
                    putExtra(EXTRA_LABEL, label)
                    putExtra(EXTRA_LICENSE, license)
                },
                "Starting clip job",
            )
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
            launch(
                ctx,
                Intent(ctx, ClipperJobService::class.java).apply {
                    putExtra(EXTRA_KIND, if (long) KIND_RECAP_LONG else KIND_RECAP_SHORT)
                    putExtra(EXTRA_SOURCE, source)
                    putExtra(EXTRA_TITLE, "Rendering recap")
                    putExtra(EXTRA_RECAP_TITLE, recapTitle)
                    putExtra(EXTRA_URL, url)
                    putExtra(EXTRA_LABEL, label)
                    putExtra(EXTRA_LICENSE, license)
                },
                "Starting recap job",
            )
        }
    }
}
