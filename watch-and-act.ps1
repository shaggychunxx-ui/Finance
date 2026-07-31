# watch-and-act.ps1
# Pull shared repo; if there is assigned work, run headless Grok.
# Designed for Task Scheduler (FinanceWorkspaceWatch).

$ErrorActionPreference = "Continue"
$repo = $PSScriptRoot
Set-Location $repo

$grok = Join-Path $env:USERPROFILE ".grok\bin\grok.exe"
$localDir = Join-Path $repo ".local"
$logPath = Join-Path $localDir "watch.log"
$statePath = Join-Path $localDir "last-acted-sha.txt"
$lockPath = Join-Path $localDir "act.lock"
$machine = $env:COMPUTERNAME

if (-not (Test-Path $localDir)) { New-Item -ItemType Directory -Path $localDir -Force | Out-Null }

function Resolve-GitExe {
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    $candidates = @(
        "C:\Program Files\Git\cmd\git.exe",
        "C:\Program Files\Git\bin\git.exe",
        "C:\Program Files (x86)\Git\cmd\git.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Git\cmd\git.exe")
    )
    $desktopRoot = Join-Path $env:LOCALAPPDATA "GitHubDesktop"
    if (Test-Path $desktopRoot) {
        Get-ChildItem $desktopRoot -Directory -Filter "app-*" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object {
                $candidates += (Join-Path $_.FullName "resources\app\git\cmd\git.exe")
                $candidates += (Join-Path $_.FullName "resources\app\git\mingw64\bin\git.exe")
            }
    }
    foreach ($p in $candidates) {
        if ($p -and (Test-Path $p)) { return $p }
    }
    return $null
}

$script:GitExe = Resolve-GitExe

function Write-Log([string]$msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] [$machine] $msg"
    Write-Host $line
    Add-Content -Path $logPath -Value $line -ErrorAction SilentlyContinue
}

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
    if (-not $script:GitExe) {
        return @{ Code = 127; Text = "git not found (install Git for Windows or GitHub Desktop)" }
    }
    $output = & $script:GitExe @GitArgs 2>&1 | ForEach-Object { "$_" }
    return @{
        Code = $LASTEXITCODE
        Text = ($output -join " | ")
    }
}

function Test-LockStale {
    if (-not (Test-Path $lockPath)) { return $true }
    $age = (Get-Date) - (Get-Item $lockPath).LastWriteTime
    if ($age.TotalHours -gt 2) {
        Write-Log "Removing stale lock (older than 2 hours)"
        Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
        return $true
    }
    return $false
}

function Get-StatusActOn {
    $statusFile = Join-Path $repo "STATUS.md"
    if (-not (Test-Path $statusFile)) { return "none" }
    $lines = Get-Content $statusFile -ErrorAction SilentlyContinue
    foreach ($line in $lines) {
        if ($line -match '(?i)\*\*Act on:\*\*\s*(.+?)\s*$') {
            return $Matches[1].Trim()
        }
        if ($line -match '(?i)^Act on:\s*(.+?)\s*$') {
            return $Matches[1].Trim()
        }
    }
    return "none"
}

function Get-PendingTaskTargets {
    $pending = Join-Path $repo "tasks\pending"
    $targets = @()
    if (-not (Test-Path $pending)) { return $targets }
    Get-ChildItem $pending -Filter "*.md" -File -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Name -eq "_TEMPLATE.md") { return }
        $content = Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue
        if ($content -match '(?im)^\s*target:\s*(.+?)\s*$') {
            $targets += $Matches[1].Trim()
        } else {
            $targets += "ALL"
        }
    }
    return $targets
}

function Test-TargetMatches([string]$target) {
    if ([string]::IsNullOrWhiteSpace($target)) { return $false }
    $t = $target.Trim()
    if ($t -eq "none" -or $t -eq "None" -or $t -eq "NONE") { return $false }
    if ($t -eq "ALL" -or $t -eq "all" -or $t -eq "either" -or $t -eq "EITHER") { return $true }
    if ($t -ieq $machine) { return $true }
    return $false
}

function Test-ShouldAct {
    $actOn = Get-StatusActOn
    if (Test-TargetMatches $actOn) {
        Write-Log "STATUS Act on matches: $actOn"
        return $true
    }
    $targets = Get-PendingTaskTargets
    foreach ($t in $targets) {
        if (Test-TargetMatches $t) {
            Write-Log "Pending task target matches: $t"
            return $true
        }
    }
    $inbox = Join-Path $repo "inbox"
    if (Test-Path $inbox) {
        $files = Get-ChildItem $inbox -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne ".gitkeep" }
        if ($files) {
            Write-Log "Inbox has files; will act"
            return $true
        }
    }
    return $false
}

function Invoke-Sync {
    $branch = "main"
    $remote = "origin"
    Write-Log "Sync remote: $remote"

    $status = Invoke-Git status --porcelain
    $dirty = [string]$status.Text
    $stashed = $false
    if ($dirty.Trim().Length -gt 0) {
        $null = Invoke-Git stash push -u -m "watch stash"
        $stashed = $true
    }

    $fetch = Invoke-Git fetch $remote
    if ($fetch.Code -ne 0) {
        Write-Log ("Fetch issue ($remote): " + $fetch.Text)
    }

    $pull = Invoke-Git pull --rebase $remote $branch
    if ($pull.Code -ne 0) {
        Write-Log ("Pull issue ($remote): " + $pull.Text)
    }
    if ($stashed) {
        $null = Invoke-Git stash pop
    }

    $after = Invoke-Git status --porcelain
    $text = [string]$after.Text
    if ($text.Trim().Length -gt 0) {
        $null = Invoke-Git add -A
        $null = Invoke-Git reset HEAD -- .local 2>$null
        $msg = "auto-sync: " + (Get-Date -Format "yyyy-MM-dd HH:mm") + " from " + $machine
        $c = Invoke-Git commit -m $msg
        if ($c.Code -eq 0) {
            Write-Log "Committed local changes"
        }
    }
    $ahead = Invoke-Git rev-list --count "${remote}/${branch}..HEAD"
    $n = 0
    if ($ahead.Code -eq 0 -and ([string]$ahead.Text).Trim() -match '^\d+$') {
        $n = [int]([string]$ahead.Text).Trim()
    } elseif ($ahead.Code -ne 0) {
        $lr = Invoke-Git rev-parse "$remote/$branch"
        if ($lr.Code -ne 0) { $n = 1 }
    }
    if ($n -gt 0) {
        $push = Invoke-Git push $remote $branch
        Write-Log ("Push ($remote): " + $push.Text)
    }
}

function Get-HeadSha {
    $r = Invoke-Git rev-parse HEAD
    if ($r.Code -eq 0) { return ([string]$r.Text).Trim() }
    return ""
}

function Get-NewCommitSummary([string]$oldSha, [string]$newSha) {
    if ([string]::IsNullOrWhiteSpace($oldSha)) {
        $r = Invoke-Git log -5 --oneline
        return $r.Text
    }
    $r = Invoke-Git log --oneline "$oldSha..$newSha"
    return $r.Text
}

function Test-OnlySelfAutoSync([string]$oldSha, [string]$newSha) {
    if ([string]::IsNullOrWhiteSpace($oldSha)) { return $false }
    $r = Invoke-Git log --format="%s" "$oldSha..$newSha"
    $msgs = ([string]$r.Text) -split '\s*\|\s*'
    $any = $false
    foreach ($m in $msgs) {
        $m = $m.Trim()
        if ($m.Length -eq 0) { continue }
        $any = $true
        if ($m -notmatch [regex]::Escape("from $machine")) {
            return $false
        }
        if ($m -notmatch '^auto-sync:') {
            return $false
        }
    }
    return $any
}

function Invoke-GrokAct([string]$reason, [string]$commitSummary) {
    if (-not (Test-Path $grok)) {
        Write-Log "Grok not found at $grok - cannot act"
        return $false
    }
    if (-not (Test-LockStale)) {
        Write-Log "Another act is in progress (lock present) - skip"
        return $false
    }

    $lockBody = @{
        machine = $machine
        started = (Get-Date).ToString("o")
        pid     = $PID
        reason  = $reason
    } | ConvertTo-Json
    Set-Content -Path $lockPath -Value $lockBody -Encoding UTF8

    $promptPath = Join-Path $localDir "prompt.txt"
    $prompt = @"
You are running unattended on machine $machine in the Finance repo.

Reason you were woken: $reason

Recent commits:
$commitSummary

Follow RULES.md and AGENTS.md strictly.

Team:
- AI-CODING = MAIN computer (plans; decides what to send to BOXONE unless human asked).
- BOXONE = HELPER (executes assigned work only; no inventing work for main).
- PHONE-OXYGEN / OXYGEN-PHONE = human mobile only (never Act on phone).

Rules:
1) Read RULES.md, STATUS.md, tasks/pending/.
2) Only act if assigned to this machine ($machine). Ignore ALL/either on BOXONE.
3) Do the work; on complete: tasks/done + NOTIFY line + Act on: the OTHER machine (always notify).
4) If woken only for a peer NOTIFY: ack once, set Act on: none, do NOT notify back.
5) If nothing to do: EXIT without editing STATUS (no heartbeat notes).
6) Need help/info: one Blockers or kind:help; bump handoff_count.
7) Anti-thrash: no work ping-pong; handoff_count < max_handoffs (default 2); one NOTIFY per completion only.
8) BOXONE must not invent chores for AI-CODING; help only when blocked.
9) No secrets in git.
"@
    Set-Content -Path $promptPath -Value $prompt -Encoding UTF8

    $runLog = Join-Path $localDir ("act-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")
    Write-Log "Starting headless Grok (log: $runLog) [no-window]"

    $argList = @(
        "--prompt-file", $promptPath,
        "--cwd", $repo,
        "--always-approve",
        "--no-auto-update",
        "--max-turns", "40",
        "--output-format", "plain",
        "--rules", "Stay inside this repo. Do not disable watchers. No secrets in commits."
    )

    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $grok
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.RedirectStandardInput = $true
        $psi.WorkingDirectory = $repo
        $quoted = foreach ($a in $argList) {
            if ($a -match '[\s"]') { '"' + ($a -replace '"', '\"') + '"' } else { $a }
        }
        $psi.Arguments = [string]::Join(" ", $quoted)

        $p = New-Object System.Diagnostics.Process
        $p.StartInfo = $psi
        $null = $p.Start()
        $stdout = $p.StandardOutput.ReadToEnd()
        $stderr = $p.StandardError.ReadToEnd()
        $p.WaitForExit()
        $code = $p.ExitCode
        $combined = @($stdout, $stderr) -join "`n"
        if ($combined.Trim().Length -gt 0) {
            Set-Content -Path $runLog -Value $combined -Encoding UTF8
        } else {
            Set-Content -Path $runLog -Value "(no output, exit $code)" -Encoding UTF8
        }
        Write-Log ("Grok exit code: " + $code)
        return ($code -eq 0)
    }
    catch {
        Write-Log ("Grok failed: " + $_.Exception.Message)
        return $false
    }
    finally {
        Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
    }
}

# ---- main ----
# PHONE 2026-07-29: check for tasks every 30s. Outer scheduled task is still ~2â€“5m
# (Task Scheduler floor ~1m); inner loop covers the gap.
$pollSeconds = 30
if ($env:GROK_WATCH_POLL_SEC -match '^\d+$') {
    $pollSeconds = [Math]::Max(5, [int]$env:GROK_WATCH_POLL_SEC)
}
$windowSeconds = 110
if ($env:GROK_WATCH_WINDOW_SEC -match '^\d+$') {
    $windowSeconds = [Math]::Max($pollSeconds, [int]$env:GROK_WATCH_WINDOW_SEC)
}

$deadline = (Get-Date).AddSeconds($windowSeconds)
$poll = 0
$wake = $false
$reason = ""
$last = ""
if (Test-Path $statePath) {
    $last = (Get-Content $statePath -Raw -ErrorAction SilentlyContinue).Trim()
}
$head = ""

Write-Log "Watch window start (poll=${pollSeconds}s window=${windowSeconds}s)"

while ($true) {
    $poll++
    Write-Log "Watch poll $poll start"
    try {
        Invoke-Sync
    }
    catch {
        Write-Log ("Sync error: " + $_.Exception.Message)
    }

    $head = Get-HeadSha
    $newActivity = ($head -ne $last -and $head.Length -gt 0)
    $assigned = Test-ShouldAct

    if ($assigned) {
        $wake = $true
        $reason = "Work assigned to this machine (STATUS / tasks / inbox)"
        break
    }
    elseif ($newActivity) {
        $onlySelf = Test-OnlySelfAutoSync $last $head
        if ($onlySelf) {
            Write-Log "Only self auto-sync commits and no assignment - skip Grok"
        } else {
            Write-Log "Remote commits seen but no assignment to this machine - sync only (skip Grok)"
        }
        if ($head.Length -gt 0) {
            Set-Content -Path $statePath -Value $head -Encoding ASCII
            $last = $head
        }
    }
    else {
        Write-Log "No assignment this poll - idle"
        if ($head.Length -gt 0) {
            Set-Content -Path $statePath -Value $head -Encoding ASCII
            $last = $head
        }
    }

    if ((Get-Date) -ge $deadline) {
        Write-Log "Watch window complete (no act; polls=$poll)"
        exit 0
    }
    Start-Sleep -Seconds $pollSeconds
}

$summary = Get-NewCommitSummary $last $head
$ok = Invoke-GrokAct -reason $reason -commitSummary $summary

try {
    Invoke-Sync
}
catch {
    Write-Log ("Post-act sync error: " + $_.Exception.Message)
}

$head2 = Get-HeadSha
if ($head2.Length -gt 0) {
    Set-Content -Path $statePath -Value $head2 -Encoding ASCII
}

if ($ok) {
    Write-Log "Watch cycle complete (acted after poll $poll)"
    exit 0
} else {
    Write-Log "Watch cycle complete (act failed or skipped after poll $poll)"
    exit 1
}
