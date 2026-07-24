$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectDir

python -m pip install -r .\requirements.txt
python -m pip install -r .\requirements-build.txt
python -m unittest discover -s tests -v

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name GDUTAutoLogin `
    --version-file .\version_info.txt `
    .\app.py

$releaseDir = Join-Path $projectDir 'release'
New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
$releaseExe = Join-Path $releaseDir 'GDUTAutoLogin-1.0.0-win64.exe'
Copy-Item -LiteralPath .\dist\GDUTAutoLogin.exe -Destination $releaseExe -Force

$selfTest = Join-Path $releaseDir 'self-test.json'
$previousDataDir = $env:GDUT_AUTOLOGIN_DATA_DIR
$env:GDUT_AUTOLOGIN_DATA_DIR = Join-Path $releaseDir 'self-test-data'
$process = Start-Process -FilePath $releaseExe -ArgumentList @('--self-test', ('"{0}"' -f $selfTest)) -Wait -PassThru
if ($null -eq $previousDataDir) {
    Remove-Item Env:GDUT_AUTOLOGIN_DATA_DIR -ErrorAction SilentlyContinue
} else {
    $env:GDUT_AUTOLOGIN_DATA_DIR = $previousDataDir
}
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $selfTest)) {
    throw 'Packaged executable self-test failed.'
}
$result = Get-Content -Raw -Encoding UTF8 -LiteralPath $selfTest | ConvertFrom-Json
if (-not $result.ok -or -not $result.frozen) {
    throw 'Packaged executable returned an invalid self-test result.'
}
Remove-Item -LiteralPath $selfTest -Force
$releaseRootFull = [System.IO.Path]::GetFullPath($releaseDir)
$selfTestData = [System.IO.Path]::GetFullPath((Join-Path $releaseDir 'self-test-data'))
if (-not $selfTestData.StartsWith($releaseRootFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe self-test cleanup path: $selfTestData"
}
Remove-Item -LiteralPath $selfTestData -Recurse -Force

$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $releaseExe
"$($hash.Hash.ToLower())  $([System.IO.Path]::GetFileName($releaseExe))" |
    Set-Content -Encoding ASCII -LiteralPath (Join-Path $releaseDir 'SHA256SUMS.txt')

Write-Host "Build complete: $releaseExe"
