# Download cloudflared for remote phone access (works across networks).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$tools = Join-Path $root "tools"
$exe = Join-Path $tools "cloudflared.exe"
$url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"

New-Item -ItemType Directory -Force -Path $tools | Out-Null
if (-not (Test-Path $exe)) {
    Write-Host "Downloading cloudflared..."
    Invoke-WebRequest -Uri $url -OutFile $exe -UseBasicParsing
}
if (-not (Test-Path $exe)) {
    Write-Error "cloudflared download failed."
}
Write-Host "cloudflared ready: $exe"