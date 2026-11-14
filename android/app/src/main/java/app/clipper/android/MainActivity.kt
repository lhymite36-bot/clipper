@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
package app.clipper.android

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import app.clipper.android.data.SecureStore
import app.clipper.android.data.queueFile
import app.clipper.android.data.sourcesDir
import app.clipper.android.data.workRoot
import app.clipper.android.job.AutoFindScheduler
import app.clipper.android.job.ClipperJobService
import app.clipper.android.ui.ClipperTheme
import app.clipper.pipeline.AutoFind
import app.clipper.pipeline.CommandResult
import app.clipper.pipeline.CommandRunner
import app.clipper.pipeline.QueueItem
import app.clipper.pipeline.QueueStatus
import app.clipper.pipeline.QueueStore
import app.clipper.pipeline.SourceKind
import app.clipper.pipeline.WatchSource
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 33) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        val sharedUrl = when (intent?.action) {
            Intent.ACTION_SEND -> intent.getStringExtra(Intent.EXTRA_TEXT)
            else -> null
        }
        val sharedUri = if (intent?.action == Intent.ACTION_SEND) {
            if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
            else @Suppress("DEPRECATION") intent.getParcelableExtra(Intent.EXTRA_STREAM)
        } else null

        setContent {
            ClipperTheme {
                Surface(Modifier.fillMaxSize()) {
                    ClipperAppScreen(
                        store = (application as ClipperApp).store,
                        initialUrl = sharedUrl,
                        initialUri = sharedUri,
                        copyUri = { uri -> copyIncoming(uri) },
                        openFile = { path -> openOutput(path) },
                    )
                }
            }
        }
    }

    private fun copyIncoming(uri: Uri): String {
        val name = contentResolver.query(uri, null, null, null, null)?.use { c ->
            val idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (c.moveToFirst() && idx >= 0) c.getString(idx) else "shared.mp4"
        } ?: "shared.mp4"
        val dest = workRoot(this).resolve("inbox").resolve(name)
        dest.parent.toFile().mkdirs()
        contentResolver.openInputStream(uri)?.use { inp ->
            Files.copy(inp, dest, StandardCopyOption.REPLACE_EXISTING)
        } ?: error("Could not read the shared file")
        return dest.toAbsolutePath().toString()
    }

    private fun openOutput(path: String) {
        val file = File(path)
        val uri = FileProvider.getUriForFile(this, "$packageName.files", file)
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "video/mp4")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        startActivity(Intent.createChooser(intent, "Open clip"))
    }
}

private enum class Tab { Clip, Recap, Queue, Sources, Settings }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ClipperAppScreen(
    store: SecureStore,
    initialUrl: String?,
    initialUri: Uri?,
    copyUri: (Uri) -> String,
    openFile: (String) -> Unit,
) {
    val ctx = androidx.compose.ui.platform.LocalContext.current
    var tab by remember { mutableStateOf(Tab.Clip) }
    var url by remember { mutableStateOf(initialUrl ?: "") }
    var status by remember { mutableStateOf("Draft-only is on. Nothing posts unless Autopilot is enabled.") }
    var recapTitle by remember { mutableStateOf("") }
    var recapLong by remember { mutableStateOf(false) }

    LaunchedEffect(initialUri) {
        if (initialUri != null) {
            runCatching {
                val path = copyUri(initialUri)
                ClipperJobService.startClip(ctx, path)
                status = "Clipping the shared video in the background."
            }.onFailure { status = it.message ?: "Could not open the shared file." }
        }
    }

    Scaffold(
        topBar = { TopAppBar(title = { Text("Clipper") }) },
        bottomBar = {
            TabRow(selectedTabIndex = Tab.entries.indexOf(tab)) {
                Tab.entries.forEach { item ->
                    Tab(
                        selected = tab == item,
                        onClick = { tab = item },
                        text = { Text(item.name) },
                    )
                }
            }
        },
    ) { pad ->
        Box(Modifier.padding(pad).fillMaxSize().padding(16.dp)) {
            when (tab) {
                Tab.Clip -> ClipPanel(url, { url = it }, status, { status = it }, copyUri)
                Tab.Recap -> RecapPanel(url, { url = it }, recapTitle, { recapTitle = it }, recapLong, { recapLong = it }, status, { status = it }, copyUri)
                Tab.Queue -> QueuePanel(openFile)
                Tab.Sources -> SourcesPanel(store)
                Tab.Settings -> SettingsPanel(store)
            }
        }
    }
}

@Composable
private fun ClipPanel(
    url: String,
    onUrl: (String) -> Unit,
    status: String,
    onStatus: (String) -> Unit,
    copyUri: (Uri) -> String,
) {
    val ctx = androidx.compose.ui.platform.LocalContext.current
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) {
            runCatching {
                val path = copyUri(uri)
                ClipperJobService.startClip(ctx, path)
                onStatus("Clipping your file in the background. It will land in the review queue.")
            }.onFailure { onStatus(it.message ?: "Could not open the file.") }
        }
    }
    Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Paste a YouTube URL or pick a video. Clipper finds hook moments, captions them in 9:16, and adds copyright-safe music. Finished clips go to the review queue — nothing posts automatically.")
        OutlinedTextField(url, onUrl, label = { Text("YouTube or video URL") }, modifier = Modifier.fillMaxWidth())
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                if (url.isBlank()) {
                    onStatus("Paste a URL or pick a file first.")
                } else {
                    ClipperJobService.startClip(ctx, url.trim(), url = url.trim())
                    onStatus("Downloading and clipping in the background. If the download is blocked, pick the file instead.")
                }
            }) { Text("Clip URL") }
            OutlinedButton(onClick = { picker.launch("video/*") }) { Text("Pick a file") }
        }
        Text(status, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun RecapPanel(
    url: String,
    onUrl: (String) -> Unit,
    title: String,
    onTitle: (String) -> Unit,
    long: Boolean,
    onLong: (Boolean) -> Unit,
    status: String,
    onStatus: (String) -> Unit,
    copyUri: (Uri) -> String,
) {
    val ctx = androidx.compose.ui.platform.LocalContext.current
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null && title.isNotBlank()) {
            runCatching {
                val path = copyUri(uri)
                ClipperJobService.startRecap(ctx, path, title, long = long)
                onStatus("Rendering the recap in a foreground job so it can finish if you leave the app.")
            }.onFailure { onStatus(it.message ?: "Could not open the file.") }
        } else if (title.isBlank()) {
            onStatus("Add a movie title first.")
        }
    }
    Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Movie Recap: a Short (45–60s, 9:16, hook bar) or a Long 16:9 recap with one narrator, scene-matched shots, and word captions. Content ID can still claim a recap. Clipper does not flip, speed-shift, or hide a film.")
        OutlinedTextField(title, onTitle, label = { Text("Movie title") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(url, onUrl, label = { Text("Trailer or film URL (optional)") }, modifier = Modifier.fillMaxWidth())
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Short")
            Switch(checked = long, onCheckedChange = onLong)
            Text("Long")
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                if (title.isBlank()) onStatus("Add a movie title first.")
                else if (url.isBlank()) onStatus("Paste a URL or pick a file.")
                else {
                    ClipperJobService.startRecap(ctx, url.trim(), title, url = url.trim(), long = long)
                    onStatus("Recap started. Long recaps keep running as a foreground job.")
                }
            }) { Text("Recap URL") }
            OutlinedButton(onClick = { picker.launch("video/*") }) { Text("Pick a file") }
        }
        Text(status, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun QueuePanel(openFile: (String) -> Unit) {
    val ctx = androidx.compose.ui.platform.LocalContext.current
    val store = remember { QueueStore(queueFile(ctx)) }
    var items by remember { mutableStateOf(store.all().reversed()) }
    fun reload() { items = store.all().reversed() }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Review queue. Draft-only is the default. Approve items here; nothing goes live unless Autopilot is on and draft-only is off.")
        if (items.isEmpty()) {
            Text("Queue is empty. New clips and Auto-find drafts show up here.", style = MaterialTheme.typography.bodySmall)
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(items, key = { it.id }) { item ->
                ElevatedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(item.title.ifBlank { item.path }, style = MaterialTheme.typography.titleMedium)
                        Text("Status: ${item.status.name.lowercase().replace('_', ' ')}", style = MaterialTheme.typography.bodySmall)
                        val meta = listOfNotNull(
                            item.sourceLabel?.let { "Source: $it" },
                            item.license?.let { "Licence: $it" },
                            item.foundBy?.let { "Found by: $it" },
                        ).joinToString("  ·  ")
                        if (meta.isNotBlank()) Text(meta, style = MaterialTheme.typography.bodySmall)
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            if (item.status == QueueStatus.PENDING_REVIEW) {
                                Button(onClick = { store.updateStatus(item.id, QueueStatus.APPROVED); reload() }) { Text("Approve") }
                                OutlinedButton(onClick = { store.updateStatus(item.id, QueueStatus.REJECTED); reload() }) { Text("Reject") }
                            }
                            if (item.path.isNotBlank()) TextButton(onClick = { openFile(item.path) }) { Text("Open") }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SourcesPanel(secure: SecureStore) {
    val ctx = androidx.compose.ui.platform.LocalContext.current
    val auto = remember { AutoFind(sourcesDir(ctx), CommandRunner { _, _ -> CommandResult(0, "", "") }, dailyCap = secure.settings().dailyCap) }
    var sources by remember { mutableStateOf(auto.listSources()) }
    var kind by remember { mutableStateOf(SourceKind.KEYWORD) }
    var query by remember { mutableStateOf("") }
    var ccOnly by remember { mutableStateOf(secure.settings().ccOnlyDefault) }
    var recap by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("Daily cap used ${auto.usedToday()}/${auto.dailyCap} today (Asia/Calcutta).") }
    fun reload() {
        sources = auto.listSources()
        status = "Daily cap used ${auto.usedToday()}/${auto.dailyCap} today (Asia/Calcutta). Remaining: ${auto.remainingToday()}."
    }
    Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Auto-find pulls videos by itself from watched channels, playlists, campaign/brief links, keyword search, or a movie trailer title. New items are clipped or recapped into the draft review queue. Nothing posts unless Autopilot is on.")
        var kindExpanded by remember { mutableStateOf(false) }
        ExposedDropdown(kind.name.lowercase(), listOf("channel", "playlist", "brief", "keyword", "trailer")) {
            kind = SourceKind.valueOf(it.uppercase())
            recap = kind == SourceKind.TRAILER
        }
        OutlinedTextField(query, { query = it }, label = { Text("URL, keyword, or movie title") }, modifier = Modifier.fillMaxWidth())
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(ccOnly, { ccOnly = it })
            Text("Creative Commons only")
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(recap, { recap = it })
            Text("Treat as Recap")
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                if (query.isBlank()) {
                    status = "Add a URL, keyword, or title first."
                } else {
                    auto.addSource(WatchSource("", kind, query.trim(), query.trim(), ccOnly, recap || kind == SourceKind.TRAILER, true))
                    query = ""
                    reload()
                    status = "Source saved."
                }
            }) { Text("Save source") }
            OutlinedButton(onClick = {
                status = "Checking sources in the background (Wi-Fi / charging rules apply when scheduled)."
                // Kick an immediate one-off by scheduling; also start the worker via WorkManager
                androidx.work.OneTimeWorkRequestBuilder<app.clipper.android.job.AutoFindWorker>().build().also {
                    androidx.work.WorkManager.getInstance(ctx).enqueue(it)
                }
            }) { Text("Check now") }
        }
        Text(status, style = MaterialTheme.typography.bodySmall)
        sources.forEach { src ->
            ElevatedCard(Modifier.fillMaxWidth()) {
                Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(src.label, style = MaterialTheme.typography.titleMedium)
                        Text("${src.kind.name.lowercase()} · ${src.query}" + (if (src.ccOnly) " · CC-only" else "") + (if (src.recap) " · recap" else ""), style = MaterialTheme.typography.bodySmall)
                    }
                    TextButton(onClick = { auto.removeSource(src.id); reload() }) { Text("Remove") }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ExposedDropdown(value: String, options: List<String>, onPick: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(expanded, { expanded = it }) {
        OutlinedTextField(
            value = value,
            onValueChange = {},
            readOnly = true,
            label = { Text("Source kind") },
            modifier = Modifier.menuAnchor().fillMaxWidth(),
        )
        ExposedDropdownMenu(expanded, { expanded = false }) {
            options.forEach {
                DropdownMenuItem(text = { Text(it) }, onClick = { onPick(it); expanded = false })
            }
        }
    }
}

@Composable
private fun SettingsPanel(store: SecureStore) {
    val ctx = androidx.compose.ui.platform.LocalContext.current
    var gemini by remember { mutableStateOf("") }
    var groq by remember { mutableStateOf("") }
    var buffer by remember { mutableStateOf("") }
    var github by remember { mutableStateOf("") }
    var repo by remember { mutableStateOf(store.get("github_repo") ?: "") }
    var autopilot by remember { mutableStateOf(store.settings().autopilot) }
    var autoFind by remember { mutableStateOf(store.settings().autoFindEnabled) }
    var wifi by remember { mutableStateOf(store.settings().wifiOnly) }
    var charging by remember { mutableStateOf(store.settings().chargingOnly) }
    var cap by remember { mutableStateOf(store.settings().dailyCap.toString()) }
    var hours by remember { mutableStateOf(store.settings().autoFindIntervalHours.toString()) }
    var saved by remember { mutableStateOf("") }
    Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Keys are stored in EncryptedSharedPreferences on this phone. Clipper never prints them. Leave a field blank to keep the current value. Groq Whisper is used when a Groq key is set (recommended on a Samsung A05); otherwise clips fall back to loudness + hook words.")
        SecretField("Gemini API key", gemini, { gemini = it }, store.masked("gemini_key"))
        SecretField("Groq API key", groq, { groq = it }, store.masked("groq_key"))
        SecretField("Buffer API token", buffer, { buffer = it }, store.masked("buffer_token"))
        SecretField("GitHub token (for public MP4 URLs)", github, { github = it }, store.masked("github_token"))
        OutlinedTextField(repo, { repo = it }, label = { Text("GitHub repo for media (owner/repo)") }, modifier = Modifier.fillMaxWidth())
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = autopilot, onCheckedChange = { autopilot = it })
            Text("Autopilot (off by default — do not turn on unless you want approved items to post)")
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = autoFind, onCheckedChange = { autoFind = it })
            Text("Enable Auto-find schedule")
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = wifi, onCheckedChange = { wifi = it })
            Text("Auto-find only on Wi-Fi")
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = charging, onCheckedChange = { charging = it })
            Text("Auto-find only while charging")
        }
        OutlinedTextField(cap, { cap = it }, label = { Text("Daily Auto-find cap") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(hours, { hours = it }, label = { Text("Check every (hours)") }, modifier = Modifier.fillMaxWidth())
        Button(onClick = {
            if (gemini.isNotBlank()) store.putSecret("gemini_key", gemini)
            if (groq.isNotBlank()) store.putSecret("groq_key", groq)
            if (buffer.isNotBlank()) store.putSecret("buffer_token", buffer)
            if (github.isNotBlank()) store.putSecret("github_token", github)
            store.putString("github_repo", repo)
            store.putBool("autopilot", autopilot)
            store.putBool("autofind_enabled", autoFind)
            store.putBool("wifi_only", wifi)
            store.putBool("charging_only", charging)
            store.putInt("daily_cap", cap.toIntOrNull() ?: 8)
            store.putInt("autofind_interval_hours", hours.toIntOrNull() ?: 6)
            gemini = ""; groq = ""; buffer = ""; github = ""
            AutoFindScheduler.schedule(ctx, store.settings())
            saved = "Saved. Key values are hidden. Auto-find schedule updated."
        }) { Text("Save settings") }
        if (saved.isNotBlank()) Text(saved, style = MaterialTheme.typography.bodySmall)
        Text("To install later builds, open the GitHub pre-release and download the APK. Allow install from the browser if Android asks.", style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun SecretField(label: String, value: String, onValue: (String) -> Unit, masked: String) {
    Column {
        OutlinedTextField(
            value,
            onValue,
            label = { Text(label) },
            placeholder = { Text(masked) },
            visualTransformation = PasswordVisualTransformation(),
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
        )
        Text(masked, style = MaterialTheme.typography.bodySmall)
    }
}
