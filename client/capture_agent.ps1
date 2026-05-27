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

# Swipe gestures (x1 y1 x2 y2 duration_ms) - customizable via client_config.ps1
$swipeLeft  = @("780", "1325", "240", "1325", "120")
$swipeRight = @("240", "1325", "780", "1325", "120")
$swipeUp    = @("512", "1560", "512", "1090", "120")
$swipeDown  = @("512", "1090", "512", "1560", "120")
$postSwipeSleepMs = 1000
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
$lastSeenActionSeq = $null

function Upload-Screenshot {
    param (
        [string]$filePath,
        [string]$url
    )

    $maxRetries = 3
    $attempt = 1
    $uploaded = $false

    while ($attempt -le $maxRetries -and -not $uploaded) {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Uploading $(Split-Path -Leaf $filePath) (attempt $attempt/$maxRetries)..."
        $responseStr = & $curlPath -s -F "file=@$filePath" $url

        $success = $false
        if ($LASTEXITCODE -eq 0 -and $responseStr) {
            try {
                $resObj = $responseStr | ConvertFrom-Json
                if ($resObj.status -eq "success") {
                    $uploaded = $true
                    $success = $true
                    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Upload completed successfully."
                } elseif ($resObj.retry) {
                    Write-Warning "Server requested retry: $($resObj.message)"
                } else {
                    Write-Warning "Server returned upload error: $($resObj.message)"
                }
            } catch {
                Write-Warning "Failed to parse server upload response: $_"
            }
        } else {
            Write-Warning "curl execution failed with exit code $LASTEXITCODE"
        }

        if (-not $success) {
            if ($attempt -lt $maxRetries) {
                $delay = 300
                Write-Host "Waiting $delay ms before retrying..."
                Start-Sleep -Milliseconds $delay
            }
            $attempt++
        }
    }

    return $uploaded
}

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
        # Poll the server to check if a screenshot or swipe action is requested
        $response = Invoke-RestMethod -Uri "$server/capture/poll" -Method Get -TimeoutSec 3

        if ($null -eq $lastSeenActionSeq) {
            $lastSeenActionSeq = $response.action_seq
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Startup sync: Synchronized lastSeenActionSeq to $lastSeenActionSeq." -ForegroundColor Yellow
        }

        if ($response.action_requested -and $response.action_seq -ne $lastSeenActionSeq) {
            $action = $response.action_requested
            $actionSeq = $response.action_seq
            $coords = $response.swipe_coords

            # Execute swipe using coordinates from server (fallback to local defaults if not provided)
            # Coordinates are splatted (@coords) to pass each item as a separate process argument.
            # Retries every 5s if the ADB command fails.
            $swipeSuccess = $false
            while (-not $swipeSuccess) {
                if ($coords) {
                    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Action requested: $action [seq: $actionSeq] (Dynamic coords: $coords). Executing swipe..." -ForegroundColor Cyan
                    & $adbPath shell input swipe @coords
                } else {
                    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Action requested: $action [seq: $actionSeq] (Default coords). Executing swipe..." -ForegroundColor Cyan
                    switch ($action) {
                        "UP"    { & $adbPath shell input swipe @swipeUp }
                        "DOWN"  { & $adbPath shell input swipe @swipeDown }
                        "LEFT"  { & $adbPath shell input swipe @swipeLeft }
                        "RIGHT" { & $adbPath shell input swipe @swipeRight }
                    }
                }

                if ($LASTEXITCODE -eq 0) {
                    $swipeSuccess = $true
                } else {
                    Write-Warning "[$(Get-Date -Format 'HH:mm:ss')] Swipe command failed. Check ADB connection."
                    Write-Host "Waiting 5 seconds before retrying swipe..." -ForegroundColor Yellow
                    Start-Sleep -Seconds 5
                }
            }

            # Update lastSeenActionSeq only after successful swipe execution
            $lastSeenActionSeq = $actionSeq

            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Swipe completed. Waiting $postSwipeSleepMs ms..."
            Start-Sleep -Milliseconds $postSwipeSleepMs

            # Automatically take post-action screencap with retry on failure
            $screencapSuccess = $false
            while (-not $screencapSuccess) {
                Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Taking post-action screencap..."
                $cmd = "`"$adbPath`" exec-out screencap -p > `"$screenshotFile`""
                cmd /c $cmd

                if ($LASTEXITCODE -eq 0 -and (Test-Path $screenshotFile) -and (Get-Item $screenshotFile).Length -gt 0) {
                    $screencapSuccess = $true
                } else {
                    Write-Warning "[$(Get-Date -Format 'HH:mm:ss')] Post-action screencap failed. Check ADB connection."
                    Write-Host "Waiting 5 seconds before retrying post-action screencap..." -ForegroundColor Yellow
                    Start-Sleep -Seconds 5
                }
            }

            # Upload PNG with metadata parameters for tracking/debugging and handle retries/errors
            $uploadUrl = "$server/capture/upload?source=post_action&action=$action&action_seq=$actionSeq"
            $uploaded = Upload-Screenshot -filePath $screenshotFile -url $uploadUrl
        } elseif ($response.capture_requested) {
            $screencapSuccess = $false
            while (-not $screencapSuccess) {
                Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Capture requested! Taking adb screencap..."

                # Execute adb screencap and pipe raw output to latest.png using cmd /c
                # (cmd /c redirection preserves binary stream format, avoiding PowerShell character encoding corruption)
                $cmd = "`"$adbPath`" exec-out screencap -p > `"$screenshotFile`""
                cmd /c $cmd

                if ($LASTEXITCODE -eq 0 -and (Test-Path $screenshotFile) -and (Get-Item $screenshotFile).Length -gt 0) {
                    $screencapSuccess = $true
                } else {
                    Write-Warning "[$(Get-Date -Format 'HH:mm:ss')] adb command failed or latest.png was not created. Is your Android device connected via ADB?"
                    Write-Host "Waiting 5 seconds before retrying screencap..." -ForegroundColor Yellow
                    Start-Sleep -Seconds 5
                }
            }

            # Upload PNG using helper function with retry logic
            $uploadUrl = "$server/capture/upload?source=manual"
            $uploaded = Upload-Screenshot -filePath $screenshotFile -url $uploadUrl
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
