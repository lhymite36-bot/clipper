package app.clipper.android.job

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.ForegroundInfo
import androidx.work.WorkerParameters
import androidx.core.app.NotificationCompat
import app.clipper.android.ClipperApp
import app.clipper.android.R
import app.clipper.android.data.FfmpegKitRunner
import app.clipper.android.data.YoutubeDlRunner
import app.clipper.android.data.fontsDir
import app.clipper.android.data.queueFile
import app.clipper.android.data.sourcesDir
import app.clipper.android.data.workRoot
import app.clipper.pipeline.AutoFind
import app.clipper.pipeline.CommandResult
import app.clipper.pipeline.CommandRunner
import app.clipper.pipeline.Ffmpeg
import app.clipper.pipeline.GroqTranscriber
import app.clipper.pipeline.JobKind
import app.clipper.pipeline.Pipeline
import app.clipper.pipeline.QueueStore

class AutoFindWorker(appContext: Context, params: WorkerParameters) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        val app = applicationContext as? ClipperApp ?: ClipperApp.instance
        val settings = app.store.settings()
        if (!settings.autoFindEnabled) return Result.success()
        setForeground(notify("Checking watched sources…"))
        val yt = YoutubeDlRunner(applicationContext)
        val runner = yt.asCommandRunner()
        val auto = AutoFind(sourcesDir(applicationContext), runner, dailyCap = settings.dailyCap)
        val found = auto.discover()
        if (found.isEmpty()) return Result.success()
        val ffmpeg = Ffmpeg(FfmpegKitRunner()).also { it.fontsDir = fontsDir(applicationContext) }
        val transcriber = settings.groqKey?.let { GroqTranscriber(it) }
        val pipeline = Pipeline(
            ffmpeg = ffmpeg,
            workRoot = workRoot(applicationContext),
            queue = QueueStore(queueFile(applicationContext)),
            transcriber = transcriber,
            settings = settings,
            videoCodec = "h264_mediacodec",
        )
        var done = 0
        for (video in found) {
            setForeground(notify("Processing ${video.title.ifBlank { video.url }}"))
            val dest = workRoot(applicationContext).resolve("downloads")
            val file = runCatching { yt.download(video.url, dest) }.getOrNull() ?: continue
            runCatching {
                if (video.kind == JobKind.CLIP) {
                    pipeline.clipFile(
                        file,
                        count = 1,
                        sourceUrl = video.url,
                        sourceLabel = video.sourceLabel,
                        license = video.license,
                        foundBy = video.sourceId,
                    )
                } else {
                    // Recap needs a voiceover; Auto-find short recap is kicked to the job service.
                    ClipperJobService.startRecap(
                        applicationContext,
                        file.toString(),
                        video.title,
                        video.url,
                        video.sourceLabel,
                        video.license,
                    )
                }
                auto.markSeen(listOf(video.videoId))
                auto.recordUsed(1)
                done++
            }
        }
        return Result.success()
    }

    private fun notify(text: String): ForegroundInfo {
        val n = NotificationCompat.Builder(applicationContext, ClipperApp.CHANNEL_ID)
            .setContentTitle("Clipper Auto-find")
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_launcher)
            .setOngoing(true)
            .build()
        return ForegroundInfo(42, n)
    }
}
