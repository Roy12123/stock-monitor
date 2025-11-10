#!/bin/bash
# Stock Monitor Startup Script

echo "Starting Stock Monitor Application..."
echo "Python version:"
python --version

echo "Starting Flask-SocketIO with threading mode..."
exec python app.py