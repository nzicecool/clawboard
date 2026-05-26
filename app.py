#!/usr/bin/env python3
"""
OpenClaw Dashboard - Web UI for managing scheduled agents, cron jobs, and skills
"""
import os
import json
import subprocess
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request
import sys
sys.path.insert(0, os.path.dirname(__file__))
from guardrail_engine import run_guardrails, DATA_DIR
from db import (get_db, db_connection, init_db, get_alerts as db_get_alerts,
                get_latest_health, save_token_entry, get_token_usage_aggregated,
                get_token_usage_by_job_and_date, cleanup_old_token_data,
                save_interactive_entry, backup_database)

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# OpenClaw paths
OPENCLAW_DIR = os.path.expanduser('~/.openclaw')
WORKSPACE = os.path.expanduser('~/.openclaw/workspace')
SKILLS_DIR = f"{WORKSPACE}/skills"
CRON_JOBS_FILE = f"{OPENCLAW_DIR}/cron/jobs.json"
CRON_RUNS_DIR = f"{OPENCLAW_DIR}/cron/runs"
AGENTS_DIR = f"{OPENCLAW_DIR}/agents"
SESSIONS_DIR = f"{OPENCLAW_DIR}/agents/main/sessions"

# Initialize database on startup
init_db()


def ingest_cron_token_data():
    """Read all cron run files and populate token_usage table."""
    if not os.path.exists(CRON_RUNS_DIR):
        return 0

    # Load job names
    jobs_by_id = {}
    try:
        with open(CRON_JOBS_FILE, 'r') as f:
            data = json.load(f)
        for job in data.get('jobs', []):
            jobs_by_id[job['id']] = job.get('name', 'Unknown')
    except Exception:
        pass

    count = 0
    for fname in os.listdir(CRON_RUNS_DIR):
        if not fname.endswith('.jsonl'):
            continue
        job_id = fname.replace('.jsonl', '')
        job_name = jobs_by_id.get(job_id, job_id[:12])

        try:
            with open(os.path.join(CRON_RUNS_DIR, fname), 'r') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        run = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if run.get('action') != 'finished':
                        continue

                    usage = run.get('usage', {})
                    if not usage:
                        continue

                    total_tokens = usage.get('total') or usage.get('total_tokens', 0)
                    if not total_tokens:
                        continue

                    run_at_ms = run.get('runAtMs', run.get('ts', 0))
                    if not run_at_ms:
                        continue

                    session_id = run.get('sessionId', '')
                    model = run.get('model', 'unknown')
                    provider = run.get('provider', 'unknown')
                    duration_ms = run.get('durationMs', 0)
                    cache_read = usage.get('cacheRead', 0)
                    input_tokens = usage.get('input', 0) or usage.get('input_tokens', 0)
                    output_tokens = usage.get('output', 0) or usage.get('output_tokens', 0)

                    saved = save_token_data(
                        job_id, job_name,
                        input_tokens, output_tokens,
                        total_tokens,
                        run_at_ms,
                        session_id=session_id,
                        provider=provider, model=model,
                        cache_read=cache_read,
                        duration_ms=duration_ms
                    )
                    if saved:
                        count += 1
        except Exception as e:
            print(f"Error ingesting cron runs for {job_id}: {e}")

    return count


def ingest_interactive_token_data():
    """Read trajectory files for non-cron sessions and populate interactive_usage table."""
    results = get_interactive_token_usage()
    if not results:
        return 0

    count = 0
    with db_connection() as conn:
        for entry in results:
            try:
                save_interactive_entry(
                    conn,
                    entry['ts_ms'],
                    entry['session_key'],
                    entry['category'],
                    entry['provider'],
                    entry['model'],
                    entry['input_tokens'],
                    entry['output_tokens'],
                    entry['cache_read'],
                    entry['total_tokens']
                )
                count += 1
            except Exception as e:
                print(f"Error saving interactive entry: {e}")

    return count


def run_full_ingestion():
    """Run full ingestion from cron runs + interactive sessions."""
    cron_count = ingest_cron_token_data()
    interactive_count = ingest_interactive_token_data()
    print(f"Ingestion complete: {cron_count} cron entries, {interactive_count} interactive entries")
    return cron_count, interactive_count


# Ingestion will run after all function definitions are loaded
_STARTUP_INGEST = True

def classify_session_key(session_key):
    """Classify a sessionKey into a human-readable category"""
    if not session_key:
        return 'Unknown'
    if ':cron:' in session_key:
        return 'Scheduled Task'
    elif ':whatsapp:' in session_key:
        return 'WhatsApp Chat'
    elif ':subagent:' in session_key:
        return 'Sub-Agent'
    elif session_key.endswith(':main') or session_key == 'agent:main:main':
        return 'Main Session'
    else:
        return 'Other'

def extract_session_label(session_key):
    """Extract a short label from sessionKey for display"""
    if not session_key:
        return 'Unknown Session'
    parts = session_key.split(':')
    if ':whatsapp:' in session_key:
        return 'WhatsApp Chat'
    elif ':subagent:' in session_key:
        return f'Sub-Agent ({parts[-1][:8]}...)'
    elif session_key.endswith(':main') or session_key == 'agent:main:main':
        return 'Main Session'
    return session_key[-40:]

def get_interactive_token_usage():
    """Extract token usage from trajectory files for non-cron sessions"""
    # Run startup ingestion on first call
    global _STARTUP_INGEST
    if _STARTUP_INGEST:
        _STARTUP_INGEST = False
        try:
            run_full_ingestion()
        except Exception as e:
            print(f"Startup ingestion error: {e}")

    results = []
    if not os.path.exists(SESSIONS_DIR):
        return results

    seen_sessions = set()

    for fname in os.listdir(SESSIONS_DIR):
        if not fname.endswith('.trajectory.jsonl'):
            continue
        if '.checkpoint.' in fname:
            continue

        base_name = fname.split('.')[0]
        if base_name in seen_sessions:
            continue
        seen_sessions.add(base_name)

        fpath = os.path.join(SESSIONS_DIR, fname)
        try:
            with open(fpath, 'r') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if d.get('type') != 'model.completed':
                        continue

                    session_key = d.get('sessionKey', '')
                    if ':cron:' in session_key:
                        continue

                    usage = d.get('data', {}).get('usage', {})
                    if not usage or not usage.get('total'):
                        continue

                    ts_str = d.get('ts', '')
                    try:
                        ts_ms = int(datetime.fromisoformat(ts_str.replace('Z', '+00:00')).timestamp() * 1000)
                    except (ValueError, AttributeError):
                        continue

                    results.append({
                        'ts_ms': ts_ms,
                        'session_key': session_key,
                        'category': classify_session_key(session_key),
                        'label': extract_session_label(session_key),
                        'provider': d.get('provider', 'unknown'),
                        'model': d.get('modelId', 'unknown'),
                        'input_tokens': usage.get('input', 0),
                        'output_tokens': usage.get('output', 0),
                        'cache_read': usage.get('cacheRead', 0),
                        'total_tokens': usage.get('total', 0),
                    })
        except Exception as e:
            print(f"Error reading trajectory {fname}: {e}")
            continue

    return results

def extract_session_text(session_id):
    """Extract input and output text from a session file"""
    try:
        session_file = os.path.join(SESSIONS_DIR, f'{session_id}.jsonl')
        if not os.path.exists(session_file):
            return {'input_text': None, 'output_text': None, 'session_key': None}

        input_text = None
        output_text = None
        session_key = None

        with open(session_file, 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get('type') == 'session':
                        session_key = entry.get('id')
                    elif entry.get('type') == 'message':
                        message = entry.get('message', {})
                        if not input_text and message.get('role') == 'user':
                            # Extract text from user message
                            content = message.get('content', [])
                            if content and isinstance(content, list) and len(content) > 0:
                                text_parts = []
                                for item in content:
                                    if isinstance(item, dict) and item.get('type') == 'text':
                                        text = item.get('text', '')
                                        if text:
                                            text_parts.append(text)
                                input_text = '\n\n'.join(text_parts) if text_parts else None
                        elif not output_text and message.get('role') == 'assistant' and input_text:
                            # Extract text from assistant response
                            content = message.get('content', [])
                            if content and isinstance(content, list) and len(content) > 0:
                                text_parts = []
                                for item in content:
                                    if isinstance(item, dict) and item.get('type') == 'text':
                                        text = item.get('text', '')
                                        if text:
                                            text_parts.append(text)
                                output_text = '\n\n'.join(text_parts) if text_parts else None
                                # Break after getting output
                                break
                except json.JSONDecodeError:
                    continue

        return {
            'input_text': truncate_text(input_text, 1000),
            'output_text': truncate_text(output_text, 1000),
            'session_key': session_key
        }
    except Exception as e:
        print(f"Error extracting session text: {e}")
        return {'input_text': None, 'output_text': None, 'session_key': None}

def truncate_text(text, max_length):
    """Truncate text to max_length and add ellipsis if needed"""
    if not text:
        return None
    if len(text) <= max_length:
        return text
    return text[:max_length] + '... [truncated]'

def save_token_data(job_id, job_name, input_tokens, output_tokens, total_tokens, run_at_ms, session_id=None, provider='unknown', model='unknown', cache_read=0, duration_ms=0):
    """Save token data to SQLite database"""
    try:
        # Extract session text if session_id provided
        session_info = {}
        if session_id:
            session_info = extract_session_text(session_id)

        with db_connection() as conn:
            save_token_entry(
                conn, job_id, job_name, input_tokens, output_tokens,
                total_tokens, run_at_ms,
                session_id=session_id,
                session_key=session_info.get('session_key'),
                input_text=session_info.get('input_text'),
                output_text=session_info.get('output_text'),
                provider=provider,
                model=model,
                cache_read=cache_read,
                duration_ms=duration_ms
            )
        return True
    except Exception as e:
        print(f"Error saving token data: {e}")
        return False

def cleanup_old_token_files():
    """Remove old token data from SQLite (older than 30 days)"""
    try:
        with db_connection() as conn:
            cleanup_old_token_data(conn, days=30)
    except Exception as e:
        print(f"Error cleaning up token data: {e}")

def run_openclaw_command(args, timeout=10):
    """Run OpenClaw CLI commands and return JSON output"""
    openclaw_bin = os.path.expanduser('~/.npm-global/bin/openclaw')
    cmd = [openclaw_bin] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {'raw': result.stdout, 'error': None}
        else:
            return {'error': result.stderr, 'stdout': result.stdout}
    except subprocess.TimeoutExpired:
        return {'error': 'Command timed out'}
    except Exception as e:
        return {'error': str(e)}


import urllib.request

def gateway_api(path, timeout=5):
    """Call the OpenClaw gateway API directly (faster than CLI)"""
    gateway_port = 18789
    url = f'http://127.0.0.1:{gateway_port}{path}'
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {'error': str(e)}

def get_skills_list():
    """Get list of available skills"""
    skills = []
    if not os.path.exists(SKILLS_DIR):
        return skills

    for skill_name in os.listdir(SKILLS_DIR):
        skill_path = os.path.join(SKILLS_DIR, skill_name)
        skill_md = os.path.join(skill_path, 'SKILL.md')

        if os.path.isdir(skill_path) and os.path.exists(skill_md):
            # Read skill description
            description = ""
            try:
                with open(skill_md, 'r') as f:
                    first_lines = f.readlines(10)
                    # Look for description line (typically line 2-5)
                    for line in first_lines:
                        if line.strip().startswith('description:'):
                            description = line.split('description:', 1)[1].strip()
                            break
                        elif line.strip().startswith('## Purpose') or line.strip().startswith('## Description'):
                            # Read the next few lines for description
                            continue
            except Exception:
                pass

            skills.append({
                'name': skill_name,
                'path': skill_path,
                'description': description or skill_name
            })

    return sorted(skills, key=lambda x: x['name'])

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('index.html')

@app.route('/token-usage')
def token_usage():
    """Token usage dashboard page"""
    return render_template('token-usage.html')

@app.route('/api/cron-jobs')
def api_cron_jobs():
    """Get all cron jobs"""
    try:
        with open(CRON_JOBS_FILE, 'r') as f:
            data = json.load(f)
        return jsonify(data)
    except FileNotFoundError:
        return jsonify({'error': 'Cron jobs file not found', 'jobs': []}), 404
    except Exception as e:
        return jsonify({'error': str(e), 'jobs': []}), 500

@app.route('/api/cron-jobs/<job_id>')
def api_cron_job_detail(job_id):
    """Get details of a specific cron job"""
    runs_file = os.path.join(CRON_RUNS_DIR, f'{job_id}.jsonl')
    try:
        runs = []
        with open(runs_file, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        run = json.loads(line)
                        runs.append(run)
                    except json.JSONDecodeError:
                        pass
        # Sort by startedAtMs descending (newest first)
        runs.sort(key=lambda x: x.get('startedAtMs', 0), reverse=True)
        return jsonify({'jobId': job_id, 'runs': runs})
    except FileNotFoundError:
        return jsonify({'jobId': job_id, 'runs': []})
    except Exception as e:
        return jsonify({'error': str(e), 'runs': []})

@app.route('/api/cron-jobs/<job_id>/run', methods=['POST'])
def api_cron_job_run(job_id):
    """Trigger a cron job to run immediately"""
    result = run_openclaw_command(['cron', 'action=run', f'jobId={job_id}'])

    if result.get('error'):
        return jsonify({'error': result['error'], 'message': 'Failed to trigger job via CLI. Use OpenClaw CLI directly or try again later.'}), 500

    return jsonify(result)

@app.route('/api/skills')
def api_skills():
    """Get list of available skills"""
    return jsonify({'skills': get_skills_list()})

@app.route('/api/skills/<skill_name>')
def api_skill_detail(skill_name):
    """Get details of a specific skill"""
    skill_path = os.path.join(SKILLS_DIR, skill_name, 'SKILL.md')

    if not os.path.exists(skill_path):
        return jsonify({'error': 'Skill not found'}), 404

    try:
        with open(skill_path, 'r') as f:
            content = f.read()

        return jsonify({
            'name': skill_name,
            'path': skill_path,
            'content': content
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/status')
def api_status():
    """Get OpenClaw system status"""
    # Fast health check via gateway
    try:
        import urllib.request
        with urllib.request.urlopen('http://127.0.0.1:18789/health', timeout=3) as resp:
            health = json.loads(resp.read().decode())
        return jsonify({
            'status': 'online' if health.get('ok') else 'degraded',
            'health': health,
            'version': openclaw_version()
        })
    except Exception as e:
        return jsonify({'status': 'unknown', 'error': str(e)})

@app.route('/api/sessions')
def api_sessions():
    """Get list of sessions via gateway API"""
    result = gateway_api('/v1/sessions')
    if 'error' in result:
        # Try listing session dirs as fallback
        try:
            sessions = []
            agents_dir = os.path.expanduser('~/.openclaw/agents/main/sessions')
            if os.path.isdir(agents_dir):
                for d in os.listdir(agents_dir):
                    p = os.path.join(agents_dir, d)
                    if os.path.isdir(p):
                        sessions.append({'id': d, 'path': p})
            return jsonify({'sessions': sessions})
        except Exception:
            return jsonify({'sessions': [], 'error': result['error']})
    return jsonify(result)


def openclaw_version():
    """Get OpenClaw version from package.json"""
    try:
        pkg = os.path.expanduser('~/.npm-global/lib/node_modules/openclaw/package.json')
        with open(pkg) as f:
            return json.load(f).get('version', 'unknown')
    except Exception:
        return 'unknown'

@app.route('/api/website-health')
def api_website_health():
    """Get website health monitoring status"""
    import json
    from pathlib import Path

    # Read website health status file
    status_file = Path(f"{WORKSPACE}/skills/website-health-monitor/data/status.json")
    
    try:
        with open(status_file, 'r') as f:
            data = json.load(f)
            return jsonify(data)
    except FileNotFoundError:
        return jsonify({'error': 'No website health data found', 'websites': []})
    except Exception as e:
        return jsonify({'error': str(e), 'websites': []})

@app.route('/api/running-jobs')
def api_running_jobs():
    """Get currently running jobs"""
    try:
        # Load cron jobs
        with open(CRON_JOBS_FILE, 'r') as f:
            jobs_data = json.load(f)
        
        running_jobs = []
        now_ms = int(datetime.now().timestamp() * 1000)
        
        for job in jobs_data.get('jobs', []):
            # Check if job is enabled
            if not job.get('enabled', False):
                continue
                
            # Get recent runs for this job
            runs_file = os.path.join(CRON_RUNS_DIR, f'{job["id"]}.jsonl')
            
            if not os.path.exists(runs_file):
                continue
                
            try:
                with open(runs_file, 'r') as f:
                    lines = f.readlines()
                    
                    if len(lines) == 0:
                        continue
                        
                    # Get last few lines to check for running status
                    recent_lines = lines[-5:] if len(lines) >= 5 else lines
                    
                    for line in reversed(recent_lines):
                        if not line.strip():
                            continue
                            
                        try:
                            run = json.loads(line)
                            
                            # Check if this run started recently but hasn't finished
                            if run.get('action') == 'started':
                                started_at = run.get('ts', run.get('startedAtMs', 0))
                                
                                # If started within last 30 minutes and no corresponding "finished" or "failed"
                                time_since_start = now_ms - started_at
                                if 0 < time_since_start < 1800000:  # Less than 30 minutes ago
                                    # Check if there's a finish record after this start
                                    has_finish = False
                                    for check_line in lines:
                                        try:
                                            check_run = json.loads(check_line)
                                            if check_run.get('ts', 0) > started_at:
                                                if check_run.get('action') in ['finished', 'failed']:
                                                    has_finish = True
                                                    break
                                        except:
                                            continue
                                    
                                    if not has_finish:
                                        running_jobs.append({
                                            'jobId': job['id'],
                                            'name': job.get('name', 'Unnamed Job'),
                                            'sessionKey': run.get('sessionKey', ''),
                                            'sessionId': run.get('sessionId', ''),
                                            'startedAtMs': started_at,
                                            'elapsedMs': time_since_start,
                                            'model': run.get('model', 'unknown'),
                                            'provider': run.get('provider', 'unknown')
                                        })
                                        break
                                        
                        except json.JSONDecodeError:
                            continue
                            
            except Exception:
                continue
        
        # Sort by start time (most recent first)
        running_jobs.sort(key=lambda x: x.get('startedAtMs', 0), reverse=True)
        
        return jsonify({
            'count': len(running_jobs),
            'jobs': running_jobs,
            'timestamp': now_ms
        })
        
    except FileNotFoundError:
        return jsonify({'count': 0, 'jobs': [], 'timestamp': now_ms})
    except Exception as e:
        return jsonify({'error': str(e), 'count': 0, 'jobs': [], 'timestamp': now_ms})

@app.route('/api/token-usage')
def api_token_usage():
    """Get aggregated token usage data from SQLite"""
    try:
        # Re-ingest latest data before serving
        try:
            run_full_ingestion()
        except Exception:
            pass

        cleanup_old_token_files()

        now_ms = int(datetime.now().timestamp() * 1000)

        with db_connection() as conn:
            usage_data = get_token_usage_aggregated(conn, now_ms)

        return jsonify(usage_data)

    except Exception as e:
        return jsonify({'error': str(e), 'total': {'total_tokens': 0}})

@app.route('/health')
def health_page():
    """Health & Observability dashboard page"""
    return render_template('health.html')

@app.route('/api/health')
def api_health():
    """Get current health status from SQLite"""
    try:
        with db_connection() as conn:
            health = get_latest_health(conn)
        if health:
            return jsonify(health)
        else:
            health, _, _ = run_guardrails()
            return jsonify(health)
    except Exception as e:
        return jsonify({'error': str(e), 'overall': 'unknown'})

@app.route('/api/health/refresh')
def api_health_refresh():
    """Force refresh health checks"""
    try:
        health, alerts, new_count = run_guardrails()
        return jsonify({'health': health, 'new_alerts': new_count, 'alert_count': len(alerts)})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/alerts')
def api_alerts():
    """Get alert history from SQLite"""
    try:
        severity_filter = request.args.get('severity')
        category_filter = request.args.get('category')
        limit = int(request.args.get('limit', 100))

        with db_connection() as conn:
            alerts = db_get_alerts(conn, severity=severity_filter, category=category_filter, limit=limit)

        return jsonify({'alerts': alerts, 'total': len(alerts)})
    except Exception as e:
        return jsonify({'error': str(e), 'alerts': []})

@app.route('/api/guardrail-config')
def api_guardrail_config():
    """Get current guardrail configuration"""
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'guardrail_config.json')
        with open(config_path) as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/guardrail-config', methods=['POST'])
def api_guardrail_config_update():
    """Update guardrail configuration"""
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'guardrail_config.json')
        with open(config_path) as f:
            current = json.load(f)
        updates = request.json
        # Deep merge
        def deep_merge(base, override):
            for k, v in override.items():
                if isinstance(v, dict) and isinstance(base.get(k), dict):
                    deep_merge(base[k], v)
                else:
                    base[k] = v
        deep_merge(current, updates)
        with open(config_path, 'w') as f:
            json.dump(current, f, indent=2)
        return jsonify({'status': 'updated', 'config': current})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.template_filter('datetime')
def datetime_filter(timestamp_ms):
    """Convert millisecond timestamp to readable datetime"""
    if not timestamp_ms:
        return 'N/A'
    try:
        dt = datetime.fromtimestamp(timestamp_ms / 1000)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return 'Invalid'

@app.template_filter('from_now')
def from_now_filter(timestamp_ms):
    """Convert millisecond timestamp to relative time"""
    if not timestamp_ms:
        return 'N/A'
    try:
        dt = datetime.fromtimestamp(timestamp_ms / 1000)
        delta = datetime.now() - dt
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, _ = divmod(remainder, 60)

        if days > 0:
            return f'{days}d ago'
        elif hours > 0:
            return f'{hours}h ago'
        elif minutes > 0:
            return f'{minutes}m ago'
        else:
            return 'Just now'
    except:
        return 'Invalid'

@app.template_filter('duration')
def duration_filter(ms):
    """Convert milliseconds to readable duration"""
    if not ms:
        return 'N/A'
    seconds = ms / 1000
    if seconds < 60:
        return f'{seconds:.1f}s'
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f'{minutes}m {secs}s'

@app.route('/api/storage')
def api_storage():
    """Get current storage usage"""
    import shutil
    try:
        usage = shutil.disk_usage('/')
        total_gb = round(usage.total / (1024**3), 1)
        used_gb = round(usage.used / (1024**3), 1)
        free_gb = round(usage.free / (1024**3), 1)
        used_pct = round((usage.used / usage.total) * 100, 1)
        avail_pct = round(100 - used_pct, 1)

        # Check if guardrail health has storage status
        storage_check = None
        try:
            with db_connection() as conn:
                health = get_latest_health(conn)
            if health and 'checks' in health:
                storage_check = health['checks'].get('storage')
        except Exception:
            pass

        return jsonify({
            'total_gb': total_gb,
            'used_gb': used_gb,
            'free_gb': free_gb,
            'used_pct': used_pct,
            'avail_pct': avail_pct,
            'status': storage_check.get('status', 'green') if storage_check else ('red' if avail_pct < 10 else 'amber' if avail_pct < 20 else 'green')
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/token-usage/<job_id>/<date>')
def api_token_usage_detail(job_id, date):
    """Get token usage details for a specific job on a specific date from SQLite"""
    try:
        with db_connection() as conn:
            entries = get_token_usage_by_job_and_date(conn, job_id, date)
        return jsonify({'job_id': job_id, 'date': date, 'entries': entries, 'total_entries': len(entries)})
    except Exception as e:
        return jsonify({'error': str(e), 'entries': []})

if __name__ == '__main__':
    # Run on all interfaces, port 5000
    app.run(host='0.0.0.0', port=5000, debug=False)
