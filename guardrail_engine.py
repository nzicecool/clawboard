#!/usr/bin/env python3
"""
K3a Guardrail Engine — AI Observability & Safety

Runs health checks against all agents and interactive sessions.
Writes alerts and health status to SQLite (dashboard/data/dashboard.db).
Can be imported as a module or run standalone.
"""
import os
import json
import uuid
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

OPENCLAW_DIR = os.path.expanduser('~/.openclaw')
WORKSPACE = os.path.expanduser('~/.openclaw/workspace')
DASHBOARD_DIR = os.path.join(WORKSPACE, 'dashboard')
CRON_JOBS_FILE = os.path.join(OPENCLAW_DIR, 'cron', 'jobs.json')
CRON_RUNS_DIR = os.path.join(OPENCLAW_DIR, 'cron', 'runs')
SESSIONS_DIR = os.path.join(OPENCLAW_DIR, 'agents', 'main', 'sessions')
DATA_DIR = os.path.join(DASHBOARD_DIR, 'data')

# Legacy paths (kept for migration reference)
ALERTS_FILE = os.path.join(DATA_DIR, 'alerts.jsonl')
HEALTH_FILE = os.path.join(DATA_DIR, 'health_status.json')

# Import SQLite database module
import sys
sys.path.insert(0, DASHBOARD_DIR)
from db import get_db, db_connection, init_db, alert_fingerprint as db_fingerprint, \
    insert_alerts_with_cooldown, get_alerts, cleanup_old_alerts, \
    save_health_check, get_latest_health

# ─── Helpers ────────────────────────────────────────────────────

def load_config():
    config_path = os.path.join(DASHBOARD_DIR, 'guardrail_config.json')
    with open(config_path) as f:
        return json.load(f)


def now_utc():
    return datetime.now(timezone.utc)


def to_utc(dt_str):
    """Parse ISO timestamp to UTC datetime"""
    if dt_str.endswith('Z'):
        dt_str = dt_str[:-1] + '+00:00'
    return datetime.fromisoformat(dt_str).astimezone(timezone.utc)


def ts_ms_to_date(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000).date()


def format_cost(usd):
    return f"${usd:.4f}"


def alert_fingerprint(alert):
    """Stable hash for deduplication (delegates to db module)"""
    return db_fingerprint(alert)


def estimate_cost(input_tokens, output_tokens, cache_read, model, pricing):
    """Calculate cost from token counts"""
    p = pricing.get(model, pricing.get('default', pricing.get('glm-5.1', {})))
    inp_cost = (input_tokens / 1000) * p.get('input_per_1k', 0.001)
    out_cost = (output_tokens / 1000) * p.get('output_per_1k', 0.002)
    cache_cost = (cache_read / 1000) * p.get('cache_read_per_1k', 0.0001)
    return round(inp_cost + out_cost + cache_cost, 6)


# ─── Data Access ────────────────────────────────────────────────

def get_cron_runs():
    """Read all cron run history"""
    runs = []
    if not os.path.exists(CRON_RUNS_DIR):
        return runs
    for fname in os.listdir(CRON_RUNS_DIR):
        if not fname.endswith('.jsonl'):
            continue
        with open(os.path.join(CRON_RUNS_DIR, fname)) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    runs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return runs


def get_interactive_usage():
    """Read token usage from trajectory files (non-cron)"""
    results = []
    if not os.path.exists(SESSIONS_DIR):
        return results
    seen = set()
    for fname in os.listdir(SESSIONS_DIR):
        if not fname.endswith('.trajectory.jsonl') or '.checkpoint.' in fname:
            continue
        base = fname.split('.')[0]
        if base in seen:
            continue
        seen.add(base)
        with open(os.path.join(SESSIONS_DIR, fname)) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get('type') != 'model.completed':
                    continue
                key = d.get('sessionKey', '')
                if ':cron:' in key:
                    continue
                usage = d.get('data', {}).get('usage', {})
                if not usage or not usage.get('total'):
                    continue
                ts_str = d.get('ts', '')
                try:
                    ts_ms = int(to_utc(ts_str).timestamp() * 1000)
                except (ValueError, AttributeError):
                    continue
                results.append({
                    'ts_ms': ts_ms,
                    'session_key': key,
                    'provider': d.get('provider', 'unknown'),
                    'model': d.get('modelId', 'unknown'),
                    'input_tokens': usage.get('input', 0),
                    'output_tokens': usage.get('output', 0),
                    'cache_read': usage.get('cacheRead', 0),
                    'total_tokens': usage.get('total', 0),
                })
    return results


def classify_key(key):
    if ':whatsapp:' in key:
        return 'WhatsApp Chat'
    elif ':subagent:' in key:
        return 'Sub-Agent'
    elif key.endswith(':main') or key == 'agent:main:main':
        return 'Main Session'
    return 'Other'


# ─── Guardrail Checks ───────────────────────────────────────────

class GuardrailEngine:
    def __init__(self):
        self.config = load_config()
        self.alerts = []
        self.checks = {}
        self.cron_jobs = {}
        self._load_cron_jobs()

    def _load_cron_jobs(self):
        if os.path.exists(CRON_JOBS_FILE):
            with open(CRON_JOBS_FILE) as f:
                data = json.load(f)
            for j in data.get('jobs', []):
                self.cron_jobs[j['id']] = j.get('name', 'Unnamed')

    def _add_alert(self, severity, category, title, message, job_id=None, job_name=None, metadata=None):
        alert = {
            'id': str(uuid.uuid4())[:8],
            'timestamp': now_utc().isoformat(),
            'severity': severity,
            'category': category,
            'title': title,
            'message': message,
            'job_id': job_id,
            'job_name': job_name,
            'fingerprint': None,
            'metadata': metadata or {}
        }
        alert['fingerprint'] = alert_fingerprint(alert)
        self.alerts.append(alert)

    # --- Budget ---
    def check_budget(self):
        cfg = self.config['budget']
        pricing = cfg['pricing']
        cap = cfg['daily_cap_usd']
        warn_pct = cfg['warning_threshold_pct']
        crit_pct = cfg['critical_threshold_pct']

        today = datetime.now().date()
        today_cost = 0.0
        today_tokens = 0
        breakdown = {'cron': {'cost': 0, 'tokens': 0}, 'interactive': {'cost': 0, 'tokens': 0}}

        # Cron runs today
        for run in get_cron_runs():
            if run.get('action') not in ('finished', 'failed'):
                continue
            usage = run.get('usage', {})
            ts = run.get('runAtMs', run.get('ts', 0))
            if not ts:
                continue
            run_date = ts_ms_to_date(ts)
            if run_date != today:
                continue
            inp = usage.get('input_tokens', 0)
            out = usage.get('output_tokens', 0)
            cost = estimate_cost(inp, out, 0, 'default', pricing)
            today_cost += cost
            today_tokens += usage.get('total_tokens', 0)
            breakdown['cron']['cost'] += cost
            breakdown['cron']['tokens'] += usage.get('total_tokens', 0)

        # Interactive today
        for entry in get_interactive_usage():
            run_date = ts_ms_to_date(entry['ts_ms'])
            if run_date != today:
                continue
            cost = estimate_cost(
                entry['input_tokens'], entry['output_tokens'],
                entry['cache_read'], entry['model'], pricing
            )
            today_cost += cost
            today_tokens += entry['total_tokens']
            cat = classify_key(entry['session_key'])
            if cat not in breakdown:
                breakdown[cat] = {'cost': 0, 'tokens': 0}
            breakdown[cat]['cost'] += cost
            breakdown[cat]['tokens'] += entry['total_tokens']

        today_cost = round(today_cost, 4)
        pct = round((today_cost / cap) * 100, 1) if cap > 0 else 0

        status = 'green'
        if pct >= crit_pct:
            status = 'red'
            self._add_alert('critical', 'budget', 'Daily budget exceeded',
                           f"Spent {format_cost(today_cost)} ({pct}%) of {format_cost(cap)} daily cap",
                           metadata={'cost': today_cost, 'cap': cap, 'pct': pct, 'breakdown': breakdown})
        elif pct >= warn_pct:
            status = 'amber'
            self._add_alert('warning', 'budget', 'Approaching daily budget',
                           f"Spent {format_cost(today_cost)} ({pct}%) of {format_cost(cap)} daily cap",
                           metadata={'cost': today_cost, 'cap': cap, 'pct': pct, 'breakdown': breakdown})

        self.checks['budget'] = {
            'status': status,
            'cost_today': today_cost,
            'cap': cap,
            'pct_used': pct,
            'tokens_today': today_tokens,
            'breakdown': breakdown
        }

    # --- Consecutive Failures ---
    def check_failures(self):
        cfg = self.config['per_job']
        max_fails = cfg['max_consecutive_failures']
        job_fails = {}

        for run in get_cron_runs():
            if run.get('action') not in ('finished', 'failed'):
                continue
            job_id = run.get('jobId')
            if not job_id:
                continue
            if job_id not in job_fails:
                job_fails[job_id] = {'consecutive': 0, 'last_status': None, 'last_ts': 0}
            ts = run.get('runAtMs', run.get('ts', 0))
            if ts > job_fails[job_id]['last_ts']:
                job_fails[job_id]['last_ts'] = ts
                if run['action'] == 'failed':
                    job_fails[job_id]['consecutive'] += 1
                    job_fails[job_id]['last_status'] = 'failed'
                else:
                    job_fails[job_id]['consecutive'] = 0
                    job_fails[job_id]['last_status'] = 'ok'

        worst = 'green'
        failing_jobs = []
        for job_id, data in job_fails.items():
            if data['consecutive'] >= max_fails:
                worst = 'red'
                name = self.cron_jobs.get(job_id, job_id[:12])
                failing_jobs.append({'job_id': job_id, 'name': name, 'consecutive': data['consecutive']})
                self._add_alert('critical', 'failure', f'{name} failing',
                               f"Consecutive failures: {data['consecutive']} (threshold: {max_fails})",
                               job_id=job_id, job_name=name,
                               metadata={'consecutive': data['consecutive']})
            elif data['consecutive'] > 0 and data['consecutive'] >= max_fails - 1:
                if worst != 'red':
                    worst = 'amber'
                name = self.cron_jobs.get(job_id, job_id[:12])
                self._add_alert('warning', 'failure', f'{name} may be failing',
                               f"Consecutive failures: {data['consecutive']} (threshold: {max_fails})",
                               job_id=job_id, job_name=name,
                               metadata={'consecutive': data['consecutive']})

        self.checks['failures'] = {
            'status': worst,
            'failing_jobs': failing_jobs,
            'total_jobs': len(job_fails)
        }

    # --- Token Spike Anomaly ---
    def check_anomalies(self):
        cfg = self.config['anomaly']
        spike_mult = cfg['spike_multiplier']
        min_runs = cfg['min_runs_for_baseline']

        # Build per-job baseline from last 14 days
        now = datetime.now()
        cutoff = now - timedelta(days=14)
        job_runs = {}

        for run in get_cron_runs():
            if run.get('action') not in ('finished',):
                continue
            usage = run.get('usage', {})
            ts = run.get('runAtMs', run.get('ts', 0))
            if not ts:
                continue
            run_dt = datetime.fromtimestamp(ts / 1000)
            if run_dt < cutoff:
                continue
            job_id = run.get('jobId')
            total = usage.get('total_tokens', 0)
            if job_id not in job_runs:
                job_runs[job_id] = []
            job_runs[job_id].append({'tokens': total, 'ts': ts, 'duration': run.get('durationMs', 0)})

        anomalies = []
        worst = 'green'
        for job_id, runs in job_runs.items():
            if len(runs) < min_runs:
                continue
            tokens_list = [r['tokens'] for r in runs]
            avg = sum(tokens_list) / len(tokens_list)
            last_run = max(runs, key=lambda r: r['ts'])
            last_tokens = last_run['tokens']

            if avg > 0 and last_tokens > avg * spike_mult:
                name = self.cron_jobs.get(job_id, job_id[:12])
                pct_over = round(((last_tokens - avg) / avg) * 100, 1)
                worst = 'amber'
                anomalies.append({
                    'job_id': job_id, 'name': name,
                    'last_tokens': last_tokens, 'avg_tokens': round(avg),
                    'pct_over': pct_over
                })
                self._add_alert('warning', 'anomaly', f'Token spike: {name}',
                               f"Last run used {last_tokens:,} tokens vs avg {avg:,.0f} (+{pct_over}%)",
                               job_id=job_id, job_name=name,
                               metadata={'last': last_tokens, 'avg': round(avg), 'pct_over': pct_over})

        # Also check interactive - any single completion > max_tokens_per_run
        max_per_run = self.config['per_job']['max_tokens_per_run']
        for entry in get_interactive_usage():
            if entry['total_tokens'] > max_per_run:
                cat = classify_key(entry['session_key'])
                worst = 'amber'
                self._add_alert('warning', 'anomaly', f'Large interactive completion',
                               f"{cat}: {entry['total_tokens']:,} tokens in single completion",
                               metadata={'category': cat, 'tokens': entry['total_tokens']})

        self.checks['anomalies'] = {
            'status': worst,
            'token_spikes': anomalies
        }

    # --- Duration Anomaly ---
    def check_duration(self):
        max_duration = self.config['per_job']['max_duration_ms']
        slow_jobs = []

        for run in get_cron_runs():
            if run.get('action') not in ('finished',):
                continue
            dur = run.get('durationMs', 0)
            ts = run.get('runAtMs', run.get('ts', 0))
            if dur > max_duration and ts:
                # Only flag recent (last 24h)
                if (datetime.now().timestamp() * 1000 - ts) < 86400000:
                    job_id = run.get('jobId')
                    name = self.cron_jobs.get(job_id, job_id[:12])
                    slow_jobs.append({'name': name, 'duration_ms': dur})

        worst = 'green'
        if slow_jobs:
            worst = 'amber'
            for sj in slow_jobs:
                self._add_alert('warning', 'duration', f"Slow run: {sj['name']}",
                               f"Duration: {sj['duration_ms']/1000:.0f}s (cap: {max_duration/1000:.0f}s)",
                               metadata={'duration_ms': sj['duration_ms']})

        self.checks['duration'] = {
            'status': worst,
            'slow_jobs': slow_jobs
        }

    # --- Cache Efficiency ---
    def check_cache_efficiency(self):
        floor_pct = self.config['anomaly']['cache_efficiency_floor_pct']
        # Check interactive sessions' cache ratio
        entries = get_interactive_usage()
        total_input = sum(e['input_tokens'] for e in entries)
        total_cache = sum(e['cache_read'] for e in entries)
        ratio = (total_cache / total_input * 100) if total_input > 0 else 0

        worst = 'green'
        if total_input > 10000 and ratio < floor_pct:
            worst = 'amber'
            self._add_alert('info', 'cache', 'Low cache efficiency',
                           f"Cache read ratio: {ratio:.1f}% (floor: {floor_pct}%). Prompts may not be optimized for caching.",
                           metadata={'ratio': round(ratio, 1), 'cache_read': total_cache, 'input': total_input})

        self.checks['cache'] = {
            'status': worst,
            'cache_ratio_pct': round(ratio, 1),
            'total_cache_read': total_cache,
            'total_input': total_input
        }

    # --- Empty Results (Quality) ---
    def check_empty_results(self):
        # Check recent cron run outputs for "no new posts" patterns
        # This is a heuristic - look at the last N runs of each job
        cfg = self.config['quality']
        window = cfg['empty_result_window_days']
        threshold = cfg['empty_result_threshold_pct']

        cutoff = datetime.now() - timedelta(days=window)
        job_empty = {}
        job_total = {}

        for run in get_cron_runs():
            if run.get('action') != 'finished':
                continue
            ts = run.get('runAtMs', run.get('ts', 0))
            if not ts:
                continue
            if datetime.fromtimestamp(ts / 1000) < cutoff:
                continue
            job_id = run.get('jobId')
            if job_id not in job_total:
                job_total[job_id] = 0
                job_empty[job_id] = 0
            job_total[job_id] += 1
            # Heuristic: check if summary contains "no new" or "no relevant"
            summary = run.get('summary', '') or ''
            if any(p in summary.lower() for p in ['no new', 'no relevant', 'no posts', 'no results', 'nothing found']):
                job_empty[job_id] += 1

        worst = 'green'
        empty_jobs = []
        for job_id, total in job_total.items():
            if total < 2:
                continue
            empty_count = job_empty.get(job_id, 0)
            empty_pct = (empty_count / total) * 100
            if empty_pct >= threshold:
                name = self.cron_jobs.get(job_id, job_id[:12])
                worst = 'amber'
                empty_jobs.append({'name': name, 'empty_pct': round(empty_pct, 1), 'total': total})
                self._add_alert('info', 'quality', f'Empty results: {name}',
                               f"{empty_pct:.0f}% of last {total} runs returned no results ({window}d window)",
                               job_id=job_id, job_name=name,
                               metadata={'empty_pct': empty_pct, 'total_runs': total})

        self.checks['quality'] = {
            'status': worst,
            'empty_jobs': empty_jobs
        }

    # --- Overall Health ---
    def compute_health(self):
        status_priority = {'green': 0, 'amber': 1, 'red': 2}
        worst = 'green'
        for check in self.checks.values():
            s = check.get('status', 'green')
            if status_priority.get(s, 0) > status_priority.get(worst, 0):
                worst = s
        self.health = {
            'overall': worst,
            'last_check': now_utc().isoformat(),
            'checks': self.checks,
            'active_alerts': len([a for a in self.alerts if a['severity'] in ('critical', 'warning')]),
            'total_alerts': len(self.alerts),
            'alert_summary': {
                'critical': len([a for a in self.alerts if a['severity'] == 'critical']),
                'warning': len([a for a in self.alerts if a['severity'] == 'warning']),
                'info': len([a for a in self.alerts if a['severity'] == 'info'])
            }
        }

    # --- Persistence ---
    def save_results(self):
        os.makedirs(DATA_DIR, exist_ok=True)

        cooldown_minutes = self.config['alerts']['cooldown_minutes']

        with db_connection() as conn:
            # Save health check snapshot
            save_health_check(conn, self.health)

            # Insert alerts with cooldown deduplication
            new_count = insert_alerts_with_cooldown(conn, self.alerts, cooldown_minutes)

            # Cleanup old alerts (keep 500)
            cleanup_old_alerts(conn, 500)

        return new_count

    # --- Storage ---
    def check_storage(self):
        import shutil
        cfg = self.config.get('storage', {})
        warn_pct = cfg.get('warning_threshold_pct', 20)
        crit_pct = cfg.get('critical_threshold_pct', 10)

        # Check root filesystem
        usage = shutil.disk_usage('/')
        total_gb = round(usage.total / (1024**3), 1)
        used_gb = round(usage.used / (1024**3), 1)
        free_gb = round(usage.free / (1024**3), 1)
        used_pct = round((usage.used / usage.total) * 100, 1)
        avail_pct = round(100 - used_pct, 1)

        status = 'green'
        if avail_pct <= crit_pct:
            status = 'red'
            self._add_alert('critical', 'storage',
                'Storage Critical',
                f'Only {avail_pct}% storage remaining ({free_gb}GB free of {total_gb}GB)',
                metadata={'avail_pct': avail_pct, 'free_gb': free_gb, 'total_gb': total_gb})
        elif avail_pct <= warn_pct:
            status = 'amber'
            self._add_alert('warning', 'storage',
                'Storage Warning',
                f'Storage below {warn_pct}% — {avail_pct}% remaining ({free_gb}GB free of {total_gb}GB)',
                metadata={'avail_pct': avail_pct, 'free_gb': free_gb, 'total_gb': total_gb})

        self.checks['storage'] = {
            'status': status,
            'total_gb': total_gb,
            'used_gb': used_gb,
            'free_gb': free_gb,
            'used_pct': used_pct,
            'avail_pct': avail_pct,
            'warning_threshold_pct': warn_pct,
            'critical_threshold_pct': crit_pct
        }

    # --- Main Entry ---
    def run_all(self):
        self.check_budget()
        self.check_failures()
        self.check_anomalies()
        self.check_duration()
        self.check_cache_efficiency()
        self.check_empty_results()
        self.check_storage()
        self.compute_health()
        new_alerts = self.save_results()
        return self.health, self.alerts, new_alerts


def run_guardrails():
    """Run all guardrail checks and return results"""
    engine = GuardrailEngine()
    return engine.run_all()


if __name__ == '__main__':
    health, alerts, new_count = run_guardrails()
    print(json.dumps({
        'health': health,
        'new_alerts': new_count,
        'alerts': alerts
    }, indent=2, default=str))
