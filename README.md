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

## Version Control (Git)

The dashboard code is version-controlled using Git. This allows us to:
- Track all changes
- Rollback to working versions if something breaks
- Compare changes between versions
- Maintain a clean history

### Git Workflow

#### Before Making Changes
```bash
cd ~/.openclaw/workspace/dashboard
git status          # Check current state
git diff            # See what will change
```

#### Commit Changes (Working State)
```bash
# 1. Stage changes
git add .

# 2. Commit with descriptive message
git commit -m "Fixed tab switching issue

- Removed broken JavaScript code in renderJobHistory function
- Dashboard now loads all metrics correctly
- No more stuck loading states"

# 3. View commit history
git log --oneline -5
```

#### Rollback to Working Version (If Something Breaks)
```bash
# View recent commits
git log --oneline

# Reset to specific commit (e.g., previous working version)
git reset --hard <commit-hash>

# Example: rollback to previous commit
git reset --hard HEAD~1

# Restart dashboard after rollback
sudo systemctl restart openclaw-dashboard.service
```

#### Check What Changed
```bash
# View changes since last commit
git diff HEAD

# View changes in specific file
git diff HEAD templates/index.html

# View commit details
git show <commit-hash>
```

#### Best Practices
1. **Commit frequently** - Small, focused commits are easier to understand and rollback
2. **Use descriptive messages** - Explain WHAT changed and WHY
3. **Test before committing** - Make sure dashboard works after changes
4. **Check git status** - Always see what will be committed before committing
5. **Keep history clean** - Don't commit broken code intentionally

### Example Workflow for Dashboard Updates
```bash
# 1. Make backup before major changes
git tag backup-before-$(date +%Y%m%d-%H%M%S)

# 2. Make your changes (edit files)

# 3. Test changes locally
python3 app.py  # Test on different port if needed

# 4. If working: commit changes
git add .
git commit -m "Fixed broken job history display

- Replaced broken JavaScript with proper error handling
- Added loading states for better UX
- Tested with all 5 cron jobs"

# 5. Restart dashboard service
sudo systemctl restart openclaw-dashboard.service

# 6. Verify in browser
# Open http://192.168.0.104:5000

# 7. If broken: rollback
git reset --hard HEAD~1
sudo systemctl restart openclaw-dashboard.service
```

### Quick Reference
| Command | Purpose |
|---------|---------|
| `git status` | Check current state |
| `git log --oneline` | View commit history |
| `git add .` | Stage all changes |
| `git commit -m "message"` | Commit changes |
| `git diff` | View unstaged changes |
| `git reset --hard HEAD~1` | Rollback to previous commit |
| `git show <hash>` | View commit details |
