# Launch Unified E*TRADE Trader with base pythonw + venv site-packages.
# Avoids .venv\Scripts\pythonw.exe re-exec stubs that leave two processes and flash windows.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root '.venv'
$Gui = Join-Path $Root 'unified_trader_gui.py'
$PyVenv = Join-Path $Venv 'Scripts\python.exe'
$PywVenv = Join-Path $Venv 'Scripts\pythonw.exe'

if (-not (Test-Path $PyVenv)) {
    Write-Host 'Setting up environment...'
    python -m venv $Venv
    & $PyVenv -m pip install -r (Join-Path $Root 'requirements.txt')
}

# Resolve base interpreter from pyvenv.cfg home=
$basePyw = $null
$cfg = Join-Path $Venv 'pyvenv.cfg'
if (Test-Path $cfg) {
    foreach ($line in Get-Content $cfg) {
        if ($line -match '^\s*home\s*=\s*(.+)$') {
            $homeDir = $Matches[1].Trim()
            $candidate = Join-Path $homeDir 'pythonw.exe'
            if (Test-Path $candidate) {
                $basePyw = $candidate
                break
            }
        }
    }
}

$pythonw = if ($basePyw) { $basePyw } elseif (Test-Path $PywVenv) { $PywVenv } else { $PyVenv }

$env:VIRTUAL_ENV = $Venv
$env:PYTHONPATH = "$Root;$Venv\Lib\site-packages"
$env:PATH = "$Venv\Scripts;" + $env:PATH
$env:PYTHONUNBUFFERED = '1'

# Quote script path — paths with spaces (e.g. "Box One") break without this.
Start-Process -FilePath $pythonw -ArgumentList "`"$Gui`"" -WorkingDirectory $Root
exit 0
