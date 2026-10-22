#Requires -Version 5.1
<#
    Daily sync: pull before work, commit + push after work.
    The script is intentionally ASCII-only: no BOM / code-page issues on any Windows machine.

    Usage:
        powershell -ExecutionPolicy Bypass -File .\scripts\sync.ps1 -PullOnly
        powershell -ExecutionPolicy Bypass -File .\scripts\sync.ps1 -Message "feat: perception api"
#>
param(
    [switch]$PullOnly,
    [string]$Message = "",
    [string]$Remote = "origin",
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

# ---------- locate git (PATH on Windows is frequently wrong; probe common install dirs) ----------
$gitExe = $null
$found = Get-Command git -ErrorAction SilentlyContinue
if ($found) { $gitExe = $found.Source }
if (-not $gitExe) {
    $candidates = @("D:\claudecode\Git\cmd\git.exe")
    if ($env:ProgramFiles)        { $candidates += (Join-Path $env:ProgramFiles "Git\cmd\git.exe") }
    if (${env:ProgramFiles(x86)}) { $candidates += (Join-Path ${env:ProgramFiles(x86)} "Git\cmd\git.exe") }
    if ($env:LOCALAPPDATA)        { $candidates += (Join-Path $env:LOCALAPPDATA "Programs\Git\cmd\git.exe") }
    foreach ($c in $candidates) { if (Test-Path $c) { $gitExe = $c; break } }
}
if (-not $gitExe) {
    Write-Host "[FAIL] git.exe not found. Install: https://git-scm.com/download/win" -ForegroundColor Red
    exit 1
}
function git { & $gitExe @args }

$inside = git rev-parse --is-inside-work-tree 2>$null
if ($inside -ne "true") {
    Write-Host "[FAIL] not a git repository. Run scripts\init-repo.ps1 first." -ForegroundColor Red
    exit 1
}

# ---------- pull ----------
Write-Host "[1/3] pulling $Remote/$Branch ..." -ForegroundColor Cyan
git pull --rebase --autostash $Remote $Branch
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] pull hit a conflict. Resolve it inside YOUR OWN module, then:" -ForegroundColor Red
    Write-Host "       git add -A ; git rebase --continue"
    Write-Host "       If it touches someone else's files: stop and ask them. Never guess." -ForegroundColor Yellow
    exit 1
}

if ($PullOnly -and -not $Message) {
    git status --short
    Write-Host "[OK] up to date. Read the team task board in docs/ before starting." -ForegroundColor Green
    exit 0
}

# ---------- commit ----------
Write-Host "[2/3] committing ..." -ForegroundColor Cyan
git add -A
$staged = git diff --cached --name-only
if (-not $staged) {
    Write-Host "[INFO] no changes to commit." -ForegroundColor Yellow
    exit 0
}

if (-not $Message) {
    try { $Message = Read-Host "Commit message (feat|fix|docs|refactor|exp|chore: what you did)" } catch {}
}
if (-not $Message) { $Message = "chore: sync progress" }

git commit -m $Message
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] commit failed. Set your identity once:" -ForegroundColor Red
    Write-Host '       git config --global user.name "Your Name"'
    Write-Host '       git config --global user.email "you@example.com"'
    exit 1
}

# ---------- push ----------
Write-Host "[3/3] pushing ..." -ForegroundColor Cyan
git push $Remote $Branch
if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARN] push failed. Someone pushed first - run this script again to rebase." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "[OK] pushed. Remember to update the team task board in docs/ (status + next step)!" -ForegroundColor Green
