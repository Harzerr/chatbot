param(
  [string]$CondaEnv = "chatbot",
  [string]$SessionName = "chatbot_stack_win",
  [string]$QdrantContainerName = "qdrant",
  [switch]$SkipInfra,
  [switch]$SkipFrontend,
  [switch]$SkipLivekit
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendDir = Join-Path $ProjectDir "frontend"
$Judge0Dir = Join-Path $ProjectDir "tools/judge0-v1.13.1"
$LivekitDir = Join-Path $ProjectDir "tools/livekit"
$QdrantStorageDir = Join-Path $ProjectDir "qdrant_storage"
$LogRoot = Join-Path $ProjectDir "logs"
$RunId = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$LogDir = Join-Path $LogRoot $RunId
$LatestLogDir = Join-Path $LogRoot "latest"
$StatePath = Join-Path $LogRoot "windows_stack_state.json"
$LatestRunPath = Join-Path $LogRoot "latest_windows_run.txt"

function Write-Info([string]$Message) {
  Write-Host "[start_windows] $Message"
}

function Ensure-Command([string]$CommandName, [string]$Hint) {
  if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
    throw "$CommandName not found. $Hint"
  }
}

function Test-PidRunning([int]$ProcessId) {
  try {
    Get-Process -Id $ProcessId -ErrorAction Stop | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Invoke-NativeLoggedCommand(
  [scriptblock]$Command,
  [string]$LogPath
) {
  # Native tools frequently write progress/info to stderr.
  # Disable stderr->ErrorRecord mapping when available, then enforce by exit code.
  $prevErrorAction = $ErrorActionPreference
  $hasNativePref = Test-Path Variable:PSNativeCommandUseErrorActionPreference
  if ($hasNativePref) {
    $prevNativePref = $PSNativeCommandUseErrorActionPreference
  }
  try {
    $ErrorActionPreference = "Continue"
    if ($hasNativePref) {
      $PSNativeCommandUseErrorActionPreference = $false
    }
    & $Command 2>&1 | Tee-Object -FilePath $LogPath -Append
    $exitCode = $LASTEXITCODE
  } finally {
    if ($hasNativePref) {
      $PSNativeCommandUseErrorActionPreference = $prevNativePref
    }
    $ErrorActionPreference = $prevErrorAction
  }

  if ($exitCode -ne 0) {
    throw "Command failed with exit code $exitCode."
  }
}

function Try-NativeLoggedCommand(
  [scriptblock]$Command,
  [string]$LogPath
) {
  try {
    [void](Invoke-NativeLoggedCommand -Command $Command -LogPath $LogPath)
    return $true
  } catch {
    return $false
  }
}

function Test-DockerContainerExists([string]$ContainerName) {
  $output = docker ps -a --filter "name=^/$ContainerName$" --format "{{.Names}}"
  return $output -eq $ContainerName
}

function Repair-QdrantStorageIfNeeded() {
  $collectionsDir = Join-Path $QdrantStorageDir "collections"
  if (-not (Test-Path $collectionsDir)) {
    return
  }

  $corruptedFiles = Get-ChildItem -Path $collectionsDir -Recurse -Filter "config.json" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -like "*\payload_storage\config.json" -and $_.Length -eq 0 }

  if ($corruptedFiles.Count -eq 0) {
    return
  }

  $corruptedCollections = [System.Collections.Generic.HashSet[string]]::new()
  $escapedCollectionsDir = [regex]::Escape($collectionsDir)

  foreach ($file in $corruptedFiles) {
    if ($file.FullName -match "^$escapedCollectionsDir\\([^\\]+)\\") {
      [void]$corruptedCollections.Add($matches[1])
    }
  }

  if ($corruptedCollections.Count -eq 0) {
    return
  }

  $backupRoot = Join-Path $QdrantStorageDir ("_corrupt_backup\" + (Get-Date -Format "yyyy-MM-dd_HH-mm-ss"))
  New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null

  foreach ($collectionName in $corruptedCollections) {
    $sourcePath = Join-Path $collectionsDir $collectionName
    if (-not (Test-Path $sourcePath)) {
      continue
    }
    Move-Item -LiteralPath $sourcePath -Destination $backupRoot -Force
    Write-Info "Moved corrupted qdrant collection '$collectionName' to $backupRoot"
  }
}

function Wait-QdrantReady([int]$TimeoutSeconds = 45) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    try {
      $resp = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:6333/collections" -TimeoutSec 3
      if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
        return $true
      }
    } catch {
      # keep waiting
    }
    Start-Sleep -Seconds 1
  }
  return $false
}

function Set-LatestLogPointer([string]$TargetLogDir) {
  $resolvedLogRoot = (Resolve-Path -LiteralPath $LogRoot).Path
  $resolvedTarget = (Resolve-Path -LiteralPath $TargetLogDir).Path
  if (-not $resolvedTarget.StartsWith($resolvedLogRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to point logs/latest outside logs root: $resolvedTarget"
  }

  if (Test-Path -LiteralPath $LatestLogDir) {
    Remove-Item -LiteralPath $LatestLogDir -Recurse -Force
  }

  try {
    New-Item -ItemType Junction -Path $LatestLogDir -Target $resolvedTarget | Out-Null
    Write-Info "Updated logs/latest -> $resolvedTarget (junction)"
    return
  } catch {
    Write-Info "Failed to create logs/latest junction: $($_.Exception.Message)"
  }

  try {
    New-Item -ItemType SymbolicLink -Path $LatestLogDir -Target $resolvedTarget | Out-Null
    Write-Info "Updated logs/latest -> $resolvedTarget (symbolic link)"
    return
  } catch {
    Write-Info "Failed to create logs/latest symbolic link: $($_.Exception.Message)"
  }

  New-Item -ItemType Directory -Force -Path $LatestLogDir | Out-Null
  Write-Info "logs/latest link creation failed; created plain directory fallback at $LatestLogDir"
}

function Ensure-QdrantStarted() {
  $qdrantLog = Join-Path $LogDir "qdrant.log"
  New-Item -ItemType Directory -Force -Path $QdrantStorageDir | Out-Null
  Repair-QdrantStorageIfNeeded

  Write-Info "Ensuring qdrant container is running: $QdrantContainerName"

  if (-not (Test-DockerContainerExists -ContainerName $QdrantContainerName)) {
    Write-Info "Qdrant container not found, creating a new one."
    Invoke-NativeLoggedCommand `
      -Command {
        docker run -d --name $QdrantContainerName `
          -p 6333:6333 -p 6334:6334 `
          -v "${QdrantStorageDir}:/qdrant/storage" `
          qdrant/qdrant:latest
      } `
      -LogPath $qdrantLog
    Write-Info "Qdrant container created."
  } else {
    Write-Info "Starting existing qdrant container: $QdrantContainerName"
    Invoke-NativeLoggedCommand -Command { docker start $QdrantContainerName } -LogPath $qdrantLog
  }

  if (-not (Wait-QdrantReady -TimeoutSeconds 45)) {
    Invoke-NativeLoggedCommand -Command { docker logs $QdrantContainerName --tail 120 } -LogPath $qdrantLog
    throw "Qdrant container failed readiness check. See $qdrantLog"
  }

  Write-Info "Qdrant started and ready."
}

function Ensure-Judge0Started() {
  $judge0Log = Join-Path $LogDir "judge0.log"
  if (-not (Test-Path $Judge0Dir)) {
    Write-Info "Judge0 directory not found, skipping: $Judge0Dir"
    return
  }

  Write-Info "Starting Judge0 docker compose"
  Push-Location $Judge0Dir
  try {
    Invoke-NativeLoggedCommand -Command { docker compose up -d } -LogPath $judge0Log
  } finally {
    Pop-Location
  }
}

function Ensure-LivekitInfraStarted() {
  $livekitInfraLog = Join-Path $LogDir "livekit_infra.log"
  if (-not (Test-Path $LivekitDir)) {
    Write-Info "LiveKit infra directory not found, skipping: $LivekitDir"
    return
  }

  Write-Info "Starting LiveKit docker compose"
  Push-Location $LivekitDir
  try {
    Invoke-NativeLoggedCommand -Command { docker compose up -d } -LogPath $livekitInfraLog
  } finally {
    Pop-Location
  }
}

function Start-BackgroundService([hashtable]$Service, [string]$EnvName) {
  $workdirEsc = $Service.workdir.Replace("'", "''")
  $cmdEsc = $Service.command.Replace("'", "''")
  $logEsc = $Service.logfile.Replace("'", "''")
  $nameEsc = $Service.name.Replace("'", "''")
  $envEsc = $EnvName.Replace("'", "''")

  $childScript = @"
`$ErrorActionPreference = 'Stop'
Set-Location '$workdirEsc'
& conda 'shell.powershell' 'hook' | Out-String | Invoke-Expression
conda activate '$envEsc'
Write-Host '[$nameEsc] logging to $logEsc'
`$prevErrorAction = `$ErrorActionPreference
`$hasNativePref = Test-Path Variable:PSNativeCommandUseErrorActionPreference
if (`$hasNativePref) {
  `$prevNativePref = `$PSNativeCommandUseErrorActionPreference
}
try {
  `$ErrorActionPreference = 'Continue'
  if (`$hasNativePref) {
    `$PSNativeCommandUseErrorActionPreference = `$false
  }
  Invoke-Expression '$cmdEsc' 2>&1 | Tee-Object -FilePath '$logEsc' -Append
  `$exitCode = `$LASTEXITCODE
} finally {
  if (`$hasNativePref) {
    `$PSNativeCommandUseErrorActionPreference = `$prevNativePref
  }
  `$ErrorActionPreference = `$prevErrorAction
}
if (`$exitCode -ne 0) {
  throw 'Service exited with code ' + `$exitCode
}
"@

  $proc = Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $childScript) `
    -PassThru `
    -WindowStyle Minimized

  return [PSCustomObject]@{
    name = $Service.name
    pid = $proc.Id
    command = $Service.command
    workdir = $Service.workdir
    logfile = $Service.logfile
  }
}

Ensure-Command -CommandName "powershell.exe" -Hint "Use Windows PowerShell."
Ensure-Command -CommandName "conda" -Hint "Install Anaconda/Miniconda and make sure conda is in PATH."

if (Test-Path $StatePath) {
  $existing = Get-Content $StatePath -Raw | ConvertFrom-Json
  $alive = @($existing.processes | Where-Object { Test-PidRunning -ProcessId $_.pid })
  if ($alive.Count -gt 0) {
    $aliveNames = ($alive | ForEach-Object { "$($_.name)(PID=$($_.pid))" }) -join ", "
    throw "Another stack appears to be running: $aliveNames. Run .\stop_windows.ps1 first."
  }
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Content -Path $LatestRunPath -Value $RunId -Encoding UTF8
Set-LatestLogPointer -TargetLogDir $LogDir

if (-not $SkipInfra) {
  if (Get-Command "docker" -ErrorAction SilentlyContinue) {
    try {
      Ensure-QdrantStarted
    } catch {
      Write-Info "Qdrant auto-start failed: $($_.Exception.Message)"
    }

    try {
      Ensure-Judge0Started
    } catch {
      Write-Info "Judge0 auto-start failed: $($_.Exception.Message)"
    }

    if (-not $SkipLivekit) {
      try {
        Ensure-LivekitInfraStarted
      } catch {
        Write-Info "LiveKit infra auto-start failed: $($_.Exception.Message)"
      }
    }
  } else {
    Write-Info "docker not found, skipping qdrant/judge0/livekit infra startup."
  }
}

$services = @(
  @{
    name = "mcp_search"
    workdir = $ProjectDir
    command = "python -m app.mcp_server.search_server"
    logfile = Join-Path $LogDir "mcp_search.log"
  },
  @{
    name = "mcp_scrape"
    workdir = $ProjectDir
    command = "python -m app.mcp_server.web_scrapping_server"
    logfile = Join-Path $LogDir "mcp_scrape.log"
  },
  @{
    name = "backend"
    workdir = $ProjectDir
    command = '$env:UVICORN_PORT=''8010''; python app.py'
    logfile = Join-Path $LogDir "backend.log"
  }
)

if (-not $SkipLivekit) {
  $services += @{
    name = "livekit"
    workdir = $ProjectDir
    command = "python app/agent/livekit_agent.py dev"
    logfile = Join-Path $LogDir "livekit.log"
  }
}

if (-not $SkipFrontend) {
  if (-not (Test-Path $FrontendDir)) {
    throw "frontend directory not found: $FrontendDir"
  }
  $services += @{
    name = "frontend"
    workdir = $FrontendDir
    command = "Remove-Item Env:HOST -ErrorAction SilentlyContinue; Remove-Item Env:WDS_SOCKET_HOST -ErrorAction SilentlyContinue; `$env:DANGEROUSLY_DISABLE_HOST_CHECK='true'; npm start"
    logfile = Join-Path $LogDir "frontend.log"
  }
}

$started = @()
foreach ($svc in $services) {
  Write-Info "Starting $($svc.name)"
  $started += Start-BackgroundService -Service $svc -EnvName $CondaEnv
}

$state = [PSCustomObject]@{
  session_name = $SessionName
  started_at = (Get-Date).ToString("s")
  project_dir = $ProjectDir
  conda_env = $CondaEnv
  log_dir = $LogDir
  processes = $started
}
$state | ConvertTo-Json -Depth 6 | Set-Content -Path $StatePath -Encoding UTF8

Write-Info "All services launched in background."
Write-Info "State file: $StatePath"
Write-Info "Logs dir  : $LogDir"
Write-Info "Tail logs : Get-Content '$LogDir\\backend.log' -Wait"
Write-Info "Stop stack: .\\stop_windows.ps1"
