#!/bin/bash
# run.sh - Script to start the POS System

echo "Starting POS System..."

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
else
    echo "Warning: Virtual environment not found. Using system Python."
fi

# Check if required environment variables are set
if [ ! -f .env ]; then
    echo "Error: .env file not found. Please create one with your database credentials."
    exit 1
fi

# Start the Flask application
echo "Starting Flask server..."
python app.py