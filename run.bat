@echo off
REM run.bat - Script to start the POS System (Windows)

echo Starting POS System...

REM Activate virtual environment if it exists
if exist venv\Scripts\activate.bat (
    echo Activating virtual environment...
    call venv\Scripts\activate
) else (
    echo Warning: Virtual environment not found. Using system Python.
)

REM Check if required environment variables are set
if not exist .env (
    echo Error: .env file not found. Please create one with your database credentials.
    exit /b 1
)

REM Start the Flask application
echo Starting Flask server...
python app.py