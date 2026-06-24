# ============================================================
#  push.ps1 - 推送本地变更到 GitHub (PowerShell 版本)
#  Usage:
#    .\push.ps1                  自动 add + commit + push
#    .\push.ps1 -Message "msg"   自定义 commit message
#    .\push.ps1 -NoPush         只 add + commit, 不 push
# ============================================================
param(
    [string]$Message = "",
    [switch]$NoPush
)

$env:Path = 'C:\Users\xanhe\Tools\PortableGit\cmd;C:\Users\xanhe\Tools\PortableGit\bin;C:\Users\xanhe\Tools\PortableGit\usr\bin;C:\Users\xanhe\Tools\PortableGit\mingw64\bin;' + $env:Path
Set-Location $PSScriptRoot

$Branch = 'master'
$Remote = 'origin'

if (-not $Message) {
    $Message = "update: auto commit $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
}

function Write-Step($step, $title) {
    Write-Host ""
    Write-Host "=== $step $title ===" -ForegroundColor Cyan
}

function Write-Error-Step($msg) {
    Write-Host ""
    Write-Host "[ERROR] $msg" -ForegroundColor Red
}

Write-Step "[1/5]" "Check git status"
git status -sb

# 检查是否有变更
$hasChange = $false
git diff --quiet HEAD 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { $hasChange = $true }
$untracked = git status -sb | Select-String '^\?\?'
if ($untracked) { $hasChange = $true }

if (-not $hasChange) {
    Write-Host "Nothing to commit. Working tree clean." -ForegroundColor Yellow
    exit 0
}

Write-Step "[2/5]" "git add -A"
git add -A
git status -sb

Write-Step "[3/5]" "git commit"
git commit -m $Message
if ($LASTEXITCODE -ne 0) {
    Write-Error-Step "git commit failed."
    exit 1
}

if ($NoPush) {
    Write-Host ""
    Write-Host "[SKIP] Push disabled (-NoPush)." -ForegroundColor Yellow
    Write-Host "=== Done ==="
    exit 0
}

Write-Step "[4/5]" "git push to GitHub"
git push $Remote $Branch
if ($LASTEXITCODE -ne 0) {
    Write-Error-Step "git push failed. Run pull.ps1 first if remote has new commits."
    exit 1
}

Write-Step "[5/5]" "Verify on GitHub"
try {
    $r = Invoke-RestMethod -Uri 'https://api.github.com/repos/xianganh/stock-chip-quant/commits?per_page=3' -Headers @{'User-Agent'='push-verify'}
    Write-Host "Latest 3 commits on GitHub:" -ForegroundColor Cyan
    $r | Select-Object -First 3 | ForEach-Object {
        $msg = $_.commit.message -replace "`r`n", " "
        if ($msg.Length -gt 60) { $msg = $msg.Substring(0, 60) + "..." }
        Write-Host ("  $($_.sha.Substring(0,7))  $msg") -ForegroundColor Gray
    }
} catch {
    Write-Host "[skip] GitHub API check failed (offline?)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green