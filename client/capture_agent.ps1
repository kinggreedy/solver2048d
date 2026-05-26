# capture_agent.ps1
# Windows PowerShell Agent for Solver 2048d Client-Server capture system
# Requirements: adb.exe (with phone connected in debugging mode)

# Get the folder where this script is located
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $scriptDir) { $scriptDir = "." }

# --- DEFAULT CONFIGURATION ---
$server = "http://localhost:5000"   # Configure with your Ubuntu server IP/port
$pollIntervalMs = 500              # Poll server status every 500ms
$errorRateLimitSeconds = 5        # Limit connection error prints to once every 5s
$adbPath = "adb"                  # Command name or full path to adb
$curlPath = "curl.exe"            # Command name or full path to curl
# -----------------------------

# Load local configuration file if it exists (allows local overrides without committing personal paths)
$configFile = Join-Path $scriptDir "client_config.ps1"
if (Test-Path $configFile) {
    Write-Host "Loading local config from $configFile" -ForegroundColor Green
    . $configFile
}

# Resolve/Validate adbPath
$resolvedAdb = $null
if (Get-Command $adbPath -ErrorAction SilentlyContinue) {
    $resolvedAdb = (Get-Command $adbPath).Source
} elseif (Test-Path $adbPath) {
    $resolvedAdb = $adbPath
} else {
    # Try common fallback paths
    $commonAdbPaths = @(
        "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe",
        "$env:USERPROFILE\AppData\Local\Android\Sdk\platform-tools\adb.exe",
        "C:\Program Files (x86)\Android\android-sdk\platform-tools\adb.exe",
        "C:\Program Files\Android\android-sdk\platform-tools\adb.exe",
        "C:\Program Files\scrcpy\adb.exe"
    )
    foreach ($p in $commonAdbPaths) {
        if (Test-Path $p) {
            $resolvedAdb = $p
            break
        }
    }
}

if (-not $resolvedAdb) {
    Write-Error "Error: 'adb' command or executable was not found."
    Write-Host "Please add adb to your system PATH, or create 'client_config.ps1' in this directory and define `$adbPath." -ForegroundColor Yellow
    exit 1
}
$adbPath = $resolvedAdb

# Resolve/Validate curlPath
$resolvedCurl = $null
if (Get-Command $curlPath -ErrorAction SilentlyContinue) {
    $resolvedCurl = (Get-Command $curlPath).Source
} elseif (Test-Path $curlPath) {
    $resolvedCurl = $curlPath
} else {
    $commonCurlPaths = @(
        "C:\Windows\System32\curl.exe"
    )
    foreach ($p in $commonCurlPaths) {
        if (Test-Path $p) {
            $resolvedCurl = $p
            break
        }
    }
}

if (-not $resolvedCurl) {
    Write-Error "Error: 'curl.exe' command or executable was not found."
    Write-Host "Please add curl to your system PATH, or define `$curlPath in 'client_config.ps1'." -ForegroundColor Yellow
    exit 1
}
$curlPath = $resolvedCurl

$lastErrorTime = [DateTime]::MinValue

Write-Host "=== Windows Capture Agent Running ==="
Write-Host "Target Server: $server"
Write-Host "ADB Path:      $adbPath"
Write-Host "Curl Path:     $curlPath"
Write-Host "Polling every $pollIntervalMs ms. Press Ctrl+C to stop."
Write-Host "======================================"

# Ensure output goes to script directory
$screenshotFile = Join-Path $scriptDir "latest.png"

while ($true) {
    try {
        # Poll the server to check if a screenshot is requested
        $response = Invoke-RestMethod -Uri "$server/capture/poll" -Method Get -TimeoutSec 3

        if ($response.capture_requested) {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Capture requested! Taking adb screencap..."

            # Execute adb screencap and pipe raw output to latest.png using cmd /c
            # (cmd /c redirection preserves binary stream format, avoiding PowerShell character encoding corruption)
            $cmd = "`"$adbPath`" exec-out screencap -p > `"$screenshotFile`""
            cmd /c $cmd

            if ($LASTEXITCODE -eq 0 -and (Test-Path $screenshotFile)) {
                Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Uploading latest.png to server..."

                # Upload PNG using curl.exe
                & $curlPath -s -F "file=@$screenshotFile" "$server/capture/upload"
                Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Screenshot uploaded successfully."
            } else {
                Write-Warning "adb command failed or latest.png was not created. Is your Android device connected via ADB?"
            }
        }
    } catch {
        # Rate-limit warnings to avoid spam
        $now = [DateTime]::Now
        if (($now - $lastErrorTime).TotalSeconds -ge $errorRateLimitSeconds) {
            Write-Warning "[$(Get-Date -Format 'HH:mm:ss')] Error: $_"
            $lastErrorTime = $now
        }
    }

    Start-Sleep -Milliseconds $pollIntervalMs
}
