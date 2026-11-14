package app.clipper.android.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import app.clipper.pipeline.Layout
import app.clipper.pipeline.Settings

/**
 * Keys live in EncryptedSharedPreferences (Android Keystore). Values are never
 * logged or shown back in full once saved.
 */
class SecureStore(context: Context) {
    private val prefs: SharedPreferences

    init {
        val master = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        prefs = EncryptedSharedPreferences.create(
            context,
            "clipper.secure",
            master,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    fun settings(): Settings = Settings(
        geminiKey = get("gemini_key"),
        groqKey = get("groq_key"),
        bufferToken = get("buffer_token"),
        bufferProfile = get("buffer_profile"),
        githubToken = get("github_token"),
        githubRepo = get("github_repo"),
        youtubeClientId = get("youtube_client_id"),
        youtubeClientSecret = get("youtube_client_secret"),
        autopilot = prefs.getBoolean("autopilot", false),
        layout = runCatching { Layout.valueOf(prefs.getString("layout", "FILL") ?: "FILL") }.getOrDefault(Layout.FILL),
        dailyCap = prefs.getInt("daily_cap", 8),
        autoFindEnabled = prefs.getBoolean("autofind_enabled", false),
        autoFindIntervalHours = prefs.getInt("autofind_interval_hours", 6),
        wifiOnly = prefs.getBoolean("wifi_only", true),
        chargingOnly = prefs.getBoolean("charging_only", false),
        ccOnlyDefault = prefs.getBoolean("cc_only_default", false),
        whisperModel = prefs.getString("whisper_model", "base") ?: "base",
    )

    fun putSecret(key: String, value: String) {
        if (value.isBlank()) prefs.edit().remove(key).apply() else prefs.edit().putString(key, value.trim()).apply()
    }

    fun putBool(key: String, value: Boolean) = prefs.edit().putBoolean(key, value).apply()
    fun putInt(key: String, value: Int) = prefs.edit().putInt(key, value).apply()
    fun putString(key: String, value: String) = prefs.edit().putString(key, value).apply()

    fun hasSecret(key: String): Boolean = !prefs.getString(key, null).isNullOrBlank()

    fun get(key: String): String? = prefs.getString(key, null)?.takeIf { it.isNotBlank() }

    fun masked(key: String): String {
        val v = get(key) ?: return "not set"
        if (v.length < 8) return "saved (••••)"
        return "saved (••••${v.takeLast(4)})"
    }
}
