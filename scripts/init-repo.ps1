#Requires -Version 5.1
<#
    One-time repository initialization. Run ONCE by the team lead.
    The script is intentionally ASCII-only: no BOM / code-page issues on any Windows machine.

    Usage (interactive):
        powershell -ExecutionPolicy Bypass -File .\scripts\init-repo.ps1

    Usage (no prompts):
        powershell -ExecutionPolicy Bypass -File .\scripts\init-repo.ps1 `
            -UserName "Zhang San" -UserEmail "zs@example.com" `
            -RemoteUrl https://gitee.com/you/team-agent.git
#>
param(
    [string]$RemoteUrl = "",
    [string]$UserName = "",
    [string]$UserEmail = "",
    [switch]$SetGlobalIdentity,
    [switch]$NonInteractive
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
    Write-Host "[FAIL] git.exe not found." -ForegroundColor Red
    Write-Host "       Install: https://git-scm.com/download/win  (or: winget install --id Git.Git -e)"
    Write-Host "       Then CLOSE this terminal and open a new one."
    exit 1
}
function git { & $gitExe @args }
Write-Host "[OK] using git: $gitExe  ($(git --version))" -ForegroundColor DarkGray

# ---------- git identity (a commit cannot be created without it) ----------
$curName  = (git config --global user.name)  2>$null
$curEmail = (git config --global user.email) 2>$null

if (-not $NonInteractive) {
    if (-not $UserName  -and -not $curName)  { try { $UserName  = Read-Host "Your name for commits (e.g. Zhang San)" } catch {} }
    if (-not $UserEmail -and -not $curEmail) { try { $UserEmail = Read-Host "Your email for commits" } catch {} }
}

$haveIdentity = $false
if ($UserName -and $UserEmail) {
    if ($SetGlobalIdentity) {
        git config --global user.name  $UserName
        git config --global user.email $UserEmail
        Write-Host "[OK] global git identity set: $UserName <$UserEmail>" -ForegroundColor Green
        $haveIdentity = $true
    } else {
        Write-Host "[INFO] identity will be stored repo-local (this project only)." -ForegroundColor DarkGray
    }
} elseif ($curName -and $curEmail) {
    $haveIdentity = $true
} else {
    Write-Host "[WARN] no git identity - the first commit will fail." -ForegroundColor Yellow
    Write-Host '       Fix:  git config --global user.name "Your Name"'
    Write-Host '             git config --global user.email "you@example.com"'
    Write-Host "       Or rerun with: -UserName ... -UserEmail ... -SetGlobalIdentity"
}

# ---------- init ----------
if (Test-Path .git) {
    Write-Host "[SKIP] .git already exists - already a repository." -ForegroundColor Yellow
} else {
    git init -b main
    if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] git init failed" -ForegroundColor Red; exit 1 }
    Write-Host "[OK] repository initialized on branch main" -ForegroundColor Green
}

if ($UserName -and $UserEmail -and -not $SetGlobalIdentity) {
    git config user.name  $UserName
    git config user.email $UserEmail
    $haveIdentity = $true
}

# ---------- first commit ----------
git add -A
$staged = git diff --cached --name-only
if (-not $staged) {
    Write-Host "[INFO] nothing to commit (already committed)." -ForegroundColor Yellow
} else {
    git commit -m "chore: initialize team collaboration scaffold (AGENTS.md, task board, API contract, ADR)"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] commit failed - check the identity warning above." -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] first commit created" -ForegroundColor Green
}

# ---------- remote ----------
if (-not $RemoteUrl -and -not $NonInteractive) {
    try { $RemoteUrl = Read-Host "Private repo URL (leave empty to skip)" } catch {}
}

if ($RemoteUrl) {
    $existing = @(git remote 2>$null)
    if ($existing -contains "origin") { git remote set-url origin $RemoteUrl }
    else { git remote add origin $RemoteUrl }
    git push -u origin main
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARN] push failed. Check the URL and credentials (use an access TOKEN as the password)." -ForegroundColor Yellow
    } else {
        Write-Host "[OK] pushed to origin/main" -ForegroundColor Green
    }
} else {
    Write-Host "[INFO] no remote yet. Add it later, then push:" -ForegroundColor Yellow
    Write-Host "       git remote add origin <url>"
    Write-Host "       git push -u origin main"
}

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Create a PRIVATE repo (Gitee / GitHub) and invite the other two as Developer."
Write-Host "  2. Send them: docs\ (the onboarding checklist is the one with 3 people in its name)."
Write-Host "  3. Fill in AGENTS.md sections 1 and 2 (project goal + real names)."
Write-Host "  4. Fix the broken PATH entry so plain 'git' works everywhere (see docs)."
