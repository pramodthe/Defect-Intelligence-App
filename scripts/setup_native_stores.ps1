$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskNeo = Join-Path $taskRoot '.tools\neo4j-5.26.32\neo4j-community-5.26.32'
$taskQdrant = Join-Path $taskRoot '.tools\qdrant-1.19.2\qdrant.exe'
$taskJava = (Get-ChildItem -LiteralPath (Join-Path $taskRoot '.tools\jre21') -Directory | Select-Object -First 1).FullName
if (-not (Test-Path -LiteralPath $taskQdrant) -or -not (Test-Path -LiteralPath (Join-Path $taskNeo 'bin\neo4j.bat'))) { throw 'Unpack the pinned official Qdrant/Neo4j binaries first.' }
$env:JAVA_HOME = $taskJava
$taskConfigPath = Join-Path $taskRoot 'data\native-stores.json'
New-Item -ItemType Directory -Path (Join-Path $taskRoot 'data\logs') -Force | Out-Null
if (Test-Path -LiteralPath $taskConfigPath) {
    $taskConfig = Get-Content -LiteralPath $taskConfigPath -Raw | ConvertFrom-Json
} else {
    $taskConfig = @{neo4j_password=[Guid]::NewGuid().ToString('N')+[Guid]::NewGuid().ToString('N');qdrant_key=[Guid]::NewGuid().ToString('N')+[Guid]::NewGuid().ToString('N');neo_bootstrapped=$false}
}
$taskQdrantConfig = Join-Path $taskRoot 'data\qdrant-config.yaml'
$taskStorage = $(if ($taskConfig.qdrant_storage_path) { [System.IO.Path]::GetFullPath($taskConfig.qdrant_storage_path) } else { Join-Path $taskRoot 'data\qdrant' }).Replace('\','/')
@("telemetry_disabled: true","storage:","  storage_path: '$taskStorage'","service:","  host: '127.0.0.1'","  http_port: 6333","  grpc_port: 6334","  api_key: '$($taskConfig.qdrant_key)'") | Set-Content -LiteralPath $taskQdrantConfig -Encoding utf8
$taskQReady = $false
try { $null=Invoke-RestMethod 'http://127.0.0.1:6333/readyz' -TimeoutSec 2; $taskQReady=$true } catch {}
if (-not $taskQReady) {
    Start-Process -FilePath $taskQdrant -ArgumentList '--config-path',('"'+$taskQdrantConfig+'"') -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskRoot 'data\logs\qdrant.log') -RedirectStandardError (Join-Path $taskRoot 'data\logs\qdrant-error.log') | Out-Null
}
$taskNeoConfig = Join-Path $taskNeo 'conf\neo4j.conf'
$taskNeoData = (Join-Path $taskRoot 'data\neo4j').Replace('\','/')
$taskNeoLogs = (Join-Path $taskRoot 'data\logs\neo4j').Replace('\','/')
@("server.default_listen_address=127.0.0.1","server.bolt.enabled=true","server.bolt.listen_address=127.0.0.1:7687","server.http.enabled=false","server.https.enabled=false","server.directories.data=$taskNeoData","server.directories.logs=$taskNeoLogs","server.memory.heap.initial_size=256m","server.memory.heap.max_size=512m","server.memory.pagecache.size=256m","dbms.usage_report.enabled=false") | Set-Content -LiteralPath $taskNeoConfig -Encoding utf8
if (-not $taskConfig.neo_bootstrapped) {
    & (Join-Path $taskNeo 'bin\neo4j-admin.bat') dbms set-initial-password $taskConfig.neo4j_password
    if ($LASTEXITCODE -ne 0) { throw 'Neo4j authentication bootstrap failed.' }
    $taskConfig.neo_bootstrapped=$true
}
$taskConfig | ConvertTo-Json | Set-Content -LiteralPath $taskConfigPath -Encoding utf8
$taskSocket = New-Object System.Net.Sockets.TcpClient
try { $taskSocket.Connect('127.0.0.1',7687); $taskNReady=$true } catch { $taskNReady=$false } finally { $taskSocket.Dispose() }
if (-not $taskNReady) {
    $taskNeoCmd = '""' + (Join-Path $taskNeo 'bin\neo4j.bat') + '" console"'
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/d','/c',$taskNeoCmd -WorkingDirectory $taskNeo -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskRoot 'data\logs\neo4j-console.log') -RedirectStandardError (Join-Path $taskRoot 'data\logs\neo4j-error.log') | Out-Null
}
$taskEnvPath = Join-Path $taskRoot '.env'
$taskEnv = [System.IO.File]::ReadAllText($taskEnvPath)
$taskEnv = [regex]::Replace($taskEnv,'(?m)^(NEO4J_URI|NEO4J_USER|NEO4J_PASSWORD|QDRANT_URL|QDRANT_KEY)=.*\r?\n?','')
$taskEnv += "`nNEO4J_URI=bolt://127.0.0.1:7687`nNEO4J_USER=neo4j`nNEO4J_PASSWORD=$($taskConfig.neo4j_password)`nQDRANT_URL=http://127.0.0.1:6333`nQDRANT_KEY=$($taskConfig.qdrant_key)`n"
[System.IO.File]::WriteAllText($taskEnvPath,$taskEnv)
Write-Host 'Authenticated local Neo4j and Qdrant launched. Credentials remain in private data/.env; restart API and worker to connect.'
