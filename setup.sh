#!/bin/bash
# setup.sh - Setup script for POS System

echo "Setting up POS System..."

# Create virtual environment
echo "Creating virtual environment..."
python -m venv venv

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file..."
    cp .env.example .env
    echo "Please update the .env file with your database credentials"
fi

echo "Setup complete!"
echo "To run the application:"
echo "1. Activate the virtual environment: source venv/bin/activate"
echo "2. Start the server: python app.py"