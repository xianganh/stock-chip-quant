@echo off
REM ============================================================
REM  push.bat - 推送本地变更到 GitHub
REM  Usage:
REM    push.bat                  自动 add all + commit (使用默认消息) + push
REM    push.bat "commit message" 自定义 commit message
REM ============================================================
setlocal enabledelayedexpansion

REM 配置 PortableGit 路径
set "GIT_PATH=C:\Users\xanhe\Tools\PortableGit\cmd;C:\Users\xanhe\Tools\PortableGit\bin;C:\Users\xanhe\Tools\PortableGit\usr\bin;C:\Users\xanhe\Tools\PortableGit\mingw64\bin"
set "PATH=%GIT_PATH%;%PATH%"

REM 切换到脚本所在目录
cd /d "%~dp0"

REM 默认分支
set "BRANCH=master"
set "REMOTE=origin"

echo === [1/5] Check git status ===
git status -sb
echo.

REM 如果第一个参数是 commit message
set "MSG=%~1"
if "%MSG%"=="" set "MSG=update: auto commit %date% %time%"

REM 检查是否有变更
git diff --quiet HEAD 2>nul
set "HAS_CHANGE=%errorlevel%"

git status -sb | findstr /R "^.. .* " >nul
set "HAS_UNTRACKED=%errorlevel%"

if %HAS_CHANGE%==0 if %HAS_UNTRACKED%==1 (
    echo Nothing to commit. Working tree clean.
    endlocal & exit /b 0
)

echo === [2/5] git add -A ===
git add -A
git status -sb
echo.

echo === [3/5] git commit ===
git commit -m "%MSG%"
if errorlevel 1 (
    echo.
    echo [ERROR] git commit failed. Please check conflicts or empty commit.
    endlocal & exit /b 1
)
echo.

echo === [4/5] git push to GitHub ===
git push %REMOTE% %BRANCH%
if errorlevel 1 (
    echo.
    echo [ERROR] git push failed. Possible causes:
    echo   1. No network
    echo   2. SSH key not configured
    echo   3. Conflict with remote
    echo Run pull.bat first if remote has new commits.
    endlocal & exit /b 1
)
echo.

echo === [5/5] Verify on GitHub ===
powershell -ExecutionPolicy Bypass -NoProfile -Command "try { $r = Invoke-RestMethod -Uri 'https://api.github.com/repos/xianganh/stock-chip-quant/commits?per_page=3' -Headers @{'User-Agent'='push-verify'}; Write-Host 'Latest 3 commits on GitHub:' -ForegroundColor Cyan; $r | Select-Object -First 3 | ForEach-Object { $msg = $_.commit.message -replace '\r?\n', ' '; if ($msg.Length -gt 60) { $msg = $msg.Substring(0, 60) + '...' }; Write-Host ('  ' + $_.sha.Substring(0,7) + '  ' + $msg) -ForegroundColor Gray } } catch { Write-Host '[skip] GitHub API check failed (offline?)' -ForegroundColor Yellow }"

echo.
echo === Done ===
endlocal