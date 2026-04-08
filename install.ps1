# stealth-message installer for Windows (PowerShell)
# Usage: powershell -c "irm https://syberiancode.com/stealth-message/install.ps1 | iex"
$ErrorActionPreference = "Stop"

$Package = "stealth-message-cli"
$Binary  = "stealth-cli"

function Write-Info    { param($msg) Write-Host "[stealth-message] $msg" -ForegroundColor Green }
function Write-Warning { param($msg) Write-Host "[stealth-message] $msg" -ForegroundColor Yellow }
function Write-Err     { param($msg) Write-Host "[stealth-message] Error: $msg" -ForegroundColor Red; exit 1 }

# ── Find Python 3.10+ ─────────────────────────────────────────────────────────
function Find-Python {
    $candidates = @("python3.13", "python3.12", "python3.11", "python3.10", "python3", "python")
    foreach ($cmd in $candidates) {
        try {
            $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($ver -match "^3\.(\d+)$") {
                $minor = [int]$Matches[1]
                if ($minor -ge 10) { return $cmd }
            }
        } catch {}
    }
    return $null
}

# ── Main ──────────────────────────────────────────────────────────────────────
Write-Info "Installing $Package..."

$Python = Find-Python
if (-not $Python) {
    Write-Err "Python 3.10 or newer is required.`nDownload it from https://python.org"
}

$pyVer = & $Python --version
Write-Info "Using $Python ($pyVer)"

# pipx — preferred
$usePipx = $false
try {
    $null = Get-Command pipx -ErrorAction Stop
    $usePipx = $true
} catch {}

if ($usePipx) {
    Write-Info "Installing via pipx..."
    & pipx install --python $Python $Package
} else {
    Write-Warning "pipx not found — falling back to pip install --user"
    Write-Warning "Consider installing pipx: https://pipx.pypa.io"
    & $Python -m pip install --user --upgrade $Package

    # Add user Scripts dir to current session PATH
    $userScripts = [System.IO.Path]::Combine($env:APPDATA, "Python", "Scripts")
    if (Test-Path $userScripts) {
        $env:PATH = "$userScripts;$env:PATH"
        Write-Warning "Add this to your PATH permanently: $userScripts"
    }
}

Write-Host ""
Write-Info "$Binary installed successfully!"
Write-Info "Run: $Binary --help"
