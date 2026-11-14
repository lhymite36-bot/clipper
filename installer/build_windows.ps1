$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

python -m pip install -U pip
pip install -e ".[dev]"
pip install pyinstaller

# Bundle a Windows FFmpeg build (essentials, already unzipped to dist/ffmpeg-bin)
$ffDir = "dist/ffmpeg-bin"
New-Item -ItemType Directory -Force -Path $ffDir | Out-Null
if (-not (Test-Path "$ffDir/ffmpeg.exe")) {
  $zip = "dist/ffmpeg-release-essentials.zip"
  Write-Host "Downloading FFmpeg essentials…"
  Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $zip
  Expand-Archive -Path $zip -DestinationPath "dist/ffmpeg-unpack" -Force
  $bin = Get-ChildItem -Path "dist/ffmpeg-unpack" -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
  if (-not $bin) { throw "ffmpeg.exe missing from the essentials zip" }
  Copy-Item -Force $bin.FullName "$ffDir/ffmpeg.exe"
  $probe = Join-Path $bin.DirectoryName "ffprobe.exe"
  if (Test-Path $probe) { Copy-Item -Force $probe "$ffDir/ffprobe.exe" }
}

$common = @(
  "--noconfirm", "--clean",
  "--collect-all", "faster_whisper",
  "--collect-all", "ctranslate2",
  "--collect-all", "tokenizers",
  "--collect-all", "onnxruntime",
  "--collect-all", "av",
  "--collect-all", "yt_dlp",
  "--collect-all", "cv2",
  "--hidden-import=uvicorn.logging",
  "--hidden-import=uvicorn.loops",
  "--hidden-import=uvicorn.loops.auto",
  "--hidden-import=uvicorn.protocols",
  "--hidden-import=uvicorn.protocols.http",
  "--hidden-import=uvicorn.protocols.http.auto",
  "--hidden-import=uvicorn.lifespan",
  "--hidden-import=uvicorn.lifespan.on",
  "--hidden-import=clipper.cli",
  "--hidden-import=clipper.web",
  "--hidden-import=clipper.pipeline",
  "--collect-submodules", "clipper",
  "--add-data", "src/clipper/data;clipper/data",
  "--add-data", "src/clipper/static;clipper/static"
)

# Windowed web UI
pyinstaller @common --name Clipper --windowed --distpath dist src/clipper/ui_main.py
if (-not (Test-Path "dist/Clipper/Clipper.exe")) { throw "Clipper.exe missing" }

# Console CLI into a temp onedir, then merge
pyinstaller @common --name clipper --console --distpath dist/clipper_cli_build src/clipper/cli.py
if (-not (Test-Path "dist/clipper_cli_build/clipper/clipper.exe")) { throw "clipper.exe missing" }

# Final onedir used by Inno Setup
$app = "dist/ClipperApp"
if (Test-Path $app) { Remove-Item -Recurse -Force $app }
New-Item -ItemType Directory -Force -Path $app | Out-Null
Copy-Item -Recurse -Force "dist/Clipper/*" $app
Copy-Item -Force "dist/clipper_cli_build/clipper/clipper.exe" "$app/clipper.exe"
# Also ship `clip.exe` (same CLI). Windows already has System32\clip.exe; the
# installer does not put this folder ahead of System32, so Start Menu / full
# path / `clipper.exe` is the supported way to launch on Windows.
Copy-Item -Force "$app/clipper.exe" "$app/clip.exe"

# Extra DLLs / data from the CLI build
Get-ChildItem "dist/clipper_cli_build/clipper" -File | ForEach-Object {
  $dest = Join-Path $app $_.Name
  if (-not (Test-Path $dest)) { Copy-Item -Force $_.FullName $dest }
}
Get-ChildItem "dist/clipper_cli_build/clipper" -Directory | ForEach-Object {
  $dest = Join-Path $app $_.Name
  if (-not (Test-Path $dest)) {
    Copy-Item -Recurse -Force $_.FullName $dest
  } else {
    Copy-Item -Recurse -Force (Join-Path $_.FullName "*") $dest -ErrorAction SilentlyContinue
  }
}

# Bundle ffmpeg / ffprobe next to the exes
Copy-Item -Force "$ffDir/ffmpeg.exe" "$app/ffmpeg.exe"
if (Test-Path "$ffDir/ffprobe.exe") { Copy-Item -Force "$ffDir/ffprobe.exe" "$app/ffprobe.exe" }

# Smoke test frozen CLI (no model download)
& "$app/clipper.exe" --selftest
if ($LASTEXITCODE -ne 0) { throw "clipper --selftest failed with $LASTEXITCODE" }
Write-Host "clipper --selftest OK"

& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\setup.iss
if (-not (Test-Path "dist/Clipper-Setup.exe")) { throw "Installer missing" }
Write-Host "Build OK"
