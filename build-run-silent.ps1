# Build run-silent.exe into .local/ (gitignored) for no-flash scheduled tasks.
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
$src = Join-Path $repo "run-silent.cs"
$outDir = Join-Path $repo ".local"
$out = Join-Path $outDir "run-silent.exe"

if (-not (Test-Path $src)) { throw "Missing run-silent.cs" }
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }

$csc = Get-ChildItem "$env:WINDIR\Microsoft.NET\Framework64\v4*\csc.exe" -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
if (-not $csc) {
    $csc = Get-ChildItem "$env:WINDIR\Microsoft.NET\Framework\v4*\csc.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $csc) { throw "csc.exe not found (need .NET Framework 4.x)" }

# winexe = Windows subsystem — launcher itself never opens a console (critical on Win11 + WT)
& $csc /nologo /t:winexe /out:"$out" /optimize+ "$src"
if (-not (Test-Path $out)) { throw "Build failed: $out missing" }
Write-Host "Built: $out"
