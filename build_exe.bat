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
    --icon main.ico ^
    --add-data "archive.png;." ^
    --add-data "arrow-left.png;." ^
    --add-data "arrow-right.png;." ^
    --add-data "download.png;." ^
    --add-data "flush.png;." ^
    --add-data "gear-fill.png;." ^
    --add-data "house.png;." ^
    --add-data "main.ico;." ^
    --add-data "on.mp3;." ^
    --add-data "play-fill.png;." ^
    --add-data "search.png;." ^
    main.py

if errorlevel 1 (
    echo Build failed.
    exit /b 1
)

echo Build complete. Output is in dist\MyInstantsDownloader\
