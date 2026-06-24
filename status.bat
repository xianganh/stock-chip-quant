@echo off
REM ============================================================
REM  status.bat - 快速查看仓库状态
REM  Usage:
REM    status.bat
REM ============================================================
setlocal

set "GIT_PATH=C:\Users\xanhe\Tools\PortableGit\cmd;C:\Users\xanhe\Tools\PortableGit\bin;C:\Users\xanhe\Tools\PortableGit\usr\bin;C:\Users\xanhe\Tools\PortableGit\mingw64\bin"
set "PATH=%GIT_PATH%;%PATH%"

cd /d "%~dp0"

set "BRANCH=master"
set "REMOTE=origin"

echo === [1/4] Branch ===
git branch --show-current
echo.

echo === [2/4] Status ===
git status -sb
echo.

echo === [3/4] Last 5 commits (local) ===
git log --oneline -5
echo.

echo === [4/4] Sync status with remote ===
git fetch %REMOTE% 2>nul
git rev-list --left-right --count %BRANCH%...%REMOTE%/%BRANCH%
echo Format: ahead  behind
echo   ahead:  local commits not pushed
echo   behind: remote commits not pulled
echo.

echo === Latest 3 remote commits ===
git log %REMOTE%/%BRANCH% --oneline -3
echo.

endlocal