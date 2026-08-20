# Builds a standalone Windows app for Faceless Studio.
#
#   powershell -ExecutionPolicy Bypass -File build_app.ps1
#
# Produces:
#   dist/FacelessStudio.exe          (built with PyInstaller --onedir)
#   dist/FacelessStudio/             (app folder: exe + generator/ + clipper/)
#   dist/FacelessStudio.zip          (zipped app folder, ready to share)
#
# Requirements:  git, uv  (pip/venv is fine too — see $PyInstaller below)
#                ffmpeg on PATH (needed by the generator at runtime)
# Optional:      Inno Setup 6  ->  iscc installer.iss  (creates setup.exe)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Name  = "FacelessStudio"
$Out   = Join-Path $Root "dist"
$App   = Join-Path $Out $Name

# --- 1. icon ---------------------------------------------------------------
$Icon = Join-Path $Root "assets\faceless.ico"
if (-not (Test-Path $Icon)) {
    Write-Host "Generating icon..."
    New-Item -ItemType Directory -Force -Path (Split-Path $Icon) | Out-Null
    Add-Type -AssemblyName System.Drawing
    $size = 256
    $bmp  = New-Object System.Drawing.Bitmap($size, $size)
    $g    = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear([System.Drawing.Color]::Transparent)
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $d = 44
    $r = 56
    $path.AddArc(4, 4, $r, $r, 180, 90)
    $path.AddArc($size-4-$r, 4, $r, $r, 270, 90)
    $path.AddArc($size-4-$r, $size-4-$r, $r, $r, 0, 90)
    $path.AddArc(4, $size-4-$r, $r, $r, 90, 90)
    $path.CloseFigure()
    $brush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
        (New-Object System.Drawing.Rectangle(0, 0, $size, $size)),
        [System.Drawing.Color]::FromArgb(255, 109, 124, 255),
        [System.Drawing.Color]::FromArgb(255, 143, 155, 255), 60)
    $g.FillPath($brush, $path)
    $font = New-Object System.Drawing.Font("Segoe UI", 150, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
    $sf   = New-Object System.Drawing.StringFormat
    $sf.Alignment = [System.Drawing.StringAlignment]::Center
    $sf.LineAlignment = [System.Drawing.StringAlignment]::Center
    $g.DrawString("F", $font, [System.Drawing.Brushes]::Black, (New-Object System.Drawing.RectangleF(0, 0, $size, $size)), $sf)
    $g.DrawString("F", $font, [System.Drawing.Brushes]::White, (New-Object System.Drawing.RectangleF(0, -6, $size, $size)), $sf)
    $png = Join-Path (Split-Path $Icon) "faceless.png"
    $bmp.Save($png, [System.Drawing.Imaging.ImageFormat]::Png)
    $pngBytes = [System.IO.File]::ReadAllBytes($png)
    $fs = [System.IO.File]::Create($Icon)
    $bw = New-Object System.IO.BinaryWriter($fs)
    $bw.Write([uint16]0); $bw.Write([uint16]1); $bw.Write([uint16]1)
    $bw.Write([byte]0);   $bw.Write([byte]0);   $bw.Write([byte]0); $bw.Write([byte]0)
    $bw.Write([uint16]1); $bw.Write([uint16]32)
    $bw.Write([uint32]$pngBytes.Length); $bw.Write([uint32]22)
    $bw.Write($pngBytes)
    $bw.Close(); $fs.Close()
    Remove-Item $png -ErrorAction SilentlyContinue
    Write-Host "  icon written: $Icon"
}

# --- 2. pyinstaller build ------------------------------------------------
Write-Host "Building with PyInstaller..."
uv run --with pyinstaller pyinstaller --noconfirm --clean --onedir --windowed `
    --name $Name --icon $Icon gui.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# --- 3. copy the two pipelines (with their venvs) next to the exe ----------
Write-Host "Copying generator/ and clipper/ pipelines..."
New-Item -ItemType Directory -Force -Path (Join-Path $App "generator") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $App "clipper") | Out-Null
robocopy "$Root\generator" "$App\generator" /E /XD output __pycache__ .git /NFL /NDL /NJH /NJS /NP | Out-Null
robocopy "$Root\clipper"   "$App\clipper"   /E /XD output __pycache__ .git /NFL /NDL /NJH /NJS /NP | Out-Null

# --- 4. zip it ------------------------------------------------------------
Write-Host "Zipping app..."
$Zip = Join-Path $Out "$Name.zip"
Remove-Item $Zip -ErrorAction SilentlyContinue
Compress-Archive -Path $App -DestinationPath $Zip -Force

Write-Host ""
Write-Host "Done."
Write-Host "  App folder: $App"
Write-Host "  Zip:        $Zip"
Write-Host ""
Write-Host "Note: ffmpeg must be installed on the machine that runs the app"
Write-Host "      (same requirement as the dev environment)."