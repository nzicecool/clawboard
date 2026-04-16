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
TOKEN_DATA_DIR = '/media/pi/F53E-517D1/tokens'

def save_token_data(job_id, job_name, input_tokens, output_tokens, total_tokens, run_at_ms):
    """Save token data to daily JSON file"""
    try:
        run_date = datetime.fromtimestamp(run_at_ms / 1000).date()
        date_str = run_date.strftime('%Y-%m-%d')
        filename = os.path.join(TOKEN_DATA_DIR, f'tokens-{date_str}.json')

        # Load existing data for this date
        existing_data = []
        if os.path.exists(filename):
            try:
                with open(filename, 'r') as f:
                    existing_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                existing_data = []

        # Add new entry
        new_entry = {
            'timestamp': run_at_ms,
            'datetime': datetime.fromtimestamp(run_at_ms / 1000).isoformat(),
            'job_id': job_id,
            'job_name': job_name,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'total_tokens': total_tokens
        }

        existing_data.append(new_entry)

        # Save to file
        with open(filename, 'w') as f:
            json.dump(existing_data, f, indent=2)

        return True
    except Exception as e:
        print(f"Error saving token data: {e}")
        return False

def cleanup_old_token_files():
    """Remove token files older than 7 days"""
    try:
        if not os.path.exists(TOKEN_DATA_DIR):
            return

        now = datetime.now()
        cutoff_date = now - timedelta(days=7)

        for filename in os.listdir(TOKEN_DATA_DIR):
            if not filename.startswith('tokens-') or not filename.endswith('.json'):
                continue

            filepath = os.path.join(TOKEN_DATA_DIR, filename)
            # Extract date from filename
            try:
                date_str = filename.replace('tokens-', '').replace('.json', '')
                file_date = datetime.strptime(date_str, '%Y-%m-%d')

                # Remove if older than 7 days
                if file_date < cutoff_date:
                    os.remove(filepath)
                    print(f"Removed old token file: {filename}")
            except ValueError:
                # Invalid date format, skip
                continue
    except Exception as e:
        print(f"Error cleaning up token files: {e}")

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

@app.route('/api/token-usage')
def api_token_usage():
    """Get aggregated token usage data"""
    try:
        # Cleanup old token files (older than 7 days)
        cleanup_old_token_files()

        # Load cron jobs
        with open(CRON_JOBS_FILE, 'r') as f:
            jobs_data = json.load(f)

        now_ms = int(datetime.now().timestamp() * 1000)
        day_ms = 86400000  # 24 hours in milliseconds
        
        # Initialize aggregations
        usage_data = {
            'total': {
                'total_tokens': 0,
                'input_tokens': 0,
                'output_tokens': 0,
                'total_runs': 0,
                'estimated_cost': 0.0
            },
            'by_job': {},
            'by_model': {},
            'by_provider': {},
            'by_date': {},
            'by_day': {
                'today': {'total_tokens': 0, 'input_tokens': 0, 'output_tokens': 0, 'runs': 0},
                'week': {'total_tokens': 0, 'input_tokens': 0, 'output_tokens': 0, 'runs': 0},
                'month': {'total_tokens': 0, 'input_tokens': 0, 'output_tokens': 0, 'runs': 0}
            },
            'daily_trends': []
        }
        
        # Process each job's runs
        for job in jobs_data.get('jobs', []):
            job_id = job['id']
            job_name = job.get('name', 'Unnamed Job')
            
            runs_file = os.path.join(CRON_RUNS_DIR, f'{job_id}.jsonl')
            
            if not os.path.exists(runs_file):
                continue
            
            try:
                with open(runs_file, 'r') as f:
                    for line in f:
                        if not line.strip():
                            continue
                        
                        try:
                            run = json.loads(line)
                            
                            # Only process finished/failed runs with usage data
                            if run.get('action') not in ['finished', 'failed']:
                                continue
                            
                            usage = run.get('usage', {})
                            if not usage or 'total_tokens' not in usage:
                                continue
                            
                            run_at = run.get('runAtMs', run.get('ts', 0))
                            if not run_at:
                                continue
                            
                            # Extract token values
                            total_tokens = usage.get('total_tokens', 0)
                            input_tokens = usage.get('input_tokens', 0)
                            output_tokens = usage.get('output_tokens', 0)
                            model = run.get('model', 'unknown')
                            provider = run.get('provider', 'unknown')

                            # Skip runs with zero tokens
                            if total_tokens == 0:
                                continue

                            # Save token data to disk (today's runs only)
                            time_diff = now_ms - run_at
                            day_ms = 86400000  # 24 hours
                            if time_diff < day_ms:
                                save_token_data(job_id, job_name, input_tokens, output_tokens, total_tokens, run_at)

                            # Total aggregations
                            usage_data['total']['total_tokens'] += total_tokens
                            usage_data['total']['input_tokens'] += input_tokens
                            usage_data['total']['output_tokens'] += output_tokens
                            usage_data['total']['total_runs'] += 1
                            
                            # By job
                            if job_id not in usage_data['by_job']:
                                usage_data['by_job'][job_id] = {
                                    'job_id': job_id,
                                    'name': job_name,
                                    'total_tokens': 0,
                                    'input_tokens': 0,
                                    'output_tokens': 0,
                                    'runs': 0,
                                    'avg_tokens': 0
                                }
                            usage_data['by_job'][job_id]['total_tokens'] += total_tokens
                            usage_data['by_job'][job_id]['input_tokens'] += input_tokens
                            usage_data['by_job'][job_id]['output_tokens'] += output_tokens
                            usage_data['by_job'][job_id]['runs'] += 1
                            
                            # By model
                            if model not in usage_data['by_model']:
                                usage_data['by_model'][model] = {
                                    'total_tokens': 0,
                                    'input_tokens': 0,
                                    'output_tokens': 0,
                                    'runs': 0
                                }
                            usage_data['by_model'][model]['total_tokens'] += total_tokens
                            usage_data['by_model'][model]['input_tokens'] += input_tokens
                            usage_data['by_model'][model]['output_tokens'] += output_tokens
                            usage_data['by_model'][model]['runs'] += 1
                            
                            # By provider
                            if provider not in usage_data['by_provider']:
                                usage_data['by_provider'][provider] = {
                                    'total_tokens': 0,
                                    'runs': 0
                                }
                            usage_data['by_provider'][provider]['total_tokens'] += total_tokens
                            usage_data['by_provider'][provider]['runs'] += 1
                            
                            # By date (daily trends)
                            run_date = datetime.fromtimestamp(run_at / 1000).date()
                            date_str = run_date.strftime('%Y-%m-%d')
                            
                            if date_str not in usage_data['by_date']:
                                usage_data['by_date'][date_str] = {
                                    'date': date_str,
                                    'total_tokens': 0,
                                    'input_tokens': 0,
                                    'output_tokens': 0,
                                    'runs': 0
                                }
                            usage_data['by_date'][date_str]['total_tokens'] += total_tokens
                            usage_data['by_date'][date_str]['input_tokens'] += input_tokens
                            usage_data['by_date'][date_str]['output_tokens'] += output_tokens
                            usage_data['by_date'][date_str]['runs'] += 1
                            
                            # Time-based aggregations
                            time_diff = now_ms - run_at
                            
                            # Today (last 24 hours)
                            if time_diff < day_ms:
                                usage_data['by_day']['today']['total_tokens'] += total_tokens
                                usage_data['by_day']['today']['input_tokens'] += input_tokens
                                usage_data['by_day']['today']['output_tokens'] += output_tokens
                                usage_data['by_day']['today']['runs'] += 1
                            
                            # Week (last 7 days)
                            if time_diff < day_ms * 7:
                                usage_data['by_day']['week']['total_tokens'] += total_tokens
                                usage_data['by_day']['week']['input_tokens'] += input_tokens
                                usage_data['by_day']['week']['output_tokens'] += output_tokens
                                usage_data['by_day']['week']['runs'] += 1
                            
                            # Month (last 30 days)
                            if time_diff < day_ms * 30:
                                usage_data['by_day']['month']['total_tokens'] += total_tokens
                                usage_data['by_day']['month']['input_tokens'] += input_tokens
                                usage_data['by_day']['month']['output_tokens'] += output_tokens
                                usage_data['by_day']['month']['runs'] += 1
                            
                        except json.JSONDecodeError:
                            continue
                            
            except Exception:
                continue
        
        # Calculate averages
        for job_id, job_data in usage_data['by_job'].items():
            if job_data['runs'] > 0:
                job_data['avg_tokens'] = job_data['total_tokens'] // job_data['runs']
        
        # Sort by total tokens (descending)
        usage_data['by_job'] = sorted(
            usage_data['by_job'].values(),
            key=lambda x: x['total_tokens'],
            reverse=True
        )
        
        # Sort daily trends by date
        usage_data['daily_trends'] = sorted(
            usage_data['by_date'].values(),
            key=lambda x: x['date']
        )
        
        # Calculate estimated cost (simplified pricing)
        # Note: These are example prices - adjust based on actual pricing
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
        
        return jsonify(usage_data)
        
    except FileNotFoundError:
        return jsonify({'error': 'No token usage data found', 'total': {'total_tokens': 0}})
    except Exception as e:
        return jsonify({'error': str(e), 'total': {'total_tokens': 0}})

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

@app.route('/api/token-usage/<job_id>/<date>')
def api_token_usage_detail(job_id, date):
    """Get token usage details for a specific job on a specific date"""
    try:
        filename = os.path.join(TOKEN_DATA_DIR, f'tokens-{date}.json')

        if not os.path.exists(filename):
            return jsonify({'error': 'No token data for this date', 'entries': []})

        with open(filename, 'r') as f:
            all_entries = json.load(f)

        # Filter by job_id
        job_entries = [entry for entry in all_entries if entry['job_id'] == job_id]

        # Sort by timestamp descending (newest first)
        job_entries.sort(key=lambda x: x['timestamp'], reverse=True)

        return jsonify({
            'job_id': job_id,
            'date': date,
            'entries': job_entries,
            'total_entries': len(job_entries)
        })

    except Exception as e:
        return jsonify({'error': str(e), 'entries': []})

if __name__ == '__main__':
    # Run on all interfaces, port 5000
    app.run(host='0.0.0.0', port=5000, debug=True)
