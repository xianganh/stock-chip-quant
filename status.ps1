# ============================================================
#  status.ps1 - 快速查看仓库状态 (PowerShell 版本)
#  Usage:
#    .\status.ps1
# ============================================================

$env:Path = 'C:\Users\xanhe\Tools\PortableGit\cmd;C:\Users\xanhe\Tools\PortableGit\bin;C:\Users\xanhe\Tools\PortableGit\usr\bin;C:\Users\xanhe\Tools\PortableGit\mingw64\bin;' + $env:Path
Set-Location $PSScriptRoot

$Branch = 'master'
$Remote = 'origin'

function Write-Step($step, $title) {
    Write-Host ""
    Write-Host "=== $step $title ===" -ForegroundColor Cyan
}

Write-Step "[1/4]" "Branch"
git branch --show-current

Write-Step "[2/4]" "Status"
git status -sb

Write-Step "[3/4]" "Last 5 commits (local)"
git log --oneline -5

Write-Step "[4/4]" "Sync status with remote"
git fetch $Remote 2>&1 | Out-Null
$sync = git rev-list --left-right --count "$Branch...$Remote/$Branch"
Write-Host $sync -ForegroundColor Yellow
Write-Host "Format: ahead  behind" -ForegroundColor Gray
Write-Host "  ahead:  local commits not pushed" -ForegroundColor Gray
Write-Host "  behind: remote commits not pulled" -ForegroundColor Gray

Write-Host ""
Write-Host "Latest 3 remote commits:" -ForegroundColor Cyan
git log "$Remote/$Branch" --oneline -3