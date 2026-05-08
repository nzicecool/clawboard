# Configuration

## Guardrail Configuration

The main config file is `guardrail_config.json`. This controls budget limits, anomaly detection, and alerting.

### Budget

```json
{
  "budget": {
    "daily_cap_usd": 10,
    "warning_threshold_pct": 75,
    "critical_threshold_pct": 100,
    "pricing": {
      "glm-5.1": {
        "input_per_1k": 0.001,
        "output_per_1k": 0.002,
        "cache_read_per_1k": 0.0001
      },
      "default": {
        "input_per_1k": 0.001,
        "output_per_1k": 0.002,
        "cache_read_per_1k": 0.0001
      }
    }
  }
}
```

| Field | Description |
|---|---|
| `daily_cap_usd` | Maximum daily spend before critical alert |
| `warning_threshold_pct` | % of daily cap that triggers a warning |
| `critical_threshold_pct` | % of daily cap that triggers a critical alert |
| `pricing` | Per-model cost rates (per 1K tokens) |

### Per-Job Limits

```json
{
  "per_job": {
    "max_tokens_per_run": 500000,
    "max_duration_ms": 600000,
    "max_consecutive_failures": 3
  }
}
```

| Field | Description |
|---|---|
| `max_tokens_per_run` | Alert if a single run exceeds this |
| `max_duration_ms` | Alert if a run takes longer than this |
| `max_consecutive_failures` | Alert after N consecutive failed runs |

### Anomaly Detection

```json
{
  "anomaly": {
    "spike_multiplier": 2.5,
    "min_runs_for_baseline": 3,
    "cache_efficiency_floor_pct": 30
  }
}
```

| Field | Description |
|---|---|
| `spike_multiplier` | Alert if usage spikes above N× average |
| `min_runs_for_baseline` | Minimum runs before anomaly detection kicks in |
| `cache_efficiency_floor_pct` | Alert if cache read % drops below this |

### Alerting

```json
{
  "alerts": {
    "whatsapp": true,
    "email": "your-email@example.com",
    "email_from": "ClawBoard Alerts <alerts@yourdomain.com>",
    "cooldown_minutes": 120,
    "severities_to_alert": ["critical", "warning"]
  }
}
```

| Field | Description |
|---|---|
| `whatsapp` | Send alerts via WhatsApp (requires OpenClaw WhatsApp plugin) |
| `email` | Alert recipient email address |
| `email_from` | Sender address (requires AgentMail or SMTP) |
| `cooldown_minutes` | Minimum time between duplicate alerts |
| `severities_to_alert` | Which severity levels trigger alerts |

## Live Configuration

You can update guardrail config via the API without restarting:

```bash
# Get current config
curl http://localhost:5000/api/guardrail-config

# Update config
curl -X POST http://localhost:5000/api/guardrail-config \
  -H "Content-Type: application/json" \
  -d '{"budget": {"daily_cap_usd": 15}}'
```

The dashboard UI also provides a guardrail settings panel for live updates.

## Database

ClawBoard uses SQLite with WAL mode. The database is stored at `data/dashboard.db`.

### Tables

| Table | Purpose |
|---|---|
| `token_usage` | Cron job token consumption per run |
| `interactive_usage` | Non-cron session token usage |
| `alerts` | Guardrail alert history |
| `health_checks` | Health check snapshots |

### Cleanup

Old data is automatically cleaned up:
- Token entries older than 30 days are pruned
- Alerts are kept to a maximum of 500 entries
- Health check history is maintained for trending
