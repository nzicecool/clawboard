# ClawBoard

> Observability dashboard for [OpenClaw](https://github.com/openclaw/openclaw) AI agents

**ClawBoard** gives you real-time visibility into your OpenClaw agent infrastructure — token usage, costs, cron job management, health monitoring, and guardrail alerts — all from a single web UI.

## Quick Links

- [Installation](getting-started.md)
- [Configuration](configuration.md)
- [API Reference](api-reference.md)
- [Guardrails](guardrails.md)
- [Contributing](contributing.md)

## Features at a Glance

| Feature | Description |
|---|---|
| 📊 Token Tracking | Monitor consumption by agent, model, and session type |
| 💰 Cost Estimation | Real-time cost tracking with per-model pricing |
| ⏰ Job Manager | View, trigger, and monitor scheduled agent tasks |
| 🛡️ Guardrails | Budget caps, anomaly detection, duration limits |
| 🩺 Health Monitor | Rolling-window status (Green/Amber/Red) |
| 🚨 Alerting | WhatsApp + email when things go wrong |
| 📈 Charts | Daily trends, model distribution, I/O breakdowns |
| 🔍 Inspector | Drill into individual runs with full context |

## Why ClawBoard?

OpenClaw agents run automated tasks, interact via chat, and spin up sub-agents — but there's no built-in way to see what's happening. ClawBoard fills that gap:

- **How much are my agents costing me?** → Token usage + cost estimation
- **Are my scheduled tasks running?** → Cron job monitoring with run history
- **Is something going wrong?** → Health checks + guardrail alerts
- **Which model burns the most tokens?** → Model distribution charts

## Requirements

- [OpenClaw](https://github.com/openclaw/openclaw) installed and running
- Python 3.9+
- pip

---

*ClawBoard is an open-source project. [View on GitHub](https://github.com/nzicecool/clawboard).*
