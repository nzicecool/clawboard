# API Reference

## Token Usage

### `GET /api/token-usage`

Returns aggregated token usage data across all agents and sessions.

**Response:**

```json
{
  "total": {
    "total_tokens": 65718827,
    "input_tokens": 52000000,
    "output_tokens": 13718827,
    "total_runs": 394,
    "estimated_cost": 9.51
  },
  "by_job": [
    {
      "job_id": "abc123",
      "name": "Daily News Summary",
      "total_tokens": 250000,
      "input_tokens": 200000,
      "output_tokens": 50000,
      "runs": 5,
      "avg_tokens": 50000
    }
  ],
  "by_model": {
    "glm-5.1": {
      "total_tokens": 65718827,
      "input_tokens": 52000000,
      "output_tokens": 13718827,
      "runs": 394
    }
  },
  "by_date": {
    "2026-05-08": {
      "date": "2026-05-08",
      "total_tokens": 6975478,
      "input_tokens": 5500000,
      "output_tokens": 1475478,
      "runs": 39
    }
  },
  "by_day": {
    "today": { "total_tokens": 6975478, "runs": 39 },
    "week": { "total_tokens": 50000000, "runs": 200 },
    "older_than_week": { "total_tokens": 15718827, "runs": 194 }
  },
  "daily_trends": [
    { "date": "2026-05-08", "total_tokens": 6975478, "input_tokens": 5500000, "output_tokens": 1475478, "runs": 39 }
  ],
  "interactive_total": {
    "total_tokens": 64407616,
    "runs": 384
  },
  "by_category": {
    "WhatsApp Chat": { "total_tokens": 54067668, "runs": 242 },
    "Main Session": { "total_tokens": 40725048, "runs": 294 }
  }
}
```

### `GET /api/token-usage/:job_id/:date`

Get detailed token entries for a specific job on a specific date.

**Parameters:**
- `job_id` — Cron job ID
- `date` — Date in `YYYY-MM-DD` format

**Response:**

```json
{
  "job_id": "abc123",
  "date": "2026-05-08",
  "entries": [
    {
      "timestamp_ms": 1775893800000,
      "run_datetime": "2026-05-08T08:30:00",
      "job_name": "Daily News Summary",
      "input_tokens": 45000,
      "output_tokens": 3500,
      "total_tokens": 48500,
      "model": "glm-5.1",
      "provider": "zai",
      "duration_ms": 45000,
      "input_text": "...",
      "output_text": "..."
    }
  ]
}
```

## Cron Jobs

### `GET /api/cron-jobs`

List all registered cron jobs.

### `GET /api/cron-jobs/:job_id`

Get run history for a specific job.

### `POST /api/cron-jobs/:job_id/run`

Trigger a job to run immediately.

## Health & Alerts

### `GET /api/health`

Current health status.

### `POST /api/health/refresh`

Force a health check refresh.

### `GET /api/alerts`

Alert history with optional filters.

**Query Parameters:**
- `severity` — Filter by severity (`info`, `warning`, `critical`)
- `category` — Filter by category (e.g., `budget`, `anomaly`, `failure`)
- `limit` — Maximum results (default: 100)

### `GET /api/guardrail-config`

Get current guardrail configuration.

### `POST /api/guardrail-config`

Update guardrail configuration (live, no restart needed).

## Skills

### `GET /api/skills`

List all available OpenClaw skills.

### `GET /api/skills/:name`

Get details for a specific skill.

## System

### `GET /api/status`

OpenClaw system status.

### `GET /api/sessions`

List all active sessions.
