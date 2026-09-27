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
echo === Checking Tesseract (optional, for photo OCR) ===
"%PY%" -c "import pytesseract; pytesseract.get_tesseract_version(); print('    tesseract: OK')" 2>nul
if errorlevel 1 (
    echo [i] Tesseract not installed. Fine for now - QR is the main path.
    echo     Install later from:
    echo     https://github.com/UB-Mannheim/tesseract/wiki
)

echo.
echo ============================================
echo   Setup complete.
echo.
echo   To parse a receipt:
echo     .venv\Scripts\python.exe scripts\parse_receipt.py C:\path\to\receipt.jpg
echo ============================================
pause
