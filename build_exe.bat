@echo off
setlocal

cd /d "%~dp0"

python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    python -m pip install pyinstaller
)

echo Building Windows executable...
python -m PyInstaller ^
    --noconfirm ^
    --windowed ^
    --name MyInstantsDownloader ^
    --icon "resources/main.ico" ^
    --add-data "resources;resources" ^
    main.py

if errorlevel 1 (
    echo Build failed.
    exit /b 1
)

echo Build complete. Output is in dist\MyInstantsDownloader\
