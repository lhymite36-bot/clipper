package app.clipper.android.data

import android.content.Context
import java.nio.file.Path

fun workRoot(context: Context): Path = context.filesDir.toPath().resolve("clipper")
fun queueFile(context: Context) = workRoot(context).resolve("queue.json")
fun sourcesDir(context: Context) = workRoot(context).resolve("autofind")
fun fontsDir(context: Context): Path {
    val dest = workRoot(context).resolve("fonts")
    dest.toFile().mkdirs()
    val assets = context.assets
    listOf("Anton-Regular.ttf", "Montserrat-ExtraBold.ttf").forEach { name ->
        val out = dest.resolve(name).toFile()
        if (!out.exists()) {
            runCatching {
                assets.open("fonts/$name").use { inp -> out.outputStream().use { inp.copyTo(it) } }
            }
        }
    }
    return dest
}
