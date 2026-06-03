@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  TrintzPOS  —  One-click build script
REM  Output: dist\TrintzPOS\TrintzPOS.exe
REM ─────────────────────────────────────────────────────────────────────────────

echo.
echo  ===================================================
echo   TrintzPOS Build Script
echo  ===================================================
echo.

REM ── 1. Check Python ──────────────────────────────────────────────────────────
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ and add it to PATH.
    pause & exit /b 1
)

REM ── 2. Install / upgrade build tools ─────────────────────────────────────────
echo [STEP 1/5] Installing build dependencies...
pip install --quiet --upgrade pyinstaller cryptography
IF ERRORLEVEL 1 ( echo [ERROR] pip install failed. & pause & exit /b 1 )

REM ── 3. Ensure master.key exists ──────────────────────────────────────────────
echo [STEP 2/5] Checking master.key...
IF NOT EXIST "master.key" (
    echo  master.key not found — generating a new one.
    python -c "from cryptography.fernet import Fernet; open('master.key','wb').write(Fernet.generate_key()); print('  master.key created.')"
    echo.
    echo  [IMPORTANT] Back up master.key before distributing.
    echo  Without it, your clients CANNOT activate their licenses!
    echo.
)

REM ── 4. Clean previous build ───────────────────────────────────────────────────
echo [STEP 3/5] Cleaning previous build...
IF EXIST "dist\TrintzPOS" rmdir /S /Q "dist\TrintzPOS"
IF EXIST "build"           rmdir /S /Q "build"

REM ── 5. Build with PyInstaller ─────────────────────────────────────────────────
echo [STEP 4/5] Running PyInstaller...
pyinstaller pos.spec --noconfirm --clean
IF ERRORLEVEL 1 ( echo [ERROR] PyInstaller failed. & pause & exit /b 1 )

REM ── 6. Post-build: copy master.key into dist ─────────────────────────────────
echo [STEP 5/5] Finalising distribution folder...
copy /Y "master.key" "dist\TrintzPOS\master.key" >nul

REM Copy .env if present (DB connection string, etc.)
IF EXIST ".env" (
    copy /Y ".env" "dist\TrintzPOS\.env" >nul
    echo  Copied .env
)

echo.
echo  ===================================================
echo   Build complete!
echo   Output: dist\TrintzPOS\TrintzPOS.exe
echo.
echo   To distribute:
echo     1. Zip the entire dist\TrintzPOS\ folder.
echo     2. Send the zip to your client.
echo     3. Client runs TrintzPOS.exe and enters their license key.
echo.
echo   NEVER share master.key with clients.
echo  ===================================================
echo.
pause
