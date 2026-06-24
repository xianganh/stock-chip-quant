@echo off
setlocal
set "PATH=C:\Users\xanhe\Tools\PortableGit\cmd;%PATH%"
cd /d "E:\work\stock\stock-chip-quant"

echo === Cleanup previous demo state ===
git reset HEAD -- . 2>nul
git status -sb
echo.

echo === Step 1: Create test file ===
echo # Test commit 2026-06-24 > DEMO_TEST.md
echo Created DEMO_TEST.md
echo.

echo === Step 2: git status ===
git status -sb
echo.

echo === Step 3: git add (stage) ===
git add DEMO_TEST.md
git status -sb
echo.

echo === Step 4: git commit (local) ===
git commit -m "test: add DEMO_TEST.md (verify push works)"
git log --oneline -3
echo.

echo === Step 5: git push to GitHub ===
git push origin master
echo.

echo === Step 6: Verify on GitHub via API ===
powershell -ExecutionPolicy Bypass -NoProfile -Command "try { $r = Invoke-RestMethod -Uri 'https://api.github.com/repos/xianganh/stock-chip-quant/commits?per_page=3' -Headers @{'User-Agent'='check'}; $r | Select-Object -First 3 | ForEach-Object { Write-Host ('  ' + $_.sha + '  ' + $_.commit.message.Substring(0, [Math]::Min(60, $_.commit.message.Length))) } } catch { Write-Host 'API check skipped' }"
echo.

echo === Step 7: Cleanup - remove the demo file ===
del DEMO_TEST.md
git add -A
git status -sb
git commit -m "test: remove DEMO_TEST.md"
git push origin master
echo.

echo === Step 8: Final state ===
git status -sb
git log --oneline -5
endlocal
