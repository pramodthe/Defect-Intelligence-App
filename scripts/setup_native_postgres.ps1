param([int]$Port = 5433)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskBin = Join-Path $taskRoot '.tools\postgresql-17.6\pgsql\bin'
if (-not (Test-Path -LiteralPath (Join-Path $taskBin 'initdb.exe'))) { throw 'Unpack official PostgreSQL 17.6 binaries into .tools\postgresql-17.6 first.' }
$taskData = Join-Path $taskRoot 'data\postgres'
$taskConfigPath = Join-Path $taskRoot 'data\postgres-local.json'
New-Item -ItemType Directory -Path (Join-Path $taskRoot 'data\logs') -Force | Out-Null
if (Test-Path -LiteralPath $taskConfigPath) {
    $taskConfig = Get-Content -LiteralPath $taskConfigPath -Raw | ConvertFrom-Json
} else {
    $taskConfig = @{password = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N'); port = $Port}
    $taskConfig | ConvertTo-Json | Set-Content -LiteralPath $taskConfigPath -Encoding utf8
}
if (-not (Test-Path -LiteralPath (Join-Path $taskData 'PG_VERSION'))) {
    $taskPasswordFile = Join-Path $taskRoot 'data\pg-bootstrap-password.txt'
    [System.IO.File]::WriteAllText($taskPasswordFile,$taskConfig.password)
    & (Join-Path $taskBin 'initdb.exe') -D $taskData -U defect -A scram-sha-256 --pwfile=$taskPasswordFile --encoding=UTF8 --locale=C
    if ($LASTEXITCODE -ne 0) { throw 'Local PostgreSQL initialization failed.' }
    Remove-Item -LiteralPath $taskPasswordFile
}
& (Join-Path $taskBin 'pg_ctl.exe') -D $taskData status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    & (Join-Path $taskBin 'pg_ctl.exe') -D $taskData -l (Join-Path $taskRoot 'data\logs\postgres.log') -o "-h 127.0.0.1 -p $($taskConfig.port)" -w start
    if ($LASTEXITCODE -ne 0) { throw 'Local PostgreSQL startup failed.' }
}
$taskOldPgPassword = $env:PGPASSWORD
try {
    $env:PGPASSWORD = $taskConfig.password
    $taskExists = & (Join-Path $taskBin 'psql.exe') -h 127.0.0.1 -p $taskConfig.port -U defect -d postgres -t -A -c "SELECT 1 FROM pg_database WHERE datname='checkpoints'"
    if ($taskExists -ne '1') { & (Join-Path $taskBin 'createdb.exe') -h 127.0.0.1 -p $taskConfig.port -U defect checkpoints }
} finally { $env:PGPASSWORD = $taskOldPgPassword }
$taskEnvPath = Join-Path $taskRoot '.env'
$taskEnv = if (Test-Path -LiteralPath $taskEnvPath) { [System.IO.File]::ReadAllText($taskEnvPath) } else { '' }
$taskEnv = [regex]::Replace($taskEnv,'(?m)^(CHECKPOINT_BACKEND|LANGGRAPH_CHECKPOINT_DSN)=.*\r?\n?','')
$taskEnv += "`nCHECKPOINT_BACKEND=postgres`nLANGGRAPH_CHECKPOINT_DSN=postgresql://defect:$($taskConfig.password)@127.0.0.1:$($taskConfig.port)/checkpoints`n"
[System.IO.File]::WriteAllText($taskEnvPath,$taskEnv)
Write-Host "Authenticated local PostgreSQL is ready on 127.0.0.1:$($taskConfig.port). Restart API/worker to use it."
