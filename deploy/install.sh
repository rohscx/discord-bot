#!/bin/bash
# Install/update the Lounge Bot systemd service
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Lounge Bot Installer ==="

# Check for .env
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "ERROR: .env file not found. Copy .env.example to .env and fill in your values."
    exit 1
fi

# Create venv if missing
if [ ! -d "$PROJECT_DIR/venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$PROJECT_DIR/venv"
    "$PROJECT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
fi

# Install systemd service
echo "Installing systemd service..."
sudo cp "$SCRIPT_DIR/lounge-bot.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable lounge-bot
sudo systemctl restart lounge-bot

echo "=== Done ==="
echo "Check status: sudo systemctl status lounge-bot"
echo "View logs:    sudo journalctl -u lounge-bot -f"
