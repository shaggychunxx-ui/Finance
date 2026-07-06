# Allow phone access to the mobile monitor (run once as Administrator).
$ErrorActionPreference = "Stop"

$rules = @(
    @{ Name = "ETrade Mobile Monitor HTTP"; Port = 8766 },
    @{ Name = "ETrade Mobile Monitor HTTPS"; Port = 8767 }
)

foreach ($rule in $rules) {
    $existing = Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "Already allowed: $($rule.Name) (port $($rule.Port))"
        continue
    }
    New-NetFirewallRule -DisplayName $rule.Name `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort $rule.Port `
        -Profile Any | Out-Null
    Write-Host "Allowed inbound TCP $($rule.Port) ($($rule.Name))"
}

Write-Host ""
Write-Host "Firewall updated. Phones on your Wi-Fi can reach the monitor."