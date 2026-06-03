@echo off
REM start_pos.bat - Simple script to start the POS system

echo ========================================
echo Point of Sale System - Startup Script
echo ========================================

REM Check if virtual environment exists
if exist venv\Scripts\activate.bat (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
) else (
    echo No virtual environment found. Using system Python.
    echo If you encounter issues, create a virtual environment first:
    echo python -m venv venv
    echo call venv\Scripts\activate.bat
    echo pip install -r requirements.txt
    echo.
)

REM Check if .env file exists
if not exist .env (
    echo Warning: .env file not found!
    echo Please create a .env file with your database credentials.
    echo Example:
    echo SECRET_KEY=your-secret-key-here
    echo DB_HOST=localhost
    echo DB_NAME=pos_db
    echo DB_USER=your_postgres_username
    echo DB_PASSWORD=your_postgres_password
    echo.
    pause
)

echo Starting POS System...
echo The application will be available at http://localhost:5000
echo Press CTRL+C to stop the server
echo.

python app.py

echo.
echo POS System stopped.
pause