# Platform Studio - local launcher (native, no Docker).
#
# Starts both halves with hot reload:
#   - studio backend  -> http://127.0.0.1:8917   (FastAPI; PORT env below)
#   - studio frontend -> http://localhost:5217   (vite; /api proxied to :8917)
#
# First run provisions everything:
#   - backend venv + deps (the install conformance checks run in-process)
#   - frontend node_modules (npm ci) and the generated API types (api:generate)
# Subsequent runs just spawn the two server windows.
#
# Requires the sibling-clone topology: the platform checkout must exist at
# <workspace>/foundry-platform next to this platform-studio checkout, parked
# on the install's deploy branch (STUDIO_DEPLOY_BRANCH).
#
# Run by double-clicking start.bat, or:
#   powershell -ExecutionPolicy Bypass -File devops\start.ps1

$ErrorActionPreference = 'Stop'

$studio     = Split-Path -Parent $PSScriptRoot
$workspace  = Split-Path -Parent $studio
$backend    = Join-Path $studio 'studio-backend'
$frontend   = Join-Path $studio 'studio-frontend'
$py         = Join-Path $backend '.venv\Scripts\python.exe'

Write-Host '== Platform Studio (native dev) ==' -ForegroundColor Cyan

# --- Resolve and verify the platform checkout the studio manages ---------------
# Convention: foundry-platform cloned as a sibling of platform-studio under one
# workspace. STUDIO_PLATFORM_ROOT overrides for non-sibling setups; the spawned
# backend is pinned to whichever path this check validated.
$platform = $env:STUDIO_PLATFORM_ROOT
if ([string]::IsNullOrWhiteSpace($platform)) {
    $platform = Join-Path $workspace 'foundry-platform'
}
if (-not (Test-Path (Join-Path $platform 'foundry.yaml'))) {
    Write-Warning "No install checkout found at $platform (foundry.yaml missing)."
    Write-Warning 'Clone foundry-platform as a sibling of platform-studio (or set STUDIO_PLATFORM_ROOT) and check out the install deploy branch, then re-run.'
    Read-Host 'Press Enter to exit'
    exit 1
}
Write-Host "Platform checkout -> $platform" -ForegroundColor Green

# --- First-run setup: backend -------------------------------------------------
if (-not (Test-Path $py)) {
    Write-Host 'First run: creating backend venv and installing deps...'
    python -m venv (Join-Path $backend '.venv')
    & $py -m pip install --quiet -e "$backend[dev]"
}

# --- First-run setup: frontend -------------------------------------------------
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Write-Host 'First run: installing frontend deps...'
    Push-Location $frontend
    npm ci
    Pop-Location
}
if (-not (Test-Path (Join-Path $frontend 'src\models\index.ts'))) {
    Write-Host 'First run: generating API types from openapi.json...'
    Push-Location $frontend
    npm run api:generate
    Pop-Location
}

# --- Launch both servers in their own PowerShell windows -----------------------
Write-Host 'Studio backend  -> http://127.0.0.1:8917' -ForegroundColor Green
Start-Process pwsh -ArgumentList '-NoExit', '-Command',
    "`$Host.UI.RawUI.WindowTitle = 'Platform Studio backend (:8917)'; `$env:PORT='8917'; `$env:STUDIO_PLATFORM_ROOT='$platform'; & '$py' -m studio.adapters.inbound.http.run" `
    -WorkingDirectory $backend

Write-Host 'Studio frontend -> http://localhost:5217' -ForegroundColor Green
Start-Process pwsh -ArgumentList '-NoExit', '-Command',
    "`$Host.UI.RawUI.WindowTitle = 'Platform Studio frontend (:5217)'; npm run dev -- --port 5217 --strictPort" `
    -WorkingDirectory $frontend

Start-Sleep -Seconds 4
Start-Process 'http://localhost:5217'
Write-Host 'Started. Two PowerShell windows host the servers; close them to stop.' -ForegroundColor Green
