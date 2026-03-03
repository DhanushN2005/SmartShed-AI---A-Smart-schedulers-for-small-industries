"""
SmartSched AI v2 – Risk Engine
================================
Evaluates machine & worker reliability, detects overloads, predicts
maintenance needs, and computes the business Net Impact score.

Net_Impact = Urgent_Profit − Delay_Penalty − Reputation_Risk

If Net_Impact < threshold → flag for supervisor approval.
"""

from datetime import datetime
from database.models import get_connection

try:
    from config import (
        RISK_MACHINE_THRESHOLD,
        RISK_WORKER_THRESHOLD,
        OVERLOAD_THRESHOLD_PCT,
        HIGH_RISK_RESHUFFLE_SCORE,
        APPROVAL_REQUIRED_ABOVE_RISK,
    )
except ImportError:
    RISK_MACHINE_THRESHOLD    = 0.3
    RISK_WORKER_THRESHOLD     = 0.3
    OVERLOAD_THRESHOLD_PCT    = 90.0
    HIGH_RISK_RESHUFFLE_SCORE = 50.0
    APPROVAL_REQUIRED_ABOVE_RISK = 50.0


# ────────────────────────────────────────────────────────────────────
# Machine Risk
# ────────────────────────────────────────────────────────────────────

def assess_machine_risk(machine_id: str) -> dict:
    """
    Return reliability assessment for a single machine.
    Reliability 0–1: 1.0 = perfect, 0.0 = failed.
    """
    conn = get_connection()
    row = conn.execute("SELECT * FROM machines WHERE id=?", (machine_id,)).fetchone()
    conn.close()

    if not row:
        return {"error": f"Machine {machine_id} not found"}

    m = dict(row)
    reliability = float(m.get("reliability_score", 1.0))
    cap         = float(m.get("daily_capacity", 8.0))
    workload    = float(m.get("current_workload", 0.0))
    util_pct    = (workload / cap * 100) if cap > 0 else 0.0
    overloaded  = util_pct >= float(m.get("overload_threshold", 90.0))

    alert_level = "ok"
    recommendations = []

    if m.get("maintenance_due"):
        alert_level = "warning"
        recommendations.append("Schedule preventive maintenance immediately.")

    if reliability < RISK_MACHINE_THRESHOLD:
        alert_level = "critical"
        recommendations.append("Machine reliability critically low – consider replacement or outsourcing.")
    elif reliability < 0.6:
        alert_level = "warning"
        recommendations.append("Reliability degraded – schedule maintenance soon.")

    if overloaded:
        alert_level = "warning" if alert_level == "ok" else alert_level
        recommendations.append(f"Machine utilization {util_pct:.1f}% exceeds threshold – consider overtime or load balancing.")

    return {
        "machine_id":        machine_id,
        "name":              m["name"],
        "reliability_score": reliability,
        "utilization_pct":   round(util_pct, 1),
        "maintenance_due":   bool(m.get("maintenance_due")),
        "overloaded":        overloaded,
        "alert_level":       alert_level,
        "recommendations":   recommendations,
        "status":            m["status"],
    }


def assess_all_machine_risks() -> list:
    conn = get_connection()
    rows = conn.execute("SELECT id FROM machines").fetchall()
    conn.close()
    return [assess_machine_risk(r["id"]) for r in rows]


# ────────────────────────────────────────────────────────────────────
# Worker Risk
# ────────────────────────────────────────────────────────────────────

def assess_worker_risk(worker_id: str) -> dict:
    """Return reliability and fatigue assessment for a worker."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM workers WHERE id=?", (worker_id,)).fetchone()
    conn.close()

    if not row:
        return {"error": f"Worker {worker_id} not found"}

    w = dict(row)
    reliability   = float(w.get("reliability_score", 1.0))
    shift_hours   = float(w["shift_end"]) - float(w["shift_start"])
    assigned      = float(w.get("assigned_hours", 0.0))
    util_pct      = (assigned / shift_hours * 100) if shift_hours > 0 else 0.0
    overloaded    = util_pct >= OVERLOAD_THRESHOLD_PCT

    alert_level      = "ok"
    recommendations  = []

    if reliability < RISK_WORKER_THRESHOLD:
        alert_level = "critical"
        recommendations.append("Worker reliability critical – reassign or provide support.")
    elif reliability < 0.6:
        alert_level = "warning"
        recommendations.append("Worker reliability degraded – monitor closely.")

    if overloaded:
        old_level   = alert_level
        alert_level = "warning" if old_level == "ok" else old_level
        overtime    = bool(w.get("overtime_eligible"))
        if overtime:
            recommendations.append(f"Worker utilization {util_pct:.1f}% – approve overtime if needed.")
        else:
            recommendations.append(f"Worker overloaded at {util_pct:.1f}% – reassign or outsource tasks.")

    return {
        "worker_id":         worker_id,
        "name":              w["name"],
        "reliability_score": reliability,
        "utilization_pct":   round(util_pct, 1),
        "overtime_eligible": bool(w.get("overtime_eligible")),
        "on_leave":          bool(w.get("on_leave")),
        "overloaded":        overloaded,
        "alert_level":       alert_level,
        "recommendations":   recommendations,
    }


def assess_all_worker_risks() -> list:
    conn = get_connection()
    rows = conn.execute("SELECT id FROM workers").fetchall()
    conn.close()
    return [assess_worker_risk(r["id"]) for r in rows]


# ────────────────────────────────────────────────────────────────────
# Overload Detection
# ────────────────────────────────────────────────────────────────────

def detect_overload() -> dict:
    """Scan all machines and workers for overload conditions."""
    machine_risks = assess_all_machine_risks()
    worker_risks  = assess_all_worker_risks()

    overloaded_machines = [m for m in machine_risks if m.get("overloaded")]
    overloaded_workers  = [w for w in worker_risks  if w.get("overloaded")]
    critical_entities   = [
        e for e in (machine_risks + worker_risks)
        if e.get("alert_level") == "critical"
    ]

    return {
        "overloaded_machines": overloaded_machines,
        "overloaded_workers":  overloaded_workers,
        "critical_entities":   critical_entities,
        "total_overloaded":    len(overloaded_machines) + len(overloaded_workers),
        "has_critical":        len(critical_entities) > 0,
    }


# ────────────────────────────────────────────────────────────────────
# Business Net Impact
# ────────────────────────────────────────────────────────────────────

def compute_net_impact(job: dict, days_delayed: float = 0.0) -> dict:
    """
    Net_Impact = Urgent_Profit - Delay_Penalty - Reputation_Risk

    Parameters
    ----------
    job          : job dict (with profit_margin, delay_penalty, reputation_risk)
    days_delayed : estimated delay in days (0 = on-time)
    """
    profit         = float(job.get("profit_margin",   0))
    penalty_per_day= float(job.get("delay_penalty",   0))
    rep_risk       = float(job.get("reputation_risk", 0))
    contractual    = bool(job.get("contractual",      False))

    # Contract breach multiplier
    breach_multi   = 2.0 if (contractual and days_delayed > 0) else 1.0

    total_penalty  = penalty_per_day * days_delayed * breach_multi
    net_impact     = profit - total_penalty - rep_risk

    return {
        "job_id":          job.get("id"),
        "profit_margin":   profit,
        "delay_penalty":   round(total_penalty, 2),
        "reputation_risk": rep_risk,
        "days_delayed":    days_delayed,
        "contractual":     contractual,
        "breach_multiplier": breach_multi,
        "net_impact":      round(net_impact, 2),
    }


def recommend_decision(job: dict, days_delayed: float = 0.0) -> dict:
    """
    Analyse Net Impact and recommend Accept / Reject.
    Flags supervisor approval requirement for high-risk reshuffles.
    """
    impact     = compute_net_impact(job, days_delayed)
    net        = impact["net_impact"]
    rep_risk   = float(job.get("reputation_risk", 0))

    if net >= 0:
        decision = "accept"
        reason   = f"Positive net impact of ₹{net:,.0f}. Scheduling is profitable."
    else:
        decision = "reject"
        reason   = f"Negative net impact of ₹{net:,.0f}. Job costs more than it earns under current conditions."

    requires_approval = (
        abs(net) > HIGH_RISK_RESHUFFLE_SCORE
        or rep_risk > APPROVAL_REQUIRED_ABOVE_RISK
        or (job.get("contractual") and days_delayed > 0)
    )

    return {
        **impact,
        "decision":           decision,
        "reason":             reason,
        "requires_approval":  requires_approval,
        "approval_reason":    (
            "High net impact magnitude or reputation risk requires supervisor sign-off."
            if requires_approval else None
        ),
    }
