# Getting Started

## Installation

### 1. Clone

```bash
git clone https://github.com/nzicecool/clawboard.git
cd clawboard
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

That's it — just Flask. ClawBoard uses SQLite internally, so no external database needed.

### 3. Run

```bash
python3 app.py
```

Open **http://localhost:5000** in your browser.

## Running as a Service

For production use, run ClawBoard as a systemd user service:

```bash
# Copy the service file
cp openclaw-dashboard.service ~/.config/systemd/user/

# Edit with your paths
nano ~/.config/systemd/user/openclaw-dashboard.service
```

Update these lines:
```ini
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/.openclaw/workspace/dashboard
Environment="PATH=/home/YOUR_USERNAME/.local/bin:/usr/bin:/bin"
```

Then enable and start:

```bash
systemctl --user daemon-reload
systemctl --user enable openclaw-dashboard
systemctl --user start openclaw-dashboard
```

### Service Management

```bash
# Check status
systemctl --user status openclaw-dashboard

# View logs
journalctl --user -u openclaw-dashboard -f

# Restart
systemctl --user restart openclaw-dashboard
```

## Data Ingestion

ClawBoard automatically ingests data on startup and on each API call from:

| Source | Path | What it reads |
|---|---|---|
| Cron runs | `~/.openclaw/cron/runs/*.jsonl` | Job IDs, token usage, model, duration |
| Session trajectories | `~/.openclaw/agents/main/sessions/*.trajectory.jsonl` | Interactive session token usage |

No manual data loading needed.

## Network Access

By default, ClawBoard listens on `0.0.0.0:5000` — accessible from your local network.

To access from another device:
```
http://YOUR_PI_IP:5000
```

To change the port, edit the last line of `app.py`:
```python
app.run(host='0.0.0.0', port=5001, debug=False)
```

## Next Steps

- [Configure guardrails](configuration.md) to set budget caps and alerting
- [Explore the API](api-reference.md) for custom integrations
- [Set up alerts](guardrails.md) for WhatsApp or email notifications
