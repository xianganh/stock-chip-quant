@echo off
REM ============================================================
REM  sync.bat - 双向同步 (先 pull 再 push)
REM  Usage:
REM    sync.bat                  pull + push
REM    sync.bat --no-push        只 pull 不 push (安全模式)
REM ============================================================
setlocal

set "GIT_PATH=C:\Users\xanhe\Tools\PortableGit\cmd;C:\Users\xanhe\Tools\PortableGit\bin;C:\Users\xanhe\Tools\PortableGit\usr\bin;C:\Users\xanhe\Tools\PortableGit\mingw64\bin"
set "PATH=%GIT_PATH%;%PATH%"

cd /d "%~dp0"

set "BRANCH=master"
set "REMOTE=origin"
set "PUSH_ENABLED=1"

if /i "%~1"=="--no-push" set "PUSH_ENABLED=0"

echo =====================================================
echo   sync.bat - 双向同步
echo   Branch: %BRANCH%
echo   Remote: %REMOTE%
echo   Push:   %PUSH_ENABLED%
echo =====================================================
echo.

echo === Phase 1: PULL from remote ===
call :do_pull
if errorlevel 1 (
    echo [ABORT] Pull failed. Resolve conflicts first.
    endlocal & exit /b 1
)
echo.

if "%PUSH_ENABLED%"=="0" (
    echo [SKIP] Push disabled (--no-push).
    endlocal & exit /b 0
)

echo === Phase 2: PUSH to remote ===
call :do_push
if errorlevel 1 (
    echo [ABORT] Push failed.
    endlocal & exit /b 1
)
echo.

echo === Sync complete ===
endlocal & exit /b 0

REM ============================================================
:do_pull
echo --- git fetch ---
git fetch %REMOTE%
if errorlevel 1 exit /b 1

echo --- git pull --ff-only ---
git pull --ff-only %REMOTE% %BRANCH%
if errorlevel 1 (
    echo [WARN] FF-only failed. Trying rebase...
    git pull --rebase %REMOTE% %BRANCH%
    if errorlevel 1 exit /b 1
)
exit /b 0

REM ============================================================
:do_push
git status -sb
echo --- git add -A ---
git add -A

git diff --cached --quiet
if %errorlevel%==0 (
    echo Nothing to commit. Skip push.
    exit /b 0
)

echo --- git commit ---
git commit -m "sync: auto commit %date% %time%"
if errorlevel 1 exit /b 1

echo --- git push ---
git push %REMOTE% %BRANCH%
exit /b %errorlevel%