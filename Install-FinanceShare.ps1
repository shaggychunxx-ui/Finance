#Requires -Version 5.1
<#
.SYNOPSIS
  Create the Finance dual-PC SMB share on AI-CODING (broker host).

.DESCRIPTION
  Share path: C:\Users\Public\FinanceShare
  UNC:       \\10.10.10.1\FinanceShare  (or \\<this-pc>\FinanceShare)

  Layout:
    pipeline\  — BOXONE writes agent research
    broker\    — AI-CODING writes live quotes + account snapshot

  Run elevated once on AI-CODING. BOXONE only needs read/write access to the share.
#>
param(
    [string]$ShareName = "FinanceShare",
    [string]$LocalPath = "C:\Users\Public\FinanceShare",
    [string]$Description = "Finance dual-PC pipeline/broker data"
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdmin)) {
    Write-Host "Re-launching elevated..."
    $arg = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Start-Process powershell.exe -Verb RunAs -ArgumentList $arg | Out-Null
    exit 0
}

New-Item -ItemType Directory -Force -Path $LocalPath | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $LocalPath "pipeline") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $LocalPath "broker") | Out-Null

$readme = Join-Path $LocalPath "README_FINANCE_SHARE.txt"
@"
Finance dual-PC share
  pipeline\  — written by BOXONE (agent research)
  broker\    — written by AI-CODING (quotes, account snapshot)
Do not put etrade tokens or consumer secrets here.
"@ | Set-Content -Path $readme -Encoding UTF8

$existing = Get-SmbShare -Name $ShareName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Share $ShareName already exists at $($existing.Path)"
    if ($existing.Path -ne $LocalPath) {
        Write-Warning "Existing share path differs from $LocalPath — leaving as-is."
    }
} else {
    New-SmbShare -Name $ShareName -Path $LocalPath -Description $Description -FullAccess "Everyone" | Out-Null
    Write-Host "Created share $ShareName -> $LocalPath"
}

# Firewall: allow File and Printer Sharing on private/domain profiles if needed
try {
    Enable-NetFirewallRule -DisplayGroup "File and Printer Sharing" -ErrorAction SilentlyContinue
} catch {}

$hostname = $env:COMPUTERNAME
Write-Host ""
Write-Host "Done. Use one of:"
Write-Host "  \\$hostname\$ShareName"
Write-Host "  \\10.10.10.1\$ShareName   (preferred on team Ethernet)"
Write-Host ""
Write-Host "On AI-CODING Finance folder, set deployment.json role=broker"
Write-Host "On BOXONE Finance folder, set deployment.json role=pipeline"
Write-Host "shared_root = \\10.10.10.1\$ShareName"
