$ErrorActionPreference = 'Stop'
$sahlSourceRoot = $PSScriptRoot
$sahlBuildPython = Join-Path $sahlSourceRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $sahlBuildPython)) {
    py -3.12 -m venv (Join-Path $sahlSourceRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 virtual environment creation failed.' }
}
& $sahlBuildPython -m pip install -r (Join-Path $sahlSourceRoot 'requirements.txt') 'pyinstaller==6.22.3'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$sahlWebMapping = '{0}:web' -f (Join-Path $sahlSourceRoot 'web')
$sahlIconMapping = '{0}:.' -f (Join-Path $sahlSourceRoot 'sahl.ico')
$sahlBuildArguments = @('--noconfirm','--onefile','--windowed','--noupx','--name','SahlRemote-Desktop','--collect-data','customtkinter','--icon',(Join-Path $sahlSourceRoot 'sahl.ico'),'--add-data',$sahlWebMapping,'--add-data',$sahlIconMapping,'--distpath',(Join-Path $sahlSourceRoot 'build-output'),'--workpath',(Join-Path $sahlSourceRoot 'build-temp'),'--specpath',(Join-Path $sahlSourceRoot 'build-temp'))
$sahlSslCompanion = & $sahlBuildPython -c 'from pathlib import Path; import ssl; p=Path(ssl.__file__).with_name("codex-rejected-cas.pem"); print(p if p.is_file() else "")'
if ($sahlSslCompanion) { $sahlBuildArguments += @('--add-data',('{0}:.' -f $sahlSslCompanion)) }
$sahlBuildArguments += (Join-Path $sahlSourceRoot 'main.py')
& $sahlBuildPython -m PyInstaller @sahlBuildArguments
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
Write-Output (Join-Path $sahlSourceRoot 'build-output\SahlRemote-Desktop.exe')
