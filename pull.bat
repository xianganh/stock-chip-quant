@echo off
REM ============================================================
REM  pull.bat - 从 GitHub 拉取最新代码
REM  Usage:
REM    pull.bat                  快速拉取 (fast-forward only)
REM    pull.bat --rebase         变基模式拉取 (本地有提交时用)
REM    pull.bat --force          强制重置到远程 (危险!)
REM ============================================================
setlocal enabledelayedexpansion

REM 配置 PortableGit 路径
set "GIT_PATH=C:\Users\xanhe\Tools\PortableGit\cmd;C:\Users\xanhe\Tools\PortableGit\bin;C:\Users\xanhe\Tools\PortableGit\usr\bin;C:\Users\xanhe\Tools\PortableGit\mingw64\bin"
set "PATH=%GIT_PATH%;%PATH%"

REM 切换到脚本所在目录
cd /d "%~dp0"

set "BRANCH=master"
set "REMOTE=origin"
set "MODE=ff-only"
set "FORCE_RESET=0"

REM 参数解析
:parse_args
if "%~1"=="" goto after_parse
if /i "%~1"=="--rebase" set "MODE=rebase"
if /i "%~1"=="--ff-only" set "MODE=ff-only"
if /i "%~1"=="--force" (
    set "FORCE_RESET=1"
    set /p "CONFIRM=!! DANGER !! Force reset to remote? All local uncommitted changes will be LOST. Type YES to continue: "
    if not "!CONFIRM!"=="YES" (
        echo Cancelled.
        endlocal & exit /b 1
    )
)
shift
goto parse_args
:after_parse

echo === [1/4] git fetch ===
git fetch %REMOTE%
if errorlevel 1 (
    echo [ERROR] git fetch failed. Check network / SSH key.
    endlocal & exit /b 1
)
echo.

if %FORCE_RESET%==1 (
    echo === [2/4] FORCE RESET to remote/%BRANCH% ===
    git reset --hard %REMOTE%/%BRANCH%
    echo.
    echo === [3/4] Clean untracked files ===
    git clean -fd
    echo.
    echo === [4/4] Status ===
    goto show_status
)

echo === [2/4] git pull (mode: %MODE%) ===
if /i "%MODE%"=="rebase" (
    git pull --rebase %REMOTE% %BRANCH%
) else (
    git pull --ff-only %REMOTE% %BRANCH%
)
if errorlevel 1 (
    echo.
    echo [WARN] Fast-forward failed. Local has unmerged commits.
    echo Options:
    echo   pull.bat --rebase   : rebase local commits on top of remote
    echo   pull.bat --force    : RESET local to remote (DESTRUCTIVE)
    endlocal & exit /b 1
)
echo.

echo === [3/4] Status ===
:show_status
git status -sb
echo.

echo === [4/4] Latest 3 commits ===
git log --oneline -3
echo.

echo === Done ===
endlocal