@echo off
setlocal
set "PATH=C:\Users\xanhe\Tools\PortableGit\cmd;C:\Users\xanhe\Tools\PortableGit\bin;C:\Users\xanhe\Tools\PortableGit\usr\bin;C:\Users\xanhe\Tools\PortableGit\mingw64\bin;%PATH%"
cd /d "E:\work\stock\stock-chip-quant"
echo === git fetch ===
git fetch origin
echo.
echo === git pull --ff-only ===
git pull --ff-only
if errorlevel 1 (
    echo.
    echo Fast-forward failed, trying regular pull...
    git pull
)
echo.
echo === git status ===
git status -sb
echo.
echo === latest 3 commits ===
git log --oneline -3
endlocal
