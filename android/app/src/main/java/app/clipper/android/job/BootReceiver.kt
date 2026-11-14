package app.clipper.android.job

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import app.clipper.android.ClipperApp

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != Intent.ACTION_BOOT_COMPLETED) return
        val app = context.applicationContext as? ClipperApp ?: return
        AutoFindScheduler.schedule(context, app.store.settings())
    }
}
