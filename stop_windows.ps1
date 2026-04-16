param(
  [switch]$KeepJudge0,
  [switch]$KeepLivekitInfra,
  [switch]$KeepQdrant,
  [string]$QdrantContainerName = "qdrant"
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogRoot = Join-Path $ProjectDir "logs"
$StatePath = Join-Path $LogRoot "windows_stack_state.json"
$Judge0Dir = Join-Path $ProjectDir "tools/judge0-v1.13.1"
$LivekitDir = Join-Path $ProjectDir "tools/livekit"

function Write-Info([string]$Message) {
  Write-Host "[stop_windows] $Message"
}

function Test-PidRunning([int]$ProcessId) {
  try {
    Get-Process -Id $ProcessId -ErrorAction Stop | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Find-ServiceFallbackPids([string]$ServiceName) {
  $patterns = switch ($ServiceName) {
    "mcp_search" { @("app.mcp_server.search_server") }
    "mcp_scrape" { @("app.mcp_server.web_scrapping_server") }
    "backend"    { @(" app.py", "\app.py") }
    "livekit"    { @("livekit_agent.py") }
    "frontend"   { @("react-scripts", "scripts\start.js") }
    default      { @() }
  }

  if ($patterns.Count -eq 0) {
    return @()
  }

  $matches = Get-CimInstance Win32_Process | Where-Object {
    if (-not $_.CommandLine) { return $false }
    foreach ($ptn in $patterns) {
      if ($_.CommandLine -like "*$ptn*") { return $true }
    }
    return $false
  }

  return @($matches | Select-Object -ExpandProperty ProcessId -Unique)
}

function Invoke-NativeCommand([scriptblock]$Command) {
  $prevErrorAction = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    & $Command 2>&1 | Out-Host
    $exitCode = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $prevErrorAction
  }

  if ($exitCode -ne 0) {
    throw "Command failed with exit code $exitCode."
  }
}

function Test-DockerContainerExists([string]$ContainerName) {
  $prevErrorAction = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    & docker container inspect $ContainerName *> $null
    return ($LASTEXITCODE -eq 0)
  } finally {
    $ErrorActionPreference = $prevErrorAction
  }
}

if (Test-Path $StatePath) {
  $state = Get-Content $StatePath -Raw | ConvertFrom-Json
  if ($null -eq $state.processes) {
    Write-Info "State file has no process list, removing stale state."
    Remove-Item -LiteralPath $StatePath -Force
  } else {
    foreach ($proc in $state.processes) {
      $targetPid = [int]$proc.pid
      $didStopAny = $false

      if (Test-PidRunning -ProcessId $targetPid) {
        try {
          Stop-Process -Id $targetPid -Force -ErrorAction Stop
          Write-Info "Stopped $($proc.name) (PID=$targetPid)"
          $didStopAny = $true
        } catch {
          Write-Info "Failed to stop PID=${targetPid}: $($_.Exception.Message)"
        }
      }

      $fallbackPids = @(Find-ServiceFallbackPids -ServiceName $proc.name)
      foreach ($fallbackPid in $fallbackPids) {
        if (-not (Test-PidRunning -ProcessId $fallbackPid)) {
          continue
        }
        try {
          Stop-Process -Id $fallbackPid -Force -ErrorAction Stop
          Write-Info "Stopped orphan $($proc.name) process (PID=$fallbackPid)"
          $didStopAny = $true
        } catch {
          Write-Info "Failed to stop orphan PID=${fallbackPid}: $($_.Exception.Message)"
        }
      }

      if (-not $didStopAny) {
        Write-Info "$($proc.name) already exited (PID=$targetPid)"
      }
    }

    Remove-Item -LiteralPath $StatePath -Force
  }
} else {
  Write-Info "No state file found: $StatePath"
  Write-Info "Will still try to stop infra services."
}

if (Get-Command "docker" -ErrorAction SilentlyContinue) {
  if (-not $KeepJudge0) {
    if (Test-Path $Judge0Dir) {
      try {
        Push-Location $Judge0Dir
        Invoke-NativeCommand -Command { docker compose down }
        Write-Info "Judge0 stopped."
      } catch {
        Write-Info "Judge0 stop failed: $($_.Exception.Message)"
      } finally {
        Pop-Location
      }
    } else {
      Write-Info "Judge0 directory not found, skipped: $Judge0Dir"
    }
  } else {
    Write-Info "KeepJudge0 enabled, skip stopping Judge0."
  }

  if (-not $KeepLivekitInfra) {
    if (Test-Path $LivekitDir) {
      try {
        Push-Location $LivekitDir
        Invoke-NativeCommand -Command { docker compose down }
        Write-Info "LiveKit infra stopped."
      } catch {
        Write-Info "LiveKit infra stop failed: $($_.Exception.Message)"
      } finally {
        Pop-Location
      }
    } else {
      Write-Info "LiveKit directory not found, skipped: $LivekitDir"
    }
  } else {
    Write-Info "KeepLivekitInfra enabled, skip stopping LiveKit docker."
  }

  if (-not $KeepQdrant) {
    try {
      if (Test-DockerContainerExists -ContainerName $QdrantContainerName) {
        Invoke-NativeCommand -Command { docker stop $QdrantContainerName }
        Write-Info "Qdrant container stopped: $QdrantContainerName"
      } else {
        Write-Info "Qdrant container not found, skipped: $QdrantContainerName"
      }
    } catch {
      Write-Info "Qdrant stop failed: $($_.Exception.Message)"
    }
  } else {
    Write-Info "KeepQdrant enabled, skip stopping qdrant."
  }
} else {
  Write-Info "docker not found, skipped stopping judge0/livekit infra/qdrant."
}

Write-Info "Stack shutdown complete."
