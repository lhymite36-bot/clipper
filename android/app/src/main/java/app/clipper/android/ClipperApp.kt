package app.clipper.android

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import app.clipper.android.data.SecureStore
import app.clipper.android.job.AutoFindScheduler

class ClipperApp : Application() {
    lateinit var store: SecureStore
        private set

    override fun onCreate() {
        super.onCreate()
        instance = this
        store = SecureStore(this)
        if (Build.VERSION.SDK_INT >= 26) {
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    getString(R.string.notification_channel),
                    NotificationManager.IMPORTANCE_LOW,
                ),
            )
        }
        AutoFindScheduler.schedule(this, store.settings())
    }

    companion object {
        const val CHANNEL_ID = "clipper-jobs"
        lateinit var instance: ClipperApp
            private set
    }
}
