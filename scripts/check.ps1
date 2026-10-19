# Runs everything that must pass before a change counts as done:
# the backend tests, then the dashboard build.
# Usage (from the project folder):  .\scripts\check.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "== Backend tests"
Push-Location (Join-Path $root "backend")
try {
    $venvPython = Join-Path (Get-Location) ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) { $py = $venvPython } else { $py = "python" }
    & $py -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Backend tests failed." }
}
finally { Pop-Location }

Write-Host "== Dashboard build"
Push-Location (Join-Path $root "dashboard")
try {
    if (-not (Test-Path "node_modules")) {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw "npm ci failed." }
    }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Dashboard build failed." }
}
finally { Pop-Location }

Write-Host "All checks passed."
