#!/usr/bin/env python3
"""ClawBoard usage ingestion v2 - ground truth from agent DB model.completed events.
Creates/updates usage_ledger table with per-call token usage + cost.
Run standalone or from app.py. Idempotent: re-runs skip already-stored events."""
import os, sqlite3, json, shutil, tempfile, datetime, re

AGENT_DB = os.path.expanduser('~/.openclaw/agents/k3achief/agent/openclaw-agent.sqlite')
CB_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'dashboard.db')
JOB_NAMES = {
    '59bd41f7': 'Memory Dreaming',
    '2bfd21c9': 'Sri Lanka Sinhala Brief',
    '4f076a8c': 'Heartbeat',
}

def category_for(session_key):
    if ':cron:' in session_key:
        for jid, name in JOB_NAMES.items():
            if jid in session_key:
                return 'job: ' + name
        return 'job: ' + session_key.split(':cron:')[1][:8]
    if 'whatsapp' in session_key:
        return 'interactive: WhatsApp'
    if session_key.endswith(':main'):
        return 'interactive: main'
    return session_key[:40]

def ingest():
    tmp = tempfile.mkdtemp(prefix='cbag_')
    dst = os.path.join(tmp, 'ag.sqlite')
    shutil.copy2(AGENT_DB, dst)
    for ext in ('-wal', '-shm'):
        if os.path.exists(AGENT_DB + ext):
            shutil.copy2(AGENT_DB + ext, dst + ext)
    src = sqlite3.connect(dst)
    cb = sqlite3.connect(CB_DB)
    cb.execute('''CREATE TABLE IF NOT EXISTS usage_ledger (
        ts TEXT, day TEXT, session_key TEXT, category TEXT, provider TEXT, model TEXT,
        input_tokens INTEGER, output_tokens INTEGER, cache_read INTEGER,
        total_tokens INTEGER, cost_usd REAL, UNIQUE(ts, session_key))''')
    rows = src.execute("select event_json from trajectory_runtime_events where event_json like '%cacheRead%'").fetchall()
    added = 0
    def find_usage(e):
        d = e.get('data') or {}
        if isinstance(d, dict):
            u = d.get('usage')
            if isinstance(u, dict) and (u.get('total') or u.get('totalTokens')):
                return u
            ms = d.get('messagesSnapshot')
            if isinstance(ms, list):
                best = None
                for m in ms:
                    mu = m.get('usage') if isinstance(m, dict) else None
                    if isinstance(mu, dict):
                        best = mu
                if best and (best.get('total') or best.get('totalTokens')):
                    return best
        return {}
    def g(u, *names):
        for n in names:
            if u.get(n):
                return u[n]
        return 0
    for (ej,) in rows:
        try:
            e = json.loads(ej)
        except Exception:
            continue
        u = find_usage(e)
        tot = u.get('total') or u.get('totalTokens')
        if not tot:
            continue
        ts = e.get('ts') or ''
        sk = e.get('sessionKey') or '?'
        c_raw = u.get('cost')
        if isinstance(c_raw, dict):
            cost = c_raw.get('total') or 0.0
        else:
            try:
                cost = float(c_raw)
            except (TypeError, ValueError):
                cost = 0.0
        c_raw = u.get('cost')
        if isinstance(c_raw, dict):
            cost = c_raw.get('total') or 0.0
        else:
            try:
                cost = float(c_raw)
            except (TypeError, ValueError):
                cost = 0.0
        try:
            cb.execute('INSERT OR IGNORE INTO usage_ledger VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (ts, ts[:10], sk, category_for(sk), e.get('provider') or '?', e.get('modelId') or '?',
                 g(u, 'input', 'inputTokens'), g(u, 'output', 'outputTokens'), g(u, 'cacheRead'),
                 tot, cost))
            added += 1
        except Exception:
            pass
    cb.commit()
    n = cb.execute('select count(*) from usage_ledger').fetchone()[0]
    sums = cb.execute('select sum(total_tokens), sum(cost_usd) from usage_ledger').fetchone()
    src.close(); cb.close(); shutil.rmtree(tmp, ignore_errors=True)
    print('ledger rows:', n, '| attempted:', added, '| total tokens:', sums[0], '| total cost: $%.2f' % (sums[1] or 0))
    return n

if __name__ == '__main__':
    ingest()
