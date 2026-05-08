# Guardrails

ClawBoard's guardrail engine monitors your OpenClaw agents and alerts you when things go wrong.

## How It Works

The guardrail engine runs periodically (via cron) and checks:

1. **Budget** — Are you approaching or exceeding your daily spend cap?
2. **Failures** — Are jobs failing consecutively?
3. **Anomalies** — Is token usage spiking unexpectedly?
4. **Duration** — Are jobs running too long?
5. **Cache Efficiency** — Is the cache being underutilized?
6. **Quality** — Are jobs producing empty/useless results?

## Health Status

The overall health is calculated as a rolling status:

| Status | Meaning |
|---|---|
| 🟢 **Green** | All checks passing, no active alerts |
| 🟡 **Amber** | Minor issues detected (warnings, elevated usage) |
| 🔴 **Red** | Critical issues (budget exceeded, repeated failures) |

## Setting Up Guardrails

### 1. Configure `guardrail_config.json`

See [Configuration](configuration.md) for full options.

### 2. Set Up the Cron Job

Add a guardrail check cron job in OpenClaw:

```json
{
  "name": "ClawBoard Guardrail Check",
  "schedule": { "kind": "cron", "expr": "0 2,8,14,20 * * *" },
  "payload": {
    "kind": "agentTurn",
    "message": "Run guardrail check: exec python3 ~/.openclaw/workspace/dashboard/guardrail_engine.py"
  }
}
```

This runs every 6 hours.

### 3. Configure Alerts

#### WhatsApp Alerts

Requires the OpenClaw WhatsApp plugin. Set in config:

```json
{
  "alerts": {
    "whatsapp": true
  }
}
```

#### Email Alerts

Requires AgentMail (or modify `alert_sender.py` for SMTP). Set in config:

```json
{
  "alerts": {
    "email": "your-email@example.com",
    "email_from": "ClawBoard Alerts <alerts@yourdomain.com>"
  }
}
```

## Alert Severity Levels

| Level | When | Example |
|---|---|---|
| `info` | Informational, no action needed | New job registered |
| `warning` | Something to watch | Approaching budget cap |
| `critical` | Action required | Budget exceeded, job failing repeatedly |

## Alert Cooldown

Alerts use fingerprint-based deduplication with a cooldown window. The same alert won't fire again within the cooldown period (default: 120 minutes).

## Custom Checks

You can extend the guardrail engine by adding new check functions in `guardrail_engine.py`:

```python
def check_my_custom_thing(health_data, now_ms):
    """Custom health check"""
    alerts = []
    # Your logic here
    if something_wrong:
        alerts.append({
            'severity': 'warning',
            'category': 'custom',
            'title': 'Custom Check Failed',
            'message': 'Details here...'
        })
    return alerts
```

Register it in the `run_guardrails()` function:

```python
all_alerts += check_my_custom_thing(health_data, now_ms)
```
