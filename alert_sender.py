#!/usr/bin/env python3
"""
K3a Guardrail Alert Sender

Runs guardrail checks and sends alerts via email (AgentMail) and WhatsApp (cron wake).
Designed to be called from a cron job.
"""
import os
import sys
import json
from datetime import datetime

# Add dashboard dir to path
DASHBOARD_DIR = os.path.expanduser('~/.openclaw/workspace/dashboard')
sys.path.insert(0, DASHBOARD_DIR)

from guardrail_engine import run_guardrails


def send_alert_email(alerts, health):
    """Send alert email via AgentMail"""
    try:
        from agentmail import AgentMail
        from dotenv import load_dotenv
        load_dotenv(os.path.expanduser('~/.openclaw/.env'))
        
        client = AgentMail(api_key=os.getenv('AGENTMAIL_API_KEY'))
        inbox_id = 'notifications@zined.lk'
        
        # Filter to alertable severities
        config_path = os.path.join(DASHBOARD_DIR, 'guardrail_config.json')
        with open(config_path) as f:
            config = json.load(f)
        
        alert_severities = config.get('alerts', {}).get('severities_to_alert', ['critical', 'warning'])
        to_email = config.get('alerts', {}).get('email', 'kanchanaw@senathltd.com')
        
        filtered = [a for a in alerts if a['severity'] in alert_severities]
        if not filtered:
            return False
        
        # Build email
        overall = health.get('overall', 'unknown').upper()
        subject = f"[K3a Guardrail] {overall} — {len(filtered)} alert(s)"
        
        html = f"""
        <html><body style="font-family: sans-serif; background: #111827; color: #f3f4f6; padding: 20px;">
        <div style="max-width: 600px; margin: auto;">
            <h2 style="color: {'#ef4444' if overall == 'RED' else '#f59e0b' if overall == 'AMBER' else '#22c55e'};">
                K3a Guardrail Alert — {overall}
            </h2>
            <p>{datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</p>
            <hr style="border-color: #374151;">
        """
        
        for a in filtered:
            sev_colors = {'critical': '#ef4444', 'warning': '#f59e0b', 'info': '#3b82f6'}
            color = sev_colors.get(a['severity'], '#6b7280')
            html += f"""
            <div style="background: #1f2937; border-left: 4px solid {color}; padding: 12px; margin: 12px 0; border-radius: 6px;">
                <div style="color: {color}; font-weight: bold;">{a['severity'].upper()}: {a['title']}</div>
                <p style="color: #d1d5db; font-size: 14px; margin: 8px 0 0 0;">{a['message']}</p>
                {'<p style="color: #9ca3af; font-size: 12px;">Agent: ' + a['job_name'] + '</p>' if a.get('job_name') else ''}
            </div>
            """
        
        # Budget summary
        budget = health.get('checks', {}).get('budget', {})
        html += f"""
            <hr style="border-color: #374151;">
            <h3 style="color: #9ca3af;">Budget Status</h3>
            <p style="color: #f3f4f6;">Spent: ${budget.get('cost_today', 0):.4f} / ${budget.get('cap', 10):.2f} ({budget.get('pct_used', 0):.1f}%)</p>
            <p style="color: #6b7280; font-size: 12px; margin-top: 20px;">
                K3a Guardrail Engine · <a href="http://192.168.0.104:5000/health" style="color: #3b82f6;">Open Dashboard</a>
            </p>
        </div></body></html>
        """
        
        client.inboxes.messages.send(
            inbox_id=inbox_id,
            to=[{"email": to_email}],
            subject=subject,
            html=html,
            text=f"K3a Guardrail: {overall}. {len(filtered)} alerts. See dashboard: http://192.168.0.104:5000/health"
        )
        return True
    except Exception as e:
        print(f"Email alert failed: {e}")
        return False


def format_whatsapp_alert(alerts, health):
    """Format alerts for WhatsApp notification"""
    config_path = os.path.join(DASHBOARD_DIR, 'guardrail_config.json')
    with open(config_path) as f:
        config = json.load(f)
    
    alert_severities = config.get('alerts', {}).get('severities_to_alert', ['critical', 'warning'])
    filtered = [a for a in alerts if a['severity'] in alert_severities]
    
    if not filtered:
        return None
    
    overall = health.get('overall', 'unknown')
    emoji = {'green': '🟢', 'amber': '🟡', 'red': '🔴'}.get(overall, '⚪')
    
    lines = [f"{emoji} *K3a Guardrail Alert*\n"]
    
    for a in filtered[:5]:  # Max 5 alerts in WhatsApp
        sev_emoji = {'critical': '🚨', 'warning': '⚠️', 'info': 'ℹ️'}.get(a['severity'], '•')
        lines.append(f"{sev_emoji} *{a['title']}*")
        lines.append(f"   {a['message']}")
        if a.get('job_name'):
            lines.append(f"   _Agent: {a['job_name']}_")
        lines.append("")
    
    if len(filtered) > 5:
        lines.append(f"... and {len(filtered) - 5} more alerts")
    
    budget = health.get('checks', {}).get('budget', {})
    lines.append(f"\n💰 Budget: ${budget.get('cost_today', 0):.2f}/${budget.get('cap', 10):.0f} ({budget.get('pct_used', 0):.1f}%)")
    
    return '\n'.join(lines)


if __name__ == '__main__':
    health, alerts, new_count = run_guardrails()
    
    print(f"Health: {health['overall']}, New alerts: {new_count}, Total: {len(alerts)}")
    
    if new_count > 0 and health['overall'] != 'green':
        # Send email
        email_ok = send_alert_email(alerts, health)
        print(f"Email: {'sent' if email_ok else 'failed/skipped'}")
        
        # Output WhatsApp message for the cron job to pick up
        wa_msg = format_whatsapp_alert(alerts, health)
        if wa_msg:
            print(f"\n--- WHATSAPP_MESSAGE ---\n{wa_msg}\n--- END ---")
    else:
        print("No actionable alerts. All clear.")
