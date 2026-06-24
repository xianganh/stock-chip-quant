$env:Path = 'C:\Users\xanhe\Tools\PortableGit\cmd;C:\Users\xanhe\Tools\PortableGit\bin;C:\Users\xanhe\Tools\PortableGit\usr\bin;C:\Users\xanhe\Tools\PortableGit\mingw64\bin;' + $env:Path
Set-Location $PSScriptRoot
Write-Host '=== git fetch ===' -ForegroundColor Cyan
git fetch origin
Write-Host "`n=== git pull --ff-only ===" -ForegroundColor Cyan
git pull --ff-only
Write-Host "`n=== git status ===" -ForegroundColor Cyan
git status -sb
Write-Host "`n=== latest 3 commits ===" -ForegroundColor Cyan
git log --oneline -3
