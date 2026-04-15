#!/bin/bash
set -e

# Change to script directory
cd "$(dirname "$0")"

echo "🚀 Setting up OpenClaw Dashboard..."

# Install Python dependencies
echo "📦 Installing Python dependencies..."
pip3 install --break-system-packages -r requirements.txt

# Install systemd service
echo "🔧 Installing systemd service..."
sudo cp openclaw-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable openclaw-dashboard.service

# Start the service
echo "▶️  Starting OpenClaw Dashboard service..."
sudo systemctl start openclaw-dashboard.service

# Wait a moment for service to start
sleep 2

# Check status
if systemctl is-active --quiet openclaw-dashboard.service; then
    echo ""
    echo "✅ OpenClaw Dashboard is now running!"
    echo ""
    echo "🌐 Access the dashboard at:"
    echo "   http://localhost:5000"
    echo ""
    echo "🌍 To access from other devices on your network:"
    echo "   Find your Raspberry Pi's IP address with: ip addr show"
    echo "   Then use: http://<YOUR_PI_IP>:5000"
    echo ""
    echo "📋 Service management commands:"
    echo "   Check status: sudo systemctl status openclaw-dashboard.service"
    echo "   View logs: sudo journalctl -u openclaw-dashboard.service -f"
    echo "   Restart: sudo systemctl restart openclaw-dashboard.service"
    echo "   Stop: sudo systemctl stop openclaw-dashboard.service"
    echo ""
else
    echo "❌ Failed to start dashboard service. Check logs with:"
    echo "   sudo journalctl -u openclaw-dashboard.service -n 50"
    exit 1
fi
