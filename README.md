# 🦀 ClawBoard

> Observability dashboard for [OpenClaw](https://github.com/openclaw/openclaw) AI agents

**ClawBoard** gives you real-time visibility into your OpenClaw agent infrastructure — token usage, costs, cron job management, health monitoring, and guardrail alerts — all from a single web UI.

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0+-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## ✨ Features

- **📊 Token Usage Tracking** — Monitor token consumption across all agents, broken down by model, job, and session type
- **💰 Cost Estimation** — Real-time cost tracking with configurable pricing per model
- **⏰ Cron Job Manager** — View, trigger, and monitor all scheduled agent tasks
- **🛡️ Guardrail Engine** — Budget caps, anomaly detection, duration limits, and failure alerts
- **🩺 Health Monitoring** — Rolling-window health checks (Green/Amber/Red) for all agents
- **🚨 Alerting** — WhatsApp + email alerts when things go wrong
- **📈 Interactive Charts** — Daily trends, model distribution, input vs output breakdowns
- **🔍 Session Inspector** — Drill into individual runs with input/output text

## 📸 Screenshots

| Token Usage | Job Manager | Health Monitor |
|:---:|:---:|:---:|
| *Token dashboard with charts* | *Cron job overview* | *Health + guardrails* |

## 🚀 Quick Start

### Prerequisites

- [OpenClaw](https://github.com/openclaw/openclaw) installed and running
- Python 3.9+
- pip

### Install

```bash
# Clone
git clone https://github.com/nzicecool/clawboard.git
cd clawboard

# Install dependencies
pip install -r requirements.txt

# Run
python3 app.py
```

Open http://localhost:5000 in your browser.

### Systemd Service (Recommended)

```bash
# Edit the service file with your user/path
cp openclaw-dashboard.service ~/.config/systemd/user/

# Edit User, WorkingDirectory, and Environment paths
nano ~/.config/systemd/user/openclaw-dashboard.service

# Enable and start
systemctl --user daemon-reload
systemctl --user enable openclaw-dashboard
systemctl --user start openclaw-dashboard
```

## ⚙️ Configuration

### Guardrail Config (`guardrail_config.json`)

```json
{
  "budget": {
    "daily_cap_usd": 10,
    "warning_threshold_pct": 75,
    "critical_threshold_pct": 100,
    "pricing": {
      "default": {
        "input_per_1k": 0.001,
        "output_per_1k": 0.002,
        "cache_read_per_1k": 0.0001
      }
    }
  },
  "per_job": {
    "max_tokens_per_run": 500000,
    "max_duration_ms": 600000,
    "max_consecutive_failures": 3
  },
  "anomaly": {
    "spike_multiplier": 2.5,
    "min_runs_for_baseline": 3
  },
  "alerts": {
    "whatsapp": true,
    "email": "your-email@example.com"
  }
}
```

### Data Storage

ClawBoard uses SQLite (`data/dashboard.db`) — no external database needed. Data is auto-ingested from:

- `~/.openclaw/cron/runs/` — cron job run history
- `~/.openclaw/agents/main/sessions/` — interactive session trajectories

## 🏗️ Architecture

```
ClawBoard/
├── app.py                 # Flask app + API endpoints
├── db.py                  # SQLite database layer
├── guardrail_engine.py    # Budget, anomaly, health checks
├── guardrail_config.json  # Guardrail configuration
├── alert_sender.py        # WhatsApp + email alerting
├── migrate_to_sqlite.py   # Migration helper
├── openclaw-dashboard.service  # Systemd unit file
├── setup.sh               # Installation script
├── requirements.txt       # Python dependencies
├── static/                # CSS, JS, images
├── templates/             # Jinja2 HTML templates
└── docs/                  # GitHub Pages documentation
```

## 🔌 API Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Main dashboard |
| `GET /token-usage` | Token usage dashboard |
| `GET /health` | Health monitor |
| `GET /api/token-usage` | Aggregated token data (JSON) |
| `GET /api/cron-jobs` | List all cron jobs |
| `POST /api/cron-jobs/:id/run` | Trigger a job |
| `GET /api/skills` | List available skills |
| `GET /api/health` | Health check data |
| `GET /api/alerts` | Alert history |
| `GET/POST /api/guardrail-config` | Get/update guardrail config |

## 🤝 Contributing

Contributions welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built for the [OpenClaw](https://github.com/openclaw/openclaw) agent platform
- Uses [Flask](https://flask.palletsprojects.com/), [Chart.js](https://www.chartjs.org/), [Tailwind CSS](https://tailwindcss.com/)
