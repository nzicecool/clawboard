# OpenClaw Dashboard

A web-based dashboard for managing your OpenClaw AI agents, scheduled tasks, and skills.

## Features

- 📊 **Overview Stats**: View active jobs, total skills, next scheduled run, and system status
- ⏰ **Scheduled Tasks**: View and manage all cron jobs with details like schedule, last run status, and next run time
- 🧩 **Skills**: Browse all available skills with descriptions
- 📜 **Run History**: View recent run history for each job
- ▶️ **Quick Actions**: Trigger jobs to run immediately, view job details in modals
- 🔄 **Auto-refresh**: Refresh button to update all data

## Access

### Local Network
Open your web browser and navigate to:
```
http://192.168.0.104:5000
```

### From the Pi itself
```
http://localhost:5000
```

### From Other Devices
Find your Pi's IP address:
```bash
ip addr show
```

Then use: `http://<YOUR_PI_IP>:5000`

## Service Management

### Check Status
```bash
sudo systemctl status openclaw-dashboard.service
```

### View Logs
```bash
sudo journalctl -u openclaw-dashboard.service -f
```

### Restart Service
```bash
sudo systemctl restart openclaw-dashboard.service
```

### Stop Service
```bash
sudo systemctl stop openclaw-dashboard.service
```

### Start Service
```bash
sudo systemctl start openclaw-dashboard.service
```

## Setup

The dashboard is automatically installed and configured as a systemd service. To reinstall:

```bash
cd /home/pi/.openclaw/workspace/dashboard
sudo ./setup.sh
```

## API Endpoints

The dashboard exposes several API endpoints:

- `GET /` - Main dashboard page
- `GET /api/cron-jobs` - List all cron jobs
- `GET /api/cron-jobs/<job_id>` - Get job run history
- `POST /api/cron-jobs/<job_id>/run` - Trigger job to run immediately
- `GET /api/skills` - List all available skills
- `GET /api/skills/<skill_name>` - Get skill details
- `GET /api/status` - Get OpenClaw system status
- `GET /api/sessions` - List all sessions

## Architecture

- **Backend**: Flask web server running on port 5000
- **Frontend**: HTML5 + Tailwind CSS for responsive, modern UI
- **Integration**: Uses OpenClaw CLI commands via subprocess
- **Service**: Managed by systemd for automatic startup and restarts

## Notes

- Dashboard runs on port 5000 by default
- Auto-restart on failure (systemd managed)
- Debug mode enabled (development server)
- For production use, consider using gunicorn with nginx

## Troubleshooting

### Dashboard not accessible
1. Check service status: `sudo systemctl status openclaw-dashboard.service`
2. View logs: `sudo journalctl -u openclaw-dashboard.service -n 50`
3. Restart service: `sudo systemctl restart openclaw-dashboard.service`

### Port 5000 in use
Edit `app.py` and change the port number:
```python
app.run(host='0.0.0.0', port=5001, debug=True)
```

Then restart the service.

### Permission denied errors
Make sure the service runs as the `pi` user and has access to the workspace:
```bash
sudo systemctl edit openclaw-dashboard.service
```
Add under `[Service]`:
```
User=pi
WorkingDirectory=/home/pi/.openclaw/workspace/dashboard
```
