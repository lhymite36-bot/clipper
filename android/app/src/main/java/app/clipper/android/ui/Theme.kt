package app.clipper.android.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Gold = Color(0xFFF5C542)
private val Bg = Color(0xFF0E0F14)
private val Card = Color(0xFF181A22)
private val Ink = Color(0xFFF4F1EA)

private val colors = darkColorScheme(
    primary = Gold,
    onPrimary = Color(0xFF1A1400),
    background = Bg,
    surface = Card,
    onBackground = Ink,
    onSurface = Ink,
    secondary = Color(0xFF8E8A7C),
)

@Composable
fun ClipperTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = colors, content = content)
}
