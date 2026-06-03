@echo off
REM setup.bat - Setup script for POS System (Windows)

echo Setting up POS System...

REM Create virtual environment
echo Creating virtual environment...
python -m venv venv

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt

REM Create .env file if it doesn't exist
if not exist .env (
    echo Creating .env file...
    copy .env.example .env
    echo Please update the .env file with your database credentials
)

echo Setup complete!
echo To run the application:
echo 1. Activate the virtual environment: venv\Scripts\activate
echo 2. Start the server: python app.py