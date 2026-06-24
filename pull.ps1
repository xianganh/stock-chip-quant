# ============================================================
#  pull.ps1 - 从 GitHub 拉取最新代码 (PowerShell 版本)
#  Usage:
#    .\pull.ps1                  快速拉取 (fast-forward only)
#    .\pull.ps1 -Rebase          变基模式拉取
#    .\pull.ps1 -Force           强制重置到远程 (危险!)
# ============================================================
param(
    [switch]$Rebase,
    [switch]$Force
)

$env:Path = 'C:\Users\xanhe\Tools\PortableGit\cmd;C:\Users\xanhe\Tools\PortableGit\bin;C:\Users\xanhe\Tools\PortableGit\usr\bin;C:\Users\xanhe\Tools\PortableGit\mingw64\bin;' + $env:Path
Set-Location $PSScriptRoot

$Branch = 'master'
$Remote = 'origin'

function Write-Step($step, $title) {
    Write-Host ""
    Write-Host "=== $step $title ===" -ForegroundColor Cyan
}

function Write-Warn-Step($msg) {
    Write-Host ""
    Write-Host "[WARN] $msg" -ForegroundColor Yellow
}

function Write-Error-Step($msg) {
    Write-Host ""
    Write-Host "[ERROR] $msg" -ForegroundColor Red
}

Write-Step "[1/4]" "git fetch"
git fetch $Remote
if ($LASTEXITCODE -ne 0) {
    Write-Error-Step "git fetch failed. Check network / SSH key."
    exit 1
}

if ($Force) {
    $confirm = Read-Host "!! DANGER !! Force reset to remote? All local uncommitted changes will be LOST. Type YES to continue"
    if ($confirm -ne "YES") {
        Write-Host "Cancelled." -ForegroundColor Yellow
        exit 1
    }

    Write-Step "[2/4]" "FORCE RESET to remote/$Branch"
    git reset --hard "$Remote/$Branch"

    Write-Step "[3/4]" "Clean untracked files"
    git clean -fd
} else {
    Write-Step "[2/4]" "git pull (mode: $(if ($Rebase) {'rebase'} else {'ff-only'}))"
    if ($Rebase) {
        git pull --rebase $Remote $Branch
    } else {
        git pull --ff-only $Remote $Branch
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Warn-Step "Fast-forward failed. Local has unmerged commits."
        Write-Host "Options:"
        Write-Host "  pull.ps1 -Rebase : rebase local commits on top of remote"
        Write-Host "  pull.ps1 -Force  : RESET local to remote (DESTRUCTIVE)"
        exit 1
    }
}

Write-Step "[3/4]" "Status"
git status -sb

Write-Step "[4/4]" "Latest 3 commits"
git log --oneline -3

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green