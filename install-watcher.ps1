# install-watcher.ps1
# Install background sync + headless Grok actor with NO console flash.
# Run ONCE on each PC after clone:
#   powershell -ExecutionPolicy Bypass -File .\install-watcher.ps1

param(
    [switch]$AtStartup,
    [switch]$AtLogon,
    [switch]$RunWhetherLoggedOn,
    [SecureString]$Password
)

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
$watchScript = Join-Path $repo "watch-and-act.ps1"
$vbs = Join-Path $repo "run-watch-hidden.vbs"
$taskName = "FinanceWorkspaceWatch"

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Path $watchScript)) {
    throw "Missing watch-and-act.ps1 in $repo"
}
if (-not (Test-Path $vbs)) {
    throw "Missing run-watch-hidden.vbs in $repo"
}

if (-not $PSBoundParameters.ContainsKey("AtStartup")) { $AtStartup = $true }
if (-not $PSBoundParameters.ContainsKey("AtLogon")) { $AtLogon = $true }

# Prefer sister elevated runner if present (optional)
if (($AtStartup -or $AtLogon -or $RunWhetherLoggedOn) -and -not (Test-IsAdmin) -and -not $env:FINANCE_WATCHER_ELEVATED) {
    $sisterElev = Join-Path $env:USERPROFILE "Documents\GitHub\grok-shared-workspace\work\elevated\Invoke-Elevated.ps1"
    if (Test-Path $sisterElev) {
        if ($RunWhetherLoggedOn) {
            throw "Run elevated manually for -RunWhetherLoggedOn (password-backed principal)."
        }
        Write-Host "Elevation needed for boot/logon task triggers - using sister elevated runner..."
        $arg = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -AtStartup -AtLogon"
        & $sisterElev -Command "`$env:FINANCE_WATCHER_ELEVATED='1'; powershell $arg"
        exit $LASTEXITCODE
    }
    Write-Host "WARNING: not admin and no elevated runner - installing Interactive interval-only if boot triggers fail."
}

$build = Join-Path $repo "build-run-silent.ps1"
if (Test-Path $build) {
    try {
        powershell -NoProfile -ExecutionPolicy Bypass -File $build
    } catch {
        Write-Host "WARNING: run-silent.exe build failed: $($_.Exception.Message)"
    }
}

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument "//B //Nologo `"$vbs`"" `
    -WorkingDirectory $repo

$triggers = @()

$interval = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 2) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$triggers += $interval

if ($AtStartup) {
    try {
        $boot = New-ScheduledTaskTrigger -AtStartup
        $boot.Delay = "PT2M"
        $triggers += $boot
    } catch {
        Write-Host "WARNING: AtStartup trigger skipped: $($_.Exception.Message)"
    }
}

if ($AtLogon) {
    try {
        $logon = New-ScheduledTaskTrigger -AtLogon -User $env:USERNAME
        $logon.Delay = "PT30S"
        $triggers += $logon
    } catch {
        Write-Host "WARNING: AtLogon trigger skipped: $($_.Exception.Message)"
    }
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -Hidden `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$userId = $env:USERNAME
if ($env:USERDOMAIN -and $env:USERDOMAIN -ne $env:COMPUTERNAME) {
    $userId = "$env:USERDOMAIN\$env:USERNAME"
} else {
    $userId = "$env:COMPUTERNAME\$env:USERNAME"
}

function Get-PlainPassword([SecureString]$Secure) {
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

$description = "Sync Finance and run headless Grok (hidden). Boot + interval + logon."

if ($RunWhetherLoggedOn) {
    if (-not $Password) {
        $Password = Read-Host -AsSecureString -Prompt "Windows password for $userId (stored only in Task Scheduler)"
    }
    $plain = Get-PlainPassword $Password
    if ([string]::IsNullOrEmpty($plain)) {
        throw "Password required for -RunWhetherLoggedOn"
    }
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -User $userId `
        -Password $plain `
        -RunLevel Limited `
        -Description $description `
        -Force | Out-Null
    $plain = $null
    Write-Host "Principal: $userId (Password / run whether logged on or not)"
} else {
    $principal = New-ScheduledTaskPrincipal `
        -UserId $env:USERNAME `
        -LogonType Interactive `
        -RunLevel Limited
    try {
        Register-ScheduledTask `
            -TaskName $taskName `
            -Action $action `
            -Trigger $triggers `
            -Settings $settings `
            -Principal $principal `
            -Description $description `
            -Force | Out-Null
    } catch {
        # Fall back to interval-only without boot/logon if elevation missing
        Write-Host "Full triggers failed ($($_.Exception.Message)); retrying interval-only..."
        $intervalOnly = @(
            (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
                -RepetitionInterval (New-TimeSpan -Minutes 2) `
                -RepetitionDuration (New-TimeSpan -Days 3650))
        )
        Register-ScheduledTask `
            -TaskName $taskName `
            -Action $action `
            -Trigger $intervalOnly `
            -Settings $settings `
            -Principal $principal `
            -Description $description `
            -Force | Out-Null
    }
    Write-Host "Principal: $env:USERNAME (Interactive)"
}

$localDir = Join-Path $repo ".local"
if (-not (Test-Path $localDir)) { New-Item -ItemType Directory -Path $localDir -Force | Out-Null }
Set-Content -Path (Join-Path $localDir "machine-name.txt") -Value $env:COMPUTERNAME -Encoding ASCII

Write-Host "Installed hidden scheduled task: $taskName"
Write-Host "Launcher: wscript //B -> run-watch-hidden.vbs (no console flash)"
Write-Host "Computer name: $env:COMPUTERNAME"
Write-Host "Repo: $repo"
