#!/usr/bin/env python3
"""
Migrate existing JSON data files to SQLite database.

Run once: python3 migrate_to_sqlite.py
"""

import os
import json
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from db import get_db, db_connection, init_db, insert_alert, save_health_check, save_token_entry

DASHBOARD_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(DASHBOARD_DIR, 'data')
ALERTS_FILE = os.path.join(DATA_DIR, 'alerts.jsonl')
HEALTH_FILE = os.path.join(DATA_DIR, 'health_status.json')
TOKEN_DATA_DIR = '/media/pi/F53E-517D1/tokens'


def migrate_alerts():
    """Migrate alerts.jsonl to SQLite."""
    if not os.path.exists(ALERTS_FILE):
        print("No alerts file to migrate.")
        return 0

    count = 0
    with db_connection() as conn:
        with open(ALERTS_FILE, 'r') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    alert = json.loads(line)
                    if insert_alert(conn, alert):
                        count += 1
                except json.JSONDecodeError:
                    continue

    print(f"Migrated {count} alerts to SQLite.")
    return count


def migrate_health():
    """Migrate health_status.json to SQLite."""
    if not os.path.exists(HEALTH_FILE):
        print("No health file to migrate.")
        return

    with open(HEALTH_FILE, 'r') as f:
        health = json.load(f)

    with db_connection() as conn:
        save_health_check(conn, health)

    print("Migrated latest health check to SQLite.")


def migrate_token_files():
    """Migrate token JSON files from USB drive to SQLite."""
    if not os.path.exists(TOKEN_DATA_DIR):
        print(f"Token data directory not found: {TOKEN_DATA_DIR}")
        return 0

    count = 0
    with db_connection() as conn:
        for filename in sorted(os.listdir(TOKEN_DATA_DIR)):
            if not filename.startswith('tokens-') or not filename.endswith('.json'):
                continue

            filepath = os.path.join(TOKEN_DATA_DIR, filename)
            try:
                with open(filepath, 'r') as f:
                    entries = json.load(f)

                for entry in entries:
                    save_token_entry(
                        conn,
                        job_id=entry.get('job_id', 'unknown'),
                        job_name=entry.get('job_name', 'Unknown'),
                        input_tokens=entry.get('input_tokens', 0),
                        output_tokens=entry.get('output_tokens', 0),
                        total_tokens=entry.get('total_tokens', 0),
                        run_at_ms=entry.get('timestamp', 0),
                        session_id=entry.get('session_id'),
                        session_key=entry.get('session_key'),
                        input_text=entry.get('input_text'),
                        output_text=entry.get('output_text')
                    )
                    count += 1

            except (json.JSONDecodeError, IOError) as e:
                print(f"Error reading {filename}: {e}")
                continue

    print(f"Migrated {count} token usage entries to SQLite.")
    return count


def main():
    print("=" * 50)
    print("Dashboard Data Migration: JSON → SQLite")
    print("=" * 50)

    # Initialize DB
    init_db()
    print("✓ Database initialized")

    # Migrate alerts
    print("\nMigrating alerts...")
    alert_count = migrate_alerts()

    # Migrate health
    print("\nMigrating health checks...")
    migrate_health()

    # Migrate token files
    print("\nMigrating token usage files...")
    token_count = migrate_token_files()

    print("\n" + "=" * 50)
    print(f"Migration complete!")
    print(f"  Alerts: {alert_count}")
    print(f"  Token entries: {token_count}")
    print(f"\nDatabase: {os.path.join(DATA_DIR, 'dashboard.db')}")
    print("=" * 50)


if __name__ == '__main__':
    main()
