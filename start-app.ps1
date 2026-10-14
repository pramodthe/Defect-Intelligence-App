param([switch]$Native, [switch]$NoBrowser, [switch]$Restart)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if ($Native) {
    if ($Restart) {
        $taskPythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
            $_.ExecutablePath -eq $taskPythonPath -and
            (($_.CommandLine -match '-m\s+uvicorn\s+app\.main:app' -and $_.CommandLine -match '--port\s+8000(?:\s|$)') -or $_.CommandLine -match '-m\s+app\.worker')
        } | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
    }
    if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'data\postgres-local.json')) { & (Join-Path $PSScriptRoot 'scripts\setup_native_postgres.ps1') }
    if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'data\native-stores.json')) { & (Join-Path $PSScriptRoot 'scripts\setup_native_stores.ps1') }
    $taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run uv sync --locked --extra models first.' }
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'web\dist\index.html'))) { throw 'Run pnpm build in web first.' }
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.env'))) {
        @('WORKSPACE_ROOT=data', 'CHECKPOINT_BACKEND=sqlite-dev', 'TEXT_PROVIDER=disabled', 'VISION_ENABLED=false') | Set-Content -LiteralPath '.env' -Encoding utf8
    }
    New-Item -ItemType Directory -Path 'data\logs' -Force | Out-Null
    $taskApiReady = $false
    try { $null = Invoke-RestMethod 'http://127.0.0.1:8000/api/health' -TimeoutSec 10; $taskApiReady = $true } catch {}
    if (-not $taskApiReady) {
        $taskApi = Start-Process -FilePath $taskPython -ArgumentList '-u','-m','uvicorn','app.main:app','--loop','app.runtime:selector_loop_factory','--host','127.0.0.1','--port','8000','--no-access-log' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput 'data\logs\api.log' -RedirectStandardError 'data\logs\api-error.log'
    }
    $taskHealth = $null
    for ($taskAttempt=0; $taskAttempt -lt 30; $taskAttempt++) {
        try { $taskHealth = Invoke-RestMethod 'http://127.0.0.1:8000/api/health' -TimeoutSec 10; break } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $taskHealth) { throw 'Local API did not start. Inspect data\logs\api-error.log.' }
    $taskWorkerProcess = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match '-m\s+app\.worker' -and $_.CommandLine -match [regex]::Escape($PSScriptRoot) } | Select-Object -First 1
    if ($taskHealth.services.worker -ne 'ready' -or -not $taskWorkerProcess) {
        $taskWorker = Start-Process -FilePath $taskPython -ArgumentList '-u','-m','app.worker' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput 'data\logs\worker.log' -RedirectStandardError 'data\logs\worker-error.log'
    }
    Write-Host "Local app: http://127.0.0.1:8000 · Checkpoints: $($taskHealth.services.checkpoints)"
} else {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker Desktop with Compose is required. Use -Native for the isolated local development profile.' }
    & docker compose version
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose is unavailable.' }
    if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
    $taskEnv = [System.IO.File]::ReadAllText((Join-Path $PSScriptRoot '.env'))
    foreach ($taskKey in @('POSTGRES_PASSWORD','NEO4J_PASSWORD','QDRANT_KEY')) {
        if ($taskEnv -notmatch "(?m)^$taskKey=.+$") {
            $taskSecret = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')
            $taskEnv = [regex]::Replace($taskEnv,"(?m)^$taskKey=.*\r?\n?",'')
            $taskEnv += "`n$taskKey=$taskSecret`n"
        }
    }
    [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot '.env'),$taskEnv)
    & docker compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Compose configuration validation failed.' }
    & docker compose up --build -d
    if ($LASTEXITCODE -ne 0) { throw 'Compose startup failed.' }
    Write-Host 'Five-service stack started. Inspect readiness at http://127.0.0.1:8000/api/health.'
}
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:8000' }
