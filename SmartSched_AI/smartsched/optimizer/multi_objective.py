"""
SmartSched AI v2 – Multi-Objective Optimizer
=============================================
Replaces the single urgency heuristic with a configurable weighted
scoring function that simultaneously optimises for:

  Objective_Score =
    w1 × (1 / makespan_estimate)   [minimise makespan]
  + w2 × (1 / delay_days + 1)      [minimise delay]
  + w3 × profit_margin             [maximise profit]
  + w4 × utilization_balance       [balance load]
  + w5 × client_priority           [honour contracts]
  − reputation_risk_penalty        [avoid reputational damage]

Weights are loaded from the optimizer_settings table at runtime and
can be reconfigured by admins via the API without a server restart.
"""

from datetime import datetime, timedelta
from database.models import get_connection


# ────────────────────────────────────────────────────────────────────
# Weight Loading
# ────────────────────────────────────────────────────────────────────

def get_weights() -> dict:
    """Load weights from optimizer_settings table."""
    try:
        conn = get_connection()
        rows = conn.execute("SELECT key, value FROM optimizer_settings").fetchall()
        conn.close()
        weights = {r["key"]: float(r["value"]) for r in rows}
    except Exception:
        weights = {}

    return {
        "w1_makespan":    weights.get("w1_makespan",    0.25),
        "w2_delay":       weights.get("w2_delay",       0.25),
        "w3_profit":      weights.get("w3_profit",      0.30),
        "w4_utilization": weights.get("w4_utilization", 0.20),
    }


def update_weights(new_weights: dict) -> dict:
    """Persist updated optimizer weights to the database."""
    conn = get_connection()
    for key, val in new_weights.items():
        conn.execute(
            """INSERT INTO optimizer_settings(key, value, updated_at)
               VALUES(?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, float(val)),
        )
    conn.commit()
    conn.close()
    return get_weights()


# ────────────────────────────────────────────────────────────────────
# Objective Score
# ────────────────────────────────────────────────────────────────────

def compute_score(job: dict, reference_date: str = None, weights: dict = None) -> float:
    """
    Compute the multi-objective priority score for a job.

    Higher score = schedule this job earlier.

    Parameters
    ----------
    job            : dict row from the jobs table
    reference_date : 'YYYY-MM-DD' string; defaults to today
    weights        : optional pre-loaded weight dict (avoids repeated DB reads)
    """
    if weights is None:
        weights = get_weights()

    ref = (
        datetime.strptime(reference_date, "%Y-%m-%d")
        if reference_date
        else datetime.now()
    )

    # ── Due-date urgency ──────────────────────────────────────────────
    try:
        due = datetime.strptime(str(job.get("due_date", "")), "%Y-%m-%d")
    except ValueError:
        due = ref + timedelta(days=7)

    days_remaining = max(1, (due - ref).days)
    delay_score    = 100.0 / days_remaining   # higher = more urgent

    # ── Profit component ─────────────────────────────────────────────
    profit         = float(job.get("profit_margin", 0))
    # Normalise profit to 0–100 range (cap at 100k)
    profit_norm    = min(profit / 1000.0, 100.0)

    # ── Client priority ───────────────────────────────────────────────
    client_prio    = float(job.get("client_priority", job.get("priority", 3)))
    client_factor  = client_prio * 10.0      # 10–50 range

    # ── Contractual commitment bonus ──────────────────────────────────
    contract_bonus = 20.0 if job.get("contractual") else 0.0

    # ── Reputation risk penalty ───────────────────────────────────────
    rep_risk       = float(job.get("reputation_risk", 0))

    # ── Processing time penalty (resource fairness) ───────────────────
    proc_penalty   = float(job.get("processing_time", 0)) * 0.5

    # ── Weighted sum ──────────────────────────────────────────────────
    w = weights
    score = (
        w["w1_makespan"]    * delay_score       # proxy for makespan urgency
        + w["w2_delay"]     * delay_score       # delay minimisation
        + w["w3_profit"]    * profit_norm       # profit maximisation
        + w["w4_utilization"] * client_factor   # utilisation / client factor
        + contract_bonus                         # hard commitment bonus
        - rep_risk * 0.1                         # reputational risk penalty
        - proc_penalty                           # long job penalty
    )

    return round(score, 4)


# ────────────────────────────────────────────────────────────────────
# Backward-compatible alias (replaces old compute_urgency_score)
# ────────────────────────────────────────────────────────────────────

def compute_urgency_score(job: dict, reference_date: str = None) -> float:
    """Alias kept for backward compatibility with existing code."""
    return compute_score(job, reference_date)
