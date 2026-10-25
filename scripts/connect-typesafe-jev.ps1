# Interactive direct-TypeSafe Jev smoke test on Windows PowerShell / PowerShell 7.
# Prompts for the credential securely, never writes it to disk, and removes
# the environment variable after testing. No other configuration is changed.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$secure = Read-Host "TypeSafe API key (hidden input)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $env:TYPESAFE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

try {
    if (-not $env:TYPESAFE_API_KEY) { throw "No API key provided" }
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "Python 3.11+ not found on PATH"
    }
    $result = Join-Path (Get-Location) "results/typesafe_jev_smoke.json"
    Write-Host "Making exactly one requested Jev selection in a trusted synthetic example."
    python -m tomolab demo --case two_paths --mode cross --budget 1 --jev --jev-provider typesafe --output $result
    if ($LASTEXITCODE -ne 0) { throw "Demo process failed" }
    $data = Get-Content -Raw -Encoding UTF8 $result | ConvertFrom-Json
    Write-Host "decision_provider: $($data.decision_provider)"
    Write-Host "decision_calls: $($data.decision_calls)"
    Write-Host "decision_live_calls: $($data.decision_live_calls)"
    Write-Host "decision_fallbacks: $($data.decision_fallbacks)"
    if ($data.decision_provider -ne "jev_live_typesafe" -or $data.decision_fallbacks -gt 0) {
        throw "Jev DID NOT authenticate successfully; deterministic fallback was used. Review credit balance/key and connectivity."
    }
    Write-Host "DIRECT TYPESAFE JEV CONNECTION: SUCCESS" -ForegroundColor Green
    Write-Host "This proves only API connectivity, NOT predictive or verification quality."
} finally {
    Remove-Item Env:TYPESAFE_API_KEY -ErrorAction SilentlyContinue
    Remove-Variable secure -ErrorAction SilentlyContinue
}
