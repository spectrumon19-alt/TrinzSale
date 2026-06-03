#!/bin/bash
# Build script for Render deployment

# Print environment variables for debugging
echo "Environment variables:"
echo "PYTHON_VERSION: $PYTHON_VERSION"
echo "PORT: $PORT"
echo "PIP_REQUIREMENTS_FILE: $PIP_REQUIREMENTS_FILE"

# Explicitly set Python version
export PYTHON_VERSION=3.11.9

# Set environment variables to force binary installations
export PIP_ONLY_BINARY=:all:
export PIP_PREFER_BINARY=true
export PIP_NO_CACHE_DIR=false

# Print Python version for debugging
echo "Python version before installation:"
python --version

# Print current directory and files for debugging
echo "Current directory:"
pwd
echo "Files in current directory:"
ls -la

# Update pip to the latest version
echo "Updating pip..."
pip install --upgrade pip

# Install other dependencies with optimization flags
# Use --prefer-binary to prefer pre-compiled wheels over source distributions
echo "Installing requirements..."
pip install --prefer-binary --no-cache-dir -r requirements.txt

# Print installed packages for debugging
echo "Installed packages:"
pip list

# Print Python version after installation
echo "Python version after installation:"
python --version

# Test gunicorn installation
echo "Testing gunicorn..."
if command -v gunicorn &> /dev/null
then
    echo "gunicorn is installed"
    gunicorn --version
else
    echo "gunicorn is not installed"
fi