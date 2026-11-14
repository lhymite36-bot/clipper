package app.clipper.android.job

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import app.clipper.pipeline.Settings
import java.util.concurrent.TimeUnit

object AutoFindScheduler {
    const val UNIQUE = "clipper-autofind"

    fun schedule(context: Context, settings: Settings) {
        val wm = WorkManager.getInstance(context)
        if (!settings.autoFindEnabled) {
            wm.cancelUniqueWork(UNIQUE)
            return
        }
        val hours = settings.autoFindIntervalHours.coerceIn(1, 24).toLong()
        // WorkManager's minimum period is 15 minutes; we default to 6 hours.
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(if (settings.wifiOnly) NetworkType.UNMETERED else NetworkType.CONNECTED)
            .setRequiresCharging(settings.chargingOnly)
            .build()
        val req = PeriodicWorkRequestBuilder<AutoFindWorker>(hours, TimeUnit.HOURS)
            .setConstraints(constraints)
            .build()
        wm.enqueueUniquePeriodicWork(UNIQUE, ExistingPeriodicWorkPolicy.UPDATE, req)
    }
}
