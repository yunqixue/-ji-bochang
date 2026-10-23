# Start the demo: local server + temporary public tunnel.   Owner: C
#
# Usage: double-click start-demo.cmd in the repo root.
# It prints a https://xxx.trycloudflare.com link (also copied to the clipboard).
# Keep the window open while demoing; press Enter to stop everything.
#
# Notes:
#   - cloudflared is downloaded to %TEMP%\dsh-tunnel on first run (~50 MB).
#   - The link is temporary: it dies when this window closes, and a new random
#     hostname is issued every time you run this script. Never write it into docs.
#   - Anyone with the link can open the chat page. Stop the script after the demo.

$ErrorActionPreference = 'Stop'
$root  = Split-Path -Parent $PSScriptRoot
$tools = Join-Path $env:TEMP 'dsh-tunnel'
New-Item -ItemType Directory -Force -Path $tools | Out-Null
$exe   = Join-Path $tools 'cloudflared.exe'
$port  = 8000

function Stop-WithMessage([string]$message) {
    Write-Host ''
    Write-Host $message -ForegroundColor Yellow
    Read-Host 'Press Enter to close'
    exit 1
}

if (-not (Test-Path $exe)) {
    Write-Host 'Downloading cloudflared (first run only) ...'
    try {
        Invoke-WebRequest 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile $exe -TimeoutSec 300
    } catch {
        Stop-WithMessage 'Download failed. Check the network and run again.'
    }
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Stop-WithMessage 'python not found in PATH.'
}

$server = $null
$inUse = (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count

if ($inUse -eq 0) {
    Write-Host "Starting server on http://127.0.0.1:$port ..."
    $server = Start-Process -FilePath 'python' `
        -ArgumentList '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', "$port" `
        -WorkingDirectory $root -PassThru -WindowStyle Hidden

    $healthy = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 900
        try {
            Invoke-WebRequest "http://127.0.0.1:$port/api/health" -UseBasicParsing -TimeoutSec 3 | Out-Null
            $healthy = $true
            break
        } catch { }
    }
    if (-not $healthy) {
        if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
        Stop-WithMessage "Server did not start. Try manually: python -m uvicorn app:app --host 127.0.0.1 --port $port"
    }
    Write-Host "Server up (pid $($server.Id))."
} else {
    Write-Host "Port $port already in use - reusing the server that is already running."
}

$errLog = Join-Path $tools 'demo.err.log'
$outLog = Join-Path $tools 'demo.out.log'
Remove-Item $errLog, $outLog -ErrorAction SilentlyContinue

Write-Host 'Opening tunnel (can take 10-60s) ...'
$tunnel = Start-Process -FilePath $exe `
    -ArgumentList 'tunnel', '--url', "http://127.0.0.1:$port", '--no-autoupdate' `
    -PassThru -WindowStyle Hidden -RedirectStandardError $errLog -RedirectStandardOutput $outLog

$url = $null
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2
    $text = ((Get-Content $errLog -Raw -ErrorAction SilentlyContinue) + (Get-Content $outLog -Raw -ErrorAction SilentlyContinue))
    $match = [regex]::Match($text, 'https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com')
    if ($match.Success) { $url = $match.Value; break }
}

if (-not $url) {
    if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force }
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
    Get-Content $errLog -Tail 10 -ErrorAction SilentlyContinue
    Stop-WithMessage 'Tunnel did not come up (trycloudflare may be blocked). Run again, or demo on localhost.'
}

Set-Content -Path (Join-Path $tools 'url.txt') -Value $url -Encoding utf8
try { Set-Clipboard -Value $url } catch { }

Write-Host ''
Write-Host '=====================================================' -ForegroundColor Green
Write-Host '  PUBLIC LINK (also copied to clipboard):' -ForegroundColor Green
Write-Host "  $url" -ForegroundColor Cyan
Write-Host '=====================================================' -ForegroundColor Green
Write-Host ''
Write-Host 'Keep this window open during the demo.'
Write-Host 'Press Enter to stop the server and the tunnel.'
Read-Host | Out-Null

if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue }
if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }
Write-Host 'Stopped.'
