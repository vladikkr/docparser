@echo off
REM One-time setup for DocParser manual mode (Windows).
REM Creates a virtualenv and installs everything needed to read receipts.

cd /d "%~dp0"

echo.
echo === Checking Python ===
python --version 2>nul
if errorlevel 1 (
    echo [X] Python not found.
    echo     Install Python 3.11+ from https://www.python.org/downloads/
    echo     IMPORTANT: tick "Add python.exe to PATH" during install.
    pause
    exit /b 1
)

echo.
echo === Creating virtual environment ===
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 (
        echo [X] Could not create venv.
        pause
        exit /b 1
    )
    echo     created
) else (
    echo     already exists
)

set PY=.venv\Scripts\python.exe

echo.
echo === Installing dependencies ===
echo     this takes a few minutes on the first run
"%PY%" -m pip install --quiet --upgrade pip
"%PY%" -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo [X] Core install failed.
    pause
    exit /b 1
)
"%PY%" -m pip install --quiet -r requirements-ocr.txt
if errorlevel 1 (
    echo [!] OCR extras failed to install. QR reading may not work.
)

echo.
echo === Verifying QR reader ===
"%PY%" -c "from pyzbar.pyzbar import decode; print('    zbar (pyzbar): OK')" 2>nul
if errorlevel 1 (
    echo [!] pyzbar missing. Run: .venv\Scripts\python.exe -m pip install pyzbar
)

echo.
echo === Checking Tesseract (needed for OCR) ===
where tesseract >nul 2>nul
if errorlevel 1 (
    if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
        echo     found in Program Files
    ) else (
        echo [!] Tesseract not installed. Installing with winget...
        winget install --id UB-Mannheim.TesseractOCR --silent --accept-package-agreements --accept-source-agreements
    )
)

echo.
echo === Checking language packs ===
"%PY%" -c "import sys; sys.path.insert(0,'.'); from app.services.ocr import available_languages; print('     languages:', available_languages())" 2>nul
"%PY%" -c "import sys; sys.path.insert(0,'.'); from app.services.ocr import available_languages; import sys as s; s.exit(0 if 'rus' in available_languages() else 1)" 2>nul
if errorlevel 1 (
    echo [!] Russian language pack missing.
    echo     Download rus.traineddata into %%LOCALAPPDATA%%\docparser\tessdata\ :
    echo     https://github.com/tesseract-ocr/tessdata_best/raw/main/rus.traineddata
)

echo.
echo ============================================
echo   Setup complete.
echo.
echo   To parse a receipt:
echo     .venv\Scripts\python.exe scripts\parse_receipt.py C:\path\to\receipt.jpg
echo ============================================
pause
