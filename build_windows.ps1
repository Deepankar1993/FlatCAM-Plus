# Builds a portable Windows distribution of FlatCAM Evo using PyInstaller.
# Output: dist\FlatCAM_Evo\FlatCAM_Evo.exe
$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
$venv = Join-Path $root '.venv-build'
$py = Join-Path $venv 'Scripts\python.exe'

if (-not (Test-Path $py)) {
    python -m venv $venv
}

& $py -m pip install --upgrade pip wheel

# gdal and rasterio are listed in requirements.txt but never imported by the
# app, and they have no reliable pip wheels on Windows — exclude them.
$reqFile = Join-Path $venv 'requirements-win.txt'
Get-Content (Join-Path $root 'requirements.txt') |
    Where-Object { $_ -notmatch '^\s*(gdal|rasterio)\s*$' } |
    Set-Content $reqFile
& $py -m pip install -r $reqFile pyinstaller

& $py -m PyInstaller --noconfirm --clean (Join-Path $root 'flatcam.spec')

# flatcam.py and appMain.py look for config\configuration.txt next to the
# dist root first (this is also where portable-mode settings are written),
# so place a copy outside _internal as well.
Copy-Item -Recurse -Force (Join-Path $root 'config') (Join-Path $root 'dist\FlatCAM_Evo\config')

Write-Host "Build complete: $(Join-Path $root 'dist\FlatCAM_Evo\FlatCAM_Evo.exe')"
