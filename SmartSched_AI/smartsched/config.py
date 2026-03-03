"""
SmartSched AI – Configuration
==============================
Reads environment variables (from .env file or system env).
All tuneable parameters are centralised here.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).parent / ".env")
except ImportError:
    pass  # dotenv optional in dev


# -----------------------------------------------------------------------
# Application
# -----------------------------------------------------------------------
APP_VERSION = "2.0.0"
APP_NAME    = "SmartSched AI"
APP_ENV     = os.getenv("APP_ENV", "development")   # development | production

# -----------------------------------------------------------------------
# Server
# -----------------------------------------------------------------------
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
RELOAD = APP_ENV == "development"

# -----------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------
# SQLite (default/dev) or PostgreSQL (production)
_db_path = Path(__file__).parent / "database" / "smartsched.db"
DB_URL = os.getenv("DATABASE_URL", f"sqlite:///{_db_path}")

# -----------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------
LOG_LEVEL    = os.getenv("LOG_LEVEL", "INFO")          # DEBUG|INFO|WARNING|ERROR|CRITICAL
LOG_FILE     = os.getenv("LOG_FILE", "logs/smartsched.log")
LOG_ROTATION = os.getenv("LOG_ROTATION", "10 MB")
LOG_RETENTION= os.getenv("LOG_RETENTION", "30 days")

# -----------------------------------------------------------------------
# Multi-Objective Optimizer Weights (defaults – overridden via admin API)
# -----------------------------------------------------------------------
OPT_W1_MAKESPAN    = float(os.getenv("OPT_W1", "0.25"))   # Minimise makespan
OPT_W2_DELAY       = float(os.getenv("OPT_W2", "0.25"))   # Minimise total delay
OPT_W3_PROFIT      = float(os.getenv("OPT_W3", "0.30"))   # Maximise profit
OPT_W4_UTILIZATION = float(os.getenv("OPT_W4", "0.20"))   # Balance utilisation

# -----------------------------------------------------------------------
# Risk Thresholds
# -----------------------------------------------------------------------
RISK_MACHINE_THRESHOLD    = float(os.getenv("RISK_MACHINE_THRESHOLD", "0.3"))   # below = alert
RISK_WORKER_THRESHOLD     = float(os.getenv("RISK_WORKER_THRESHOLD", "0.3"))
OVERLOAD_THRESHOLD_PCT    = float(os.getenv("OVERLOAD_THRESHOLD_PCT", "90.0"))  # utilisation %
HIGH_RISK_RESHUFFLE_SCORE = float(os.getenv("HIGH_RISK_RESHUFFLE_SCORE", "50.0"))

# -----------------------------------------------------------------------
# Governance
# -----------------------------------------------------------------------
APPROVAL_REQUIRED_ABOVE_RISK = float(os.getenv("APPROVAL_REQUIRED_ABOVE_RISK", "50.0"))

# -----------------------------------------------------------------------
# Versioning / Checkpoints
# -----------------------------------------------------------------------
MAX_CHECKPOINTS = int(os.getenv("MAX_CHECKPOINTS", "20"))

# -----------------------------------------------------------------------
# Feature Flags
# -----------------------------------------------------------------------
ENABLE_PREEMPTION    = os.getenv("ENABLE_PREEMPTION", "true").lower() == "true"
ENABLE_MULTIDAY      = os.getenv("ENABLE_MULTIDAY", "true").lower() == "true"
OFFLINE_MODE         = os.getenv("OFFLINE_MODE", "false").lower() == "true"
