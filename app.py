#!/usr/bin/env python3
"""
OpenClaw Dashboard - Web UI for managing scheduled agents, cron jobs, and skills
"""
import os
import json
import subprocess
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# OpenClaw paths
OPENCLAW_DIR = os.path.expanduser('~/.openclaw')
WORKSPACE = os.path.expanduser('~/.openclaw/workspace')
SKILLS_DIR = f"{WORKSPACE}/skills"
CRON_JOBS_FILE = f"{OPENCLAW_DIR}/cron/jobs.json"
CRON_RUNS_DIR = f"{OPENCLAW_DIR}/cron/runs"
AGENTS_DIR = f"{OPENCLAW_DIR}/agents"

def run_openclaw_command(args):
    """Run OpenClaw CLI commands and return JSON output"""
    cmd = ['openclaw'] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
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
    result = run_openclaw_command(['status'])
    return jsonify(result)

@app.route('/api/sessions')
def api_sessions():
    """Get list of sessions"""
    result = run_openclaw_command(['sessions', 'action=list'])
    return jsonify(result)

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

if __name__ == '__main__':
    # Run on all interfaces, port 5000
    app.run(host='0.0.0.0', port=5000, debug=True)
