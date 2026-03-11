#!/bin/bash

# Setup script for Spotlight project

echo "Setting up Spotlight project..."

# Create virtual environment
echo "Creating Python virtual environment..."
python3 -m venv venv

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install Python dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file from .env.example..."
    cp .env.example .env
fi

# Setup frontend
echo "Setting up React frontend..."
cd frontend
npm install
cd ..

echo "Setup complete!"
echo ""
echo "To start the backend:"
echo "  1. Activate virtual environment: source venv/bin/activate"
echo "  2. Run: cd backend && python app.py"
echo ""
echo "To start the frontend:"
echo "  1. Run: cd frontend && npm start"
