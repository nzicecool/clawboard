#!/usr/bin/env python3
"""
SQLite database layer for OpenClaw Dashboard.

Tables:
  - alerts: Guardrail alert history
  - health_checks: Snapshots of health check results
  - token_usage: Token usage entries per job/run
  - interactive_usage: Token usage from non-cron sessions
"""

import os
import json
import sqlite3
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import contextmanager

DB_DIR = os.path.join(os.path.dirname(__file__), 'data')
DB_PATH = os.path.join(DB_DIR, 'dashboard.db')


def get_db():
    """Get a connection to the SQLite database."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db_connection():
    """Context manager for database connections."""
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize the database schema."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = get_db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS alerts (
                id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                job_id TEXT,
                job_name TEXT,
                metadata TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_alerts_fingerprint ON alerts(fingerprint);
            CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts(timestamp);
            CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
            CREATE INDEX IF NOT EXISTS idx_alerts_category ON alerts(category);

            CREATE TABLE IF NOT EXISTS health_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                overall TEXT NOT NULL DEFAULT 'unknown',
                checks_json TEXT NOT NULL DEFAULT '{}',
                active_alerts INTEGER DEFAULT 0,
                total_alerts INTEGER DEFAULT 0,
                alert_summary_json TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_health_timestamp ON health_checks(timestamp);

            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp_ms INTEGER NOT NULL,
                run_datetime TEXT NOT NULL,
                job_id TEXT NOT NULL,
                job_name TEXT NOT NULL,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                session_id TEXT,
                session_key TEXT,
                input_text TEXT,
                output_text TEXT,
                provider TEXT DEFAULT 'unknown',
                model TEXT DEFAULT 'unknown',
                cache_read INTEGER DEFAULT 0,
                duration_ms INTEGER DEFAULT 0,
                UNIQUE(job_id, timestamp_ms)
            );

            CREATE INDEX IF NOT EXISTS idx_token_usage_job ON token_usage(job_id);
            CREATE INDEX IF NOT EXISTS idx_token_usage_date ON token_usage(run_datetime);
            CREATE INDEX IF NOT EXISTS idx_token_usage_timestamp ON token_usage(timestamp_ms);

            CREATE TABLE IF NOT EXISTS interactive_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp_ms INTEGER NOT NULL,
                session_key TEXT NOT NULL,
                category TEXT DEFAULT 'Other',
                provider TEXT DEFAULT 'unknown',
                model TEXT DEFAULT 'unknown',
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cache_read INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_interactive_ts ON interactive_usage(timestamp_ms);
            CREATE INDEX IF NOT EXISTS idx_interactive_category ON interactive_usage(category);
            CREATE INDEX IF NOT EXISTS idx_interactive_session ON interactive_usage(session_key);
        """)
        conn.commit()
    finally:
        conn.close()


# ─── Alert Operations ───────────────────────────────────────────

def alert_fingerprint(alert):
    """Stable hash for deduplication."""
    raw = f"{alert.get('category', '')}:{alert.get('job_id', '')}:{alert.get('title', '')}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def insert_alert(conn, alert):
    """Insert a single alert. Returns True if inserted, False if duplicate."""
    fp = alert.get('fingerprint') or alert_fingerprint(alert)
    aid = alert.get('id') or str(uuid.uuid4())[:8]
    metadata = alert.get('metadata', {})
    if isinstance(metadata, dict):
        metadata = json.dumps(metadata)

    try:
        conn.execute(
            """INSERT OR IGNORE INTO alerts
               (id, fingerprint, timestamp, severity, category, title, message, job_id, job_name, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (aid, fp, alert.get('timestamp', ''), alert.get('severity', 'info'),
             alert.get('category', ''), alert.get('title', ''), alert.get('message', ''),
             alert.get('job_id'), alert.get('job_name'), metadata)
        )
        return conn.total_changes > 0
    except sqlite3.IntegrityError:
        return False


def insert_alerts_with_cooldown(conn, new_alerts, cooldown_minutes=60):
    """Insert alerts, respecting cooldown for duplicate fingerprints."""
    now = datetime.now(timezone.utc)
    new_count = 0

    for alert in new_alerts:
        fp = alert.get('fingerprint') or alert_fingerprint(alert)
        # Check if a recent alert with this fingerprint exists
        row = conn.execute(
            "SELECT timestamp FROM alerts WHERE fingerprint = ? ORDER BY timestamp DESC LIMIT 1",
            (fp,)
        ).fetchone()

        if row:
            try:
                last_ts = row['timestamp']
                if last_ts.endswith('Z'):
                    last_ts = last_ts[:-1] + '+00:00'
                last_dt = datetime.fromisoformat(last_ts).astimezone(timezone.utc)
                if (now - last_dt) < timedelta(minutes=cooldown_minutes):
                    continue  # Still in cooldown
            except (ValueError, AttributeError):
                pass

        if insert_alert(conn, alert):
            new_count += 1

    return new_count


def get_alerts(conn, severity=None, category=None, limit=100):
    """Get alerts with optional filtering."""
    query = "SELECT * FROM alerts WHERE 1=1"
    params = []

    if severity:
        query += " AND severity = ?"
        params.append(severity)
    if category:
        query += " AND category = ?"
        params.append(category)

    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        try:
            d['metadata'] = json.loads(d.get('metadata', '{}'))
        except (json.JSONDecodeError, TypeError):
            pass
        results.append(d)
    return results


def cleanup_old_alerts(conn, keep_count=500):
    """Keep only the most recent N alerts."""
    conn.execute(
        "DELETE FROM alerts WHERE id NOT IN (SELECT id FROM alerts ORDER BY timestamp DESC LIMIT ?)",
        (keep_count,)
    )


# ─── Health Check Operations ────────────────────────────────────

def save_health_check(conn, health_data):
    """Save a health check snapshot."""
    checks_json = json.dumps(health_data.get('checks', {}), default=str)
    alert_summary = json.dumps(health_data.get('alert_summary', {}), default=str)

    conn.execute(
        """INSERT INTO health_checks (timestamp, overall, checks_json, active_alerts, total_alerts, alert_summary_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (health_data.get('last_check', ''), health_data.get('overall', 'unknown'),
         checks_json, health_data.get('active_alerts', 0),
         health_data.get('total_alerts', 0), alert_summary)
    )


def get_latest_health(conn):
    """Get the most recent health check."""
    row = conn.execute(
        "SELECT * FROM health_checks ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()

    if not row:
        return None

    d = dict(row)
    try:
        d['checks'] = json.loads(d.pop('checks_json', '{}'))
    except (json.JSONDecodeError, TypeError):
        d['checks'] = {}
    try:
        d['alert_summary'] = json.loads(d.pop('alert_summary_json', '{}'))
    except (json.JSONDecodeError, TypeError):
        d['alert_summary'] = {}

    # Map to match old format
    d['last_check'] = d['timestamp']
    return d


# ─── Token Usage Operations ─────────────────────────────────────

def save_token_entry(conn, job_id, job_name, input_tokens, output_tokens,
                     total_tokens, run_at_ms, session_id=None, session_key=None,
                     input_text=None, output_text=None, provider='unknown',
                     model='unknown', cache_read=0, duration_ms=0):
    """Save a single token usage entry. Skips duplicates."""
    run_dt = datetime.fromtimestamp(run_at_ms / 1000).strftime('%Y-%m-%dT%H:%M:%S')

    try:
        conn.execute(
            """INSERT OR IGNORE INTO token_usage
               (timestamp_ms, run_datetime, job_id, job_name, input_tokens, output_tokens,
                total_tokens, session_id, session_key, input_text, output_text,
                provider, model, cache_read, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_at_ms, run_dt, job_id, job_name, input_tokens, output_tokens,
             total_tokens, session_id, session_key, input_text, output_text,
             provider, model, cache_read, duration_ms)
        )
        return True
    except sqlite3.IntegrityError:
        return False


def get_token_usage_aggregated(conn, now_ms=None):
    """Get aggregated token usage data, matching the old API format."""
    if not now_ms:
        now_ms = int(datetime.now().timestamp() * 1000)

    day_ms = 86400000
    week_ms = day_ms * 7

    usage_data = {
        'total': {'total_tokens': 0, 'input_tokens': 0, 'output_tokens': 0,
                  'total_runs': 0, 'estimated_cost': 0.0},
        'by_job': {},
        'by_model': {},
        'by_provider': {},
        'by_date': {},
        'by_day': {
            'today': {'total_tokens': 0, 'input_tokens': 0, 'output_tokens': 0, 'runs': 0},
            'week': {'total_tokens': 0, 'input_tokens': 0, 'output_tokens': 0, 'runs': 0},
            'older_than_week': {'total_tokens': 0, 'input_tokens': 0, 'output_tokens': 0, 'runs': 0}
        },
        'daily_trends': [],
        'interactive_total': {'total_tokens': 0, 'input_tokens': 0, 'output_tokens': 0, 'runs': 0},
        'by_category': {}
    }

    # Cron token usage
    rows = conn.execute("SELECT * FROM token_usage WHERE total_tokens > 0").fetchall()
    for row in rows:
        total_tokens = row['total_tokens']
        input_tokens = row['input_tokens']
        output_tokens = row['output_tokens']
        job_id = row['job_id']
        job_name = row['job_name']
        model = row['model']
        provider = row['provider']
        run_at = row['timestamp_ms']

        # Total
        usage_data['total']['total_tokens'] += total_tokens
        usage_data['total']['input_tokens'] += input_tokens
        usage_data['total']['output_tokens'] += output_tokens
        usage_data['total']['total_runs'] += 1

        # By job
        if job_id not in usage_data['by_job']:
            usage_data['by_job'][job_id] = {
                'job_id': job_id, 'name': job_name,
                'total_tokens': 0, 'input_tokens': 0, 'output_tokens': 0,
                'runs': 0, 'avg_tokens': 0
            }
        usage_data['by_job'][job_id]['total_tokens'] += total_tokens
        usage_data['by_job'][job_id]['input_tokens'] += input_tokens
        usage_data['by_job'][job_id]['output_tokens'] += output_tokens
        usage_data['by_job'][job_id]['runs'] += 1

        # By model
        if model not in usage_data['by_model']:
            usage_data['by_model'][model] = {'total_tokens': 0, 'input_tokens': 0, 'output_tokens': 0, 'runs': 0}
        usage_data['by_model'][model]['total_tokens'] += total_tokens
        usage_data['by_model'][model]['input_tokens'] += input_tokens
        usage_data['by_model'][model]['output_tokens'] += output_tokens
        usage_data['by_model'][model]['runs'] += 1

        # By provider
        if provider not in usage_data['by_provider']:
            usage_data['by_provider'][provider] = {'total_tokens': 0, 'runs': 0}
        usage_data['by_provider'][provider]['total_tokens'] += total_tokens
        usage_data['by_provider'][provider]['runs'] += 1

        # By date
        run_date = datetime.fromtimestamp(run_at / 1000).date().strftime('%Y-%m-%d')
        if run_date not in usage_data['by_date']:
            usage_data['by_date'][run_date] = {'date': run_date, 'total_tokens': 0, 'input_tokens': 0, 'output_tokens': 0, 'runs': 0}
        usage_data['by_date'][run_date]['total_tokens'] += total_tokens
        usage_data['by_date'][run_date]['input_tokens'] += input_tokens
        usage_data['by_date'][run_date]['output_tokens'] += output_tokens
        usage_data['by_date'][run_date]['runs'] += 1

        # Time buckets
        time_diff = now_ms - run_at
        if time_diff < day_ms:
            usage_data['by_day']['today']['total_tokens'] += total_tokens
            usage_data['by_day']['today']['input_tokens'] += input_tokens
            usage_data['by_day']['today']['output_tokens'] += output_tokens
            usage_data['by_day']['today']['runs'] += 1
        if time_diff < week_ms:
            usage_data['by_day']['week']['total_tokens'] += total_tokens
            usage_data['by_day']['week']['input_tokens'] += input_tokens
            usage_data['by_day']['week']['output_tokens'] += output_tokens
            usage_data['by_day']['week']['runs'] += 1
        if time_diff >= week_ms:
            usage_data['by_day']['older_than_week']['total_tokens'] += total_tokens
            usage_data['by_day']['older_than_week']['input_tokens'] += input_tokens
            usage_data['by_day']['older_than_week']['output_tokens'] += output_tokens
            usage_data['by_day']['older_than_week']['runs'] += 1

    # Interactive token usage
    int_rows = conn.execute("SELECT * FROM interactive_usage WHERE total_tokens > 0").fetchall()
    for row in int_rows:
        ts_ms = row['timestamp_ms']
        cat = row['category']
        total_t = row['total_tokens']
        input_t = row['input_tokens']
        output_t = row['output_tokens']
        model = row['model']
        provider = row['provider']

        usage_data['total']['total_tokens'] += total_t
        usage_data['total']['input_tokens'] += input_t
        usage_data['total']['output_tokens'] += output_t
        usage_data['total']['total_runs'] += 1

        # Interactive total
        usage_data['interactive_total']['total_tokens'] += total_t
        usage_data['interactive_total']['input_tokens'] += input_t
        usage_data['interactive_total']['output_tokens'] += output_t
        usage_data['interactive_total']['runs'] += 1

        # By category
        if cat not in usage_data['by_category']:
            usage_data['by_category'][cat] = {'total_tokens': 0, 'input_tokens': 0, 'output_tokens': 0, 'runs': 0}
        usage_data['by_category'][cat]['total_tokens'] += total_t
        usage_data['by_category'][cat]['input_tokens'] += input_t
        usage_data['by_category'][cat]['output_tokens'] += output_t
        usage_data['by_category'][cat]['runs'] += 1

        # By model
        if model not in usage_data['by_model']:
            usage_data['by_model'][model] = {'total_tokens': 0, 'input_tokens': 0, 'output_tokens': 0, 'runs': 0}
        usage_data['by_model'][model]['total_tokens'] += total_t
        usage_data['by_model'][model]['input_tokens'] += input_t
        usage_data['by_model'][model]['output_tokens'] += output_t
        usage_data['by_model'][model]['runs'] += 1

        # By provider
        if provider not in usage_data['by_provider']:
            usage_data['by_provider'][provider] = {'total_tokens': 0, 'runs': 0}
        usage_data['by_provider'][provider]['total_tokens'] += total_t
        usage_data['by_provider'][provider]['runs'] += 1

        # By date
        try:
            run_date = datetime.fromtimestamp(ts_ms / 1000).date().strftime('%Y-%m-%d')
            if run_date not in usage_data['by_date']:
                usage_data['by_date'][run_date] = {'date': run_date, 'total_tokens': 0, 'input_tokens': 0, 'output_tokens': 0, 'runs': 0}
            usage_data['by_date'][run_date]['total_tokens'] += total_t
            usage_data['by_date'][run_date]['input_tokens'] += input_t
            usage_data['by_date'][run_date]['output_tokens'] += output_t
            usage_data['by_date'][run_date]['runs'] += 1
        except Exception:
            pass

        # Time buckets
        time_diff = now_ms - ts_ms
        if time_diff < day_ms:
            usage_data['by_day']['today']['total_tokens'] += total_t
            usage_data['by_day']['today']['input_tokens'] += input_t
            usage_data['by_day']['today']['output_tokens'] += output_t
            usage_data['by_day']['today']['runs'] += 1
        if time_diff < week_ms:
            usage_data['by_day']['week']['total_tokens'] += total_t
            usage_data['by_day']['week']['input_tokens'] += input_t
            usage_data['by_day']['week']['output_tokens'] += output_t
            usage_data['by_day']['week']['runs'] += 1
        if time_diff >= week_ms:
            usage_data['by_day']['older_than_week']['total_tokens'] += total_t
            usage_data['by_day']['older_than_week']['input_tokens'] += input_t
            usage_data['by_day']['older_than_week']['output_tokens'] += output_t
            usage_data['by_day']['older_than_week']['runs'] += 1

    # Calculate averages and sort
    for job_id, job_data in usage_data['by_job'].items():
        if job_data['runs'] > 0:
            job_data['avg_tokens'] = job_data['total_tokens'] // job_data['runs']

    usage_data['by_job'] = sorted(usage_data['by_job'].values(), key=lambda x: x['total_tokens'], reverse=True)
    usage_data['daily_trends'] = sorted(usage_data['by_date'].values(), key=lambda x: x['date'])

    # Estimate cost
    PRICING = {
        'glm-4.7': {'input_per_1k': 0.001, 'output_per_1k': 0.002},
        'gemini-pro': {'input_per_1k': 0.0005, 'output_per_1k': 0.0015},
        'default': {'input_per_1k': 0.001, 'output_per_1k': 0.002}
    }
    total_cost = 0.0
    for model, model_data in usage_data['by_model'].items():
        pricing = PRICING.get(model, PRICING['default'])
        input_cost = (model_data['input_tokens'] / 1000) * pricing['input_per_1k']
        output_cost = (model_data['output_tokens'] / 1000) * pricing['output_per_1k']
        total_cost += input_cost + output_cost
    usage_data['total']['estimated_cost'] = round(total_cost, 4)

    return usage_data


def get_token_usage_by_job_and_date(conn, job_id, date):
    """Get token usage for a specific job on a specific date."""
    rows = conn.execute(
        """SELECT * FROM token_usage
           WHERE job_id = ? AND run_datetime LIKE ?
           ORDER BY timestamp_ms DESC""",
        (job_id, f'{date}%')
    ).fetchall()
    return [dict(r) for r in rows]


def cleanup_old_token_data(conn, days=30):
    """Remove token usage older than N days."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S')
    conn.execute("DELETE FROM token_usage WHERE run_datetime < ?", (cutoff,))
    conn.execute("DELETE FROM interactive_usage WHERE datetime(timestamp_ms/1000, 'unixepoch') < ?", (cutoff,))


# ─── Interactive Usage ──────────────────────────────────────────

def save_interactive_entry(conn, ts_ms, session_key, category, provider,
                           model, input_tokens, output_tokens, cache_read, total_tokens):
    """Save an interactive usage entry."""
    conn.execute(
        """INSERT INTO interactive_usage
           (timestamp_ms, session_key, category, provider, model, input_tokens,
            output_tokens, cache_read, total_tokens)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ts_ms, session_key, category, provider, model, input_tokens,
         output_tokens, cache_read, total_tokens)
    )


# ─── Backup ─────────────────────────────────────────────────────

def backup_database(backup_dir=None):
    """Create a timestamped backup of the SQLite database."""
    if not backup_dir:
        backup_dir = '/mnt/myusb/dashboard-backups'
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(backup_dir, f'dashboard_{timestamp}.db')

    conn = get_db()
    try:
        conn.execute(f"VACUUM INTO '{backup_path}'")
    finally:
        conn.close()

    # Keep only last 8 weekly backups (2 months)
    backups = sorted(Path(backup_dir).glob('dashboard_*.db'))
    for old in backups[:-8]:
        old.unlink()

    return backup_path


# ─── Initialize on import ──────────────────────────────────────

init_db()
