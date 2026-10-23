#Requires -Version 5.1
<#
    Daily sync: pull before work, commit + push after work.
    Also used for the FIRST push after init-repo.ps1 (no new commit needed).
    The script is intentionally ASCII-only: no BOM / code-page issues on any Windows machine.

    Usage:
        powershell -ExecutionPolicy Bypass -File .\scripts\sync.ps1 -PullOnly
        powershell -ExecutionPolicy Bypass -File .\scripts\sync.ps1 -Message "feat: perception api"
        powershell -ExecutionPolicy Bypass -File .\scripts\sync.ps1 -PushOnly
        powershell -ExecutionPolicy Bypass -File .\scripts\sync.ps1 -Force     (OVERWRITE remote history - use once only)
#>
param(
    [switch]$PullOnly,
    [switch]$PushOnly,
    [switch]$Force,
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

$remotes = @(git remote 2>$null)
if (-not ($remotes -contains $Remote)) {
    Write-Host "[FAIL] remote '$Remote' not configured. Bind it first:" -ForegroundColor Red
    Write-Host "       git remote add origin <repo-url>"
    exit 1
}

    # ---------- pull ----------
# -Force overwrites remote history, so pulling first makes no sense and must be skipped.
if (-not $PushOnly -and -not $Force) {
    Write-Host "[1/3] pulling $Remote/$Branch (merge mode) ..." -ForegroundColor Cyan
    $headBefore = (git rev-parse HEAD)
    # 用 --no-rebase（merge）而不是 --rebase。
    # 原因：rebase 撞车后要继续 git rebase --continue、还可能弹编辑器，三个人都不是 git 老手，
    #       已经真实卡死过两次（卡在 rebase-merge 状态、pull 都启动不了）。
    #       merge 撞车后就是普通的 git add + git commit，简单得多。
    git pull --no-rebase --autostash $Remote $Branch
    if ($LASTEXITCODE -ne 0) {
        $unmerged = @(git diff --name-only --diff-filter=U 2>$null)
        if ($unmerged.Count -gt 0) {
            Write-Host "[CONFLICT] pull stopped: these files were changed by both sides -" -ForegroundColor Red
            $unmerged | ForEach-Object { Write-Host "           $_" -ForegroundColor Red }
            Write-Host "       How to fix (3 commands):" -ForegroundColor Yellow
            Write-Host "       1) open each file, delete the <<<<<<< / ======= / >>>>>>> lines, KEEP BOTH SIDES" -ForegroundColor Yellow
            Write-Host "       2) git add -A" -ForegroundColor Yellow
            Write-Host "       3) git commit -m \"merge: resolve conflicts\"" -ForegroundColor Yellow
            Write-Host "       To give up and return to the pre-pull state:  git merge --abort" -ForegroundColor Yellow
            exit 2
        }
        Write-Host "[FAIL] pull failed. If this is the very FIRST push, the remote repo is probably empty -" -ForegroundColor Red
        Write-Host "       that is expected: rerun with -PushOnly to publish your initial commit." -ForegroundColor Yellow
        Write-Host "       Otherwise see docs/疑难排查.md section 12." -ForegroundColor Yellow
        exit 1
    }
    # Show WHICH files teammates touched, so a surprise deletion is visible immediately.
    $headAfter = (git rev-parse HEAD)
    if ($headBefore -ne $headAfter) {
        Write-Host "[INFO] this pull changed these files (D=deleted, A=added, M=modified):" -ForegroundColor Yellow
        git diff --name-status $headBefore $headAfter
    } else {
        Write-Host "[INFO] nothing new from teammates." -ForegroundColor DarkGray
    }
}

if ($PullOnly -and -not $Message -and -not $PushOnly) {
    git status --short
    Write-Host "[OK] up to date. Read the team task board in docs/ before starting." -ForegroundColor Green
    exit 0
}

# ---------- commit ----------
Write-Host "[2/3] committing ..." -ForegroundColor Cyan
git add -A
$staged = git diff --cached --name-only
if (-not $staged) {
    Write-Host "[INFO] no local changes to commit." -ForegroundColor Yellow
} else {
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
}

# ---------- push ----------
# Capture push output first, then classify. The Chinese explanation lives in push.cmd
# (GBK encoded); this script stays ASCII-only so PowerShell 5.1 can always parse it.
# Past bug: push.cmd used findstr to look for "schannel"/"rejected" in the log, but our own
# hint text contained those words, so a simple "someone pushed first" got reported as
# "your TLS is broken". Classification now comes from git's real output only.
if ($Force) {
    Write-Host "[3/3] FORCE pushing (overwriting remote history) ..." -ForegroundColor Magenta
    $pushOut = (git push --force $Remote $Branch 2>&1 | Out-String)
} else {
    Write-Host "[3/3] pushing ..." -ForegroundColor Cyan
    $pushOut = (git push -u $Remote $Branch 2>&1 | Out-String)
}
$pushCode = $LASTEXITCODE
Write-Host $pushOut.TrimEnd()

if ($pushCode -ne 0) {
    $cls = "UNKNOWN"
    $hint = "unclassified - send the whole window to the team lead"
    if ($pushOut -match '\[rejected\]|non-fast-forward|fetch first|Updates were rejected') {
        $cls = "REJECTED"
        $hint = "remote has newer commits: run pull.cmd first, then push.cmd again"
    } elseif ($pushOut -match 'Authentication failed|403 Forbidden|Permission denied|invalid username or password') {
        $cls = "AUTH"
        $hint = "wrong password: Gitee needs a PERSONAL ACCESS TOKEN, not your login password"
    } elseif ($pushOut -match 'schannel:|SEC_E_|SSL certificate problem|OpenSSL SSL_|certificate verify failed') {
        $cls = "TLS"
        $hint = "TLS problem on this machine: try  git config http.sslBackend openssl"
    } elseif ($pushOut -match 'not found|does not appear to be a git repository') {
        $cls = "NO_REPO"
        $hint = "repo URL wrong, or you are not a member of this repository"
    }

    Write-Host ""
    Write-Host "[RESULT] $cls" -ForegroundColor Red
    Write-Host "       $hint" -ForegroundColor Yellow
    Write-Host "[FAIL] push failed ($cls)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[OK] pushed. Remember to update the team task board in docs/ (status + next step)!" -ForegroundColor Green
