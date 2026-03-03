"""
SmartSched AI v2 – Database Models (Extended)
===============================================
SQLite-based persistent storage extended with:
  - Business decision fields (profit, penalty, client priority)
  - Risk fields (reliability scores, maintenance flags)
  - Governance fields (job lock, material availability, preemption)
  - New tables: schedule_checkpoints, schedule_versions,
                audit_log, optimizer_settings, approval_queue
"""

import sqlite3
import csv
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "smartsched.db"
DATA_DIR = DB_PATH.parent / "data"


def get_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # better concurrency
    return conn


def init_db():
    """Initialize / migrate all tables."""
    conn = get_connection()
    cur = conn.cursor()

    cur.executescript("""
    -- ================================================================
    -- JOBS
    -- ================================================================
    CREATE TABLE IF NOT EXISTS jobs (
        id                   TEXT PRIMARY KEY,
        name                 TEXT NOT NULL,
        processing_time      REAL NOT NULL,
        due_date             TEXT NOT NULL,
        priority             INTEGER NOT NULL DEFAULT 3,
        required_machine_type TEXT NOT NULL,
        required_worker_skill TEXT NOT NULL,
        precedence           TEXT DEFAULT NULL,
        status               TEXT DEFAULT 'pending',
        urgency_score        REAL DEFAULT 0,
        created_at           TEXT DEFAULT (datetime('now')),

        -- Business Decision Layer
        profit_margin        REAL DEFAULT 0.0,
        delay_penalty        REAL DEFAULT 0.0,
        client_priority      INTEGER DEFAULT 3,
        contractual          INTEGER DEFAULT 0,
        reputation_risk      REAL DEFAULT 0.0,

        -- Governance
        job_lock_status      INTEGER DEFAULT 0,
        locked_by            TEXT DEFAULT NULL,
        locked_at            TEXT DEFAULT NULL,

        -- Material & Preemption
        material_available   INTEGER DEFAULT 1,
        is_preemptable       INTEGER DEFAULT 0,
        preempted_at         REAL DEFAULT NULL,
        completion_pct       REAL DEFAULT 0.0
    );

    -- ================================================================
    -- MACHINES
    -- ================================================================
    CREATE TABLE IF NOT EXISTS machines (
        id                   TEXT PRIMARY KEY,
        name                 TEXT NOT NULL,
        machine_type         TEXT NOT NULL,
        status               TEXT DEFAULT 'available',
        daily_capacity       REAL DEFAULT 8.0,
        current_workload     REAL DEFAULT 0.0,
        location             TEXT DEFAULT '',
        notes                TEXT DEFAULT '',

        -- Risk
        reliability_score    REAL DEFAULT 1.0,
        maintenance_due      INTEGER DEFAULT 0,
        overload_threshold   REAL DEFAULT 90.0,
        last_maintained_at   TEXT DEFAULT NULL
    );

    -- ================================================================
    -- WORKERS
    -- ================================================================
    CREATE TABLE IF NOT EXISTS workers (
        id                   TEXT PRIMARY KEY,
        name                 TEXT NOT NULL,
        skills               TEXT NOT NULL,
        shift_start          REAL DEFAULT 8.0,
        shift_end            REAL DEFAULT 16.0,
        on_leave             INTEGER DEFAULT 0,
        assigned_hours       REAL DEFAULT 0.0,
        department           TEXT DEFAULT '',

        -- Risk
        reliability_score    REAL DEFAULT 1.0,
        overtime_eligible    INTEGER DEFAULT 0
    );

    -- ================================================================
    -- SCHEDULE
    -- ================================================================
    CREATE TABLE IF NOT EXISTS schedule (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id       TEXT NOT NULL,
        machine_id   TEXT NOT NULL,
        worker_id    TEXT NOT NULL,
        start_time   REAL NOT NULL,
        end_time     REAL NOT NULL,
        day          INTEGER DEFAULT 1,
        status       TEXT DEFAULT 'scheduled',
        created_at   TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(job_id)     REFERENCES jobs(id),
        FOREIGN KEY(machine_id) REFERENCES machines(id),
        FOREIGN KEY(worker_id)  REFERENCES workers(id)
    );

    -- ================================================================
    -- DISRUPTIONS
    -- ================================================================
    CREATE TABLE IF NOT EXISTS disruptions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        type         TEXT NOT NULL,
        entity_id    TEXT NOT NULL,
        description  TEXT,
        occurred_at  TEXT DEFAULT (datetime('now')),
        resolved     INTEGER DEFAULT 0,
        resolved_at  TEXT DEFAULT NULL
    );

    -- ================================================================
    -- SCHEDULE CHECKPOINTS (versioning)
    -- ================================================================
    CREATE TABLE IF NOT EXISTS schedule_checkpoints (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        version_no   INTEGER NOT NULL,
        description  TEXT DEFAULT '',
        snapshot     TEXT NOT NULL,        -- JSON serialized schedule state
        created_at   TEXT DEFAULT (datetime('now')),
        is_active    INTEGER DEFAULT 1
    );

    -- ================================================================
    -- AUDIT LOG (governance)
    -- ================================================================
    CREATE TABLE IF NOT EXISTS audit_log (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        action       TEXT NOT NULL,
        entity_type  TEXT NOT NULL,
        entity_id    TEXT NOT NULL,
        performed_by TEXT DEFAULT 'system',
        details      TEXT DEFAULT '',
        occurred_at  TEXT DEFAULT (datetime('now'))
    );

    -- ================================================================
    -- OPTIMIZER SETTINGS (admin-configurable weights)
    -- ================================================================
    CREATE TABLE IF NOT EXISTS optimizer_settings (
        key          TEXT PRIMARY KEY,
        value        REAL NOT NULL,
        description  TEXT DEFAULT '',
        updated_at   TEXT DEFAULT (datetime('now'))
    );

    -- ================================================================
    -- APPROVAL QUEUE (governance)
    -- ================================================================
    CREATE TABLE IF NOT EXISTS approval_queue (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id       TEXT NOT NULL,
        action       TEXT NOT NULL,
        payload      TEXT DEFAULT '{}',
        requested_by TEXT DEFAULT 'system',
        status       TEXT DEFAULT 'pending',    -- pending | approved | rejected
        reviewed_by  TEXT DEFAULT NULL,
        reason       TEXT DEFAULT NULL,
        created_at   TEXT DEFAULT (datetime('now')),
        reviewed_at  TEXT DEFAULT NULL
    );
    -- ================================================================
    -- USERS (RBAC)
    -- ================================================================
    CREATE TABLE IF NOT EXISTS users (
        username     TEXT PRIMARY KEY,
        password     TEXT NOT NULL,
        role         TEXT NOT NULL,    -- admin | supervisor
        full_name    TEXT,
        last_login   TEXT DEFAULT NULL
    );
    """)

    # ── Migrate existing DBs: add new columns if missing ──────────────
    _migrate_columns(cur)

    conn.commit()
    conn.close()


def _migrate_columns(cur):
    """Safely add missing columns to existing tables (idempotent)."""
    migrations = {
        "jobs": [
            ("profit_margin",      "REAL DEFAULT 0.0"),
            ("delay_penalty",      "REAL DEFAULT 0.0"),
            ("client_priority",    "INTEGER DEFAULT 3"),
            ("contractual",        "INTEGER DEFAULT 0"),
            ("reputation_risk",    "REAL DEFAULT 0.0"),
            ("job_lock_status",    "INTEGER DEFAULT 0"),
            ("locked_by",          "TEXT DEFAULT NULL"),
            ("locked_at",          "TEXT DEFAULT NULL"),
            ("material_available", "INTEGER DEFAULT 1"),
            ("is_preemptable",     "INTEGER DEFAULT 0"),
            ("preempted_at",       "REAL DEFAULT NULL"),
            ("completion_pct",     "REAL DEFAULT 0.0"),
        ],
        "machines": [
            ("reliability_score",  "REAL DEFAULT 1.0"),
            ("maintenance_due",    "INTEGER DEFAULT 0"),
            ("overload_threshold", "REAL DEFAULT 90.0"),
            ("last_maintained_at", "TEXT DEFAULT NULL"),
        ],
        "workers": [
            ("reliability_score",  "REAL DEFAULT 1.0"),
            ("overtime_eligible",  "INTEGER DEFAULT 0"),
        ],
    }
    for table, cols in migrations.items():
        existing = {row[1] for row in cur.execute(f"PRAGMA table_info({table})")}
        for col_name, col_def in cols:
            if col_name not in existing:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")


def _seed_optimizer_settings(cur):
    defaults = [
        ("w1_makespan",    0.25, "Weight for makespan minimisation"),
        ("w2_delay",       0.25, "Weight for total delay minimisation"),
        ("w3_profit",      0.30, "Weight for profit maximisation"),
        ("w4_utilization", 0.20, "Weight for utilisation balancing"),
    ]
    for key, val, desc in defaults:
        cur.execute(
            "INSERT OR IGNORE INTO optimizer_settings(key,value,description) VALUES(?,?,?)",
            (key, val, desc),
        )


def _seed_users(cur):
    users = [
        ("admin", "admin123", "admin", "Factory Admin"),
        ("supervisor", "super123", "supervisor", "Shift Supervisor"),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO users(username, password, role, full_name) VALUES(?,?,?,?)",
        users,
    )


def seed_demo_data():
    """Load realistic factory demo data from CSV files."""
    conn = get_connection()
    cur = conn.cursor()

    # Seed core settings
    _seed_optimizer_settings(cur)
    _seed_users(cur)

    # Check if already seeded (machines is a good proxy)
    cur.execute("SELECT COUNT(*) FROM machines")
    if cur.fetchone()[0] > 0:
        conn.commit()
        conn.close()
        return

    # Helper to load CSV safely
    def load_csv(filename):
        path = DATA_DIR / filename
        if not path.exists():
            print(f"Warning: Demo data file {path} not found.")
            return []
        with open(path, mode='r', encoding='utf-8') as f:
            return list(csv.DictReader(f))

    # ── Machines ──────────────────────────────────────────────────────
    machines_data = load_csv("machines.csv")
    for m in machines_data:
        cur.execute(
            """INSERT OR IGNORE INTO machines
               (id,name,machine_type,status,daily_capacity,reliability_score,maintenance_due)
               VALUES(?,?,?,?,?,?,?)""",
            (m["id"], m["name"], m["machine_type"], m["status"], 
             float(m["daily_capacity"]), float(m["reliability_score"]), int(m["maintenance_due"])),
        )

    # ── Workers ───────────────────────────────────────────────────────
    workers_data = load_csv("workers.csv")
    for w in workers_data:
        cur.execute(
            """INSERT OR IGNORE INTO workers
               (id,name,skills,shift_start,shift_end,reliability_score,overtime_eligible)
               VALUES(?,?,?,?,?,?,?)""",
            (w["id"], w["name"], w["skills"], 
             float(w["shift_start"]), float(w["shift_end"]), 
             float(w["reliability_score"]), int(w["overtime_eligible"])),
        )

    # ── Jobs ──────────────────────────────────────────────────────────
    jobs_data = load_csv("jobs.csv")
    for j in jobs_data:
        cur.execute(
            """INSERT OR IGNORE INTO jobs
               (id,name,processing_time,due_date,priority,required_machine_type,
                required_worker_skill,precedence,profit_margin,delay_penalty,
                client_priority,contractual,reputation_risk,material_available)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                j["id"], j["name"], float(j["processing_time"]), j["due_date"], 
                int(j["priority"]), j["required_machine_type"], j["required_worker_skill"], 
                j.get("precedence") or None, float(j["profit_margin"]), float(j["delay_penalty"]), 
                int(j["client_priority"]), int(j["contractual"]), 
                float(j["reputation_risk"]), int(j["material_available"])
            ),
        )

    conn.commit()
    conn.close()

