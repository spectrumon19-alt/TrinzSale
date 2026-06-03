#!/bin/bash
# start_pos.sh - Simple script to start the POS system

echo "========================================"
echo "Point of Sale System - Startup Script"
echo "========================================"

# Check if virtual environment exists
if [ -f "venv/bin/activate" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
else
    echo "No virtual environment found. Using system Python."
    echo "If you encounter issues, create a virtual environment first:"
    echo "python3 -m venv venv"
    echo "source venv/bin/activate"
    echo "pip install -r requirements.txt"
    echo
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "Warning: .env file not found!"
    echo "Please create a .env file with your database credentials."
    echo "Example:"
    echo "SECRET_KEY=your-secret-key-here"
    echo "DB_HOST=localhost"
    echo "DB_NAME=pos_db"
    echo "DB_USER=your_postgres_username"
    echo "DB_PASSWORD=your_postgres_password"
    echo
    read -p "Press Enter to continue or CTRL+C to exit..."
fi

echo "Starting POS System..."
echo "The application will be available at http://localhost:5000"
echo "Press CTRL+C to stop the server"
echo

python3 app.py

echo
echo "POS System stopped."