# capture_agent.ps1
# Windows PowerShell Agent for Solver 2048d Client-Server capture system
# Requirements: adb.exe (with phone connected in debugging mode)

$server = "http://localhost:5000"   # Configure with your Ubuntu server IP/port
$pollIntervalMs = 500              # Poll server status every 500ms
$errorRateLimitSeconds = 15        # Limit connection error prints to once every 15s

$lastErrorTime = [DateTime]::MinValue

Write-Host "=== Windows Capture Agent Running ==="
Write-Host "Target Server: $server"
Write-Host "Polling every $pollIntervalMs ms. Press Ctrl+C to stop."
Write-Host "======================================"

while ($true) {
    try {
        # Poll the server to check if a screenshot is requested
        $response = Invoke-RestMethod -Uri "$server/capture/poll" -Method Get -TimeoutSec 3
        
        if ($response.capture_requested) {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Capture requested! Taking adb screencap..."
            
            # Execute adb screencap and pipe raw output to latest.png
            adb exec-out screencap -p > latest.png
            
            if ($LASTEXITCODE -eq 0 -and (Test-Path latest.png)) {
                Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Uploading latest.png to server..."
                
                # Upload PNG using curl.exe
                curl.exe -s -F "file=@latest.png" "$server/capture/upload"
                Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Screenshot uploaded successfully."
            } else {
                Write-Warning "adb command failed or latest.png was not created. Is your Android device connected via ADB?"
            }
        }
    } catch {
        # Rate-limit connection/server unavailable warnings to avoid spam
        $now = [DateTime]::Now
        if (($now - $lastErrorTime).TotalSeconds -ge $errorRateLimitSeconds) {
            Write-Warning "[$(Get-Date -Format 'HH:mm:ss')] Server is unavailable at $server. Retrying..."
            $lastErrorTime = $now
        }
    }
    
    Start-Sleep -Milliseconds $pollIntervalMs
}
