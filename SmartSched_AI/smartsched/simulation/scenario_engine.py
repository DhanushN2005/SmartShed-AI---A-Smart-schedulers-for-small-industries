"""
SmartSched AI v2 – Scenario Simulation Engine
===============================================
Provides decision-support analytics:
  - Accept vs Reject scenario comparison
  - Profit impact simulation
  - Utilization trend history
  - Schedule stability index
"""

from datetime import datetime
from database.models import get_connection
from risk.risk_engine import compute_net_impact


# ────────────────────────────────────────────────────────────────────
# Stability Index
# ────────────────────────────────────────────────────────────────────

def compute_stability_index() -> dict:
    """
    Stability Index (0–100): measures how stable the current schedule is.

    Factors:
      - % of jobs successfully scheduled        (higher = more stable)
      - % of machines available                 (higher = more stable)
      - % of workers available                  (higher = more stable)
      - Pending disruptions                     (higher unresolved = less stable)
      - Machine reliability average             (higher = more stable)
    """
    conn = get_connection()

    jobs     = [dict(r) for r in conn.execute("SELECT status FROM jobs").fetchall()]
    machines = [dict(r) for r in conn.execute(
        "SELECT status, reliability_score FROM machines"
    ).fetchall()]
    workers  = [dict(r) for r in conn.execute(
        "SELECT on_leave FROM workers"
    ).fetchall()]
    disruptions = conn.execute(
        "SELECT COUNT(*) as cnt FROM disruptions WHERE resolved=0"
    ).fetchone()["cnt"]
    conn.close()

    total_jobs = len(jobs) or 1
    scheduled  = sum(1 for j in jobs if j["status"] in ("scheduled", "completed"))
    j_score    = (scheduled / total_jobs) * 100

    total_machines = len(machines) or 1
    avail_machines = sum(1 for m in machines if m["status"] == "available")
    m_score        = (avail_machines / total_machines) * 100

    total_workers = len(workers) or 1
    avail_workers = sum(1 for w in workers if not w["on_leave"])
    w_score       = (avail_workers / total_workers) * 100

    avg_reliability = (
        sum(float(m.get("reliability_score", 1.0)) for m in machines) / total_machines * 100
    )

    disruption_penalty = min(disruptions * 5, 30)  # max 30 pt penalty

    raw = (j_score * 0.35 + m_score * 0.20 + w_score * 0.15
           + avg_reliability * 0.30) - disruption_penalty

    index = max(0.0, min(100.0, raw))

    level = "critical" if index < 40 else "warning" if index < 70 else "stable"

    return {
        "stability_index":    round(index, 1),
        "level":              level,
        "job_schedule_pct":   round(j_score, 1),
        "machine_avail_pct":  round(m_score, 1),
        "worker_avail_pct":   round(w_score, 1),
        "avg_reliability_pct":round(avg_reliability, 1),
        "open_disruptions":   disruptions,
        "disruption_penalty": disruption_penalty,
    }


# ────────────────────────────────────────────────────────────────────
# Accept vs Reject Scenario Comparison
# ────────────────────────────────────────────────────────────────────

def simulate_accept_job(job_data: dict) -> dict:
    """
    Project the impact of accepting a new job.
    Returns estimated makespan change, profit gain, and utilization.
    """
    conn = get_connection()
    machines = [dict(r) for r in conn.execute(
        "SELECT * FROM machines WHERE status='available'"
    ).fetchall()]
    current_schedule = [dict(r) for r in conn.execute(
        "SELECT start_time, end_time FROM schedule WHERE status='scheduled'"
    ).fetchall()]
    conn.close()

    current_makespan = 0.0
    if current_schedule:
        current_makespan = (
            max(s["end_time"] for s in current_schedule)
            - min(s["start_time"] for s in current_schedule)
        )

    # Estimate new makespan (simple heuristic: add job duration to least-loaded machine)
    base_time  = float(job_data.get("processing_time", 0))
    eff        = float(job_data.get("efficiency_modifier", 1.0)) or 1.0
    proc_time  = base_time / eff  # e.g., 50% efficiency (0.5) doubling the time
    
    mtype      = job_data.get("required_machine_type", "")
    compatible = [m for m in machines if m["machine_type"] == mtype]
    
    if compatible:
        least_loaded   = min(compatible, key=lambda m: float(m.get("current_workload", 0)))
        projected_load = float(least_loaded.get("current_workload", 0)) + proc_time
        cap            = float(least_loaded["daily_capacity"])
        new_util_pct   = min((projected_load / cap) * 100, 100)
    else:
        new_util_pct = 100.0  # no machine available

    new_makespan = current_makespan + proc_time

    net = compute_net_impact(job_data, days_delayed=0.0)

    return {
        "scenario":           "accept",
        "projected_makespan": round(new_makespan, 2),
        "delta_makespan":     round(proc_time, 2),
        "profit_gained":      float(job_data.get("profit_margin", 0)),
        "net_impact":         net["net_impact"],
        "machine_utilization_pct": round(new_util_pct, 1),
        "feasible":           len(compatible) > 0,
    }


def simulate_reject_job(job_data: dict) -> dict:
    """
    Project the impact of rejecting the job.
    Returns opportunity cost and freed capacity.
    """
    profit_lost   = float(job_data.get("profit_margin", 0))
    rep_risk_saved = float(job_data.get("reputation_risk", 0))

    # Opportunity cost = profit we're walking away from
    net_cost = profit_lost - rep_risk_saved

    base_time = float(job_data.get("processing_time", 0))
    eff       = float(job_data.get("efficiency_modifier", 1.0)) or 1.0
    proc_time = base_time / eff

    return {
        "scenario":         "reject",
        "profit_lost":      profit_lost,
        "reputation_risk_saved": rep_risk_saved,
        "net_opportunity_cost": round(net_cost, 2),
        "capacity_freed_hours": round(proc_time, 2),
    }


def compare_scenarios(job_data: dict) -> dict:
    """
    Run both Accept and Reject simulations and recommend the better option.
    """
    accept = simulate_accept_job(job_data)
    reject = simulate_reject_job(job_data)

    if accept["net_impact"] >= 0 and accept["feasible"]:
        recommendation = "accept"
        reason = f"Accepting yields a positive net impact of ₹{accept['net_impact']:,.0f}."
    elif not accept["feasible"]:
        recommendation = "reject"
        reason = "No compatible machine available to accept this job."
    else:
        recommendation = "reject"
        reason = (
            f"Net impact of accepting is negative (₹{accept['net_impact']:,.0f}). "
            f"Rejecting avoids losses; opportunity cost is ₹{reject['net_opportunity_cost']:,.0f}."
        )

    return {
        "job_id":         job_data.get("id"),
        "job_name":       job_data.get("name"),
        "accept_scenario": accept,
        "reject_scenario": reject,
        "recommendation": recommendation,
        "reason":         reason,
    }


# ────────────────────────────────────────────────────────────────────
# Utilization Trend
# ────────────────────────────────────────────────────────────────────

def utilization_trend() -> list:
    """
    Return machine utilization history reconstructed from schedule entries.
    Groups by day (day column in schedule table).
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT s.day, s.machine_id, m.name as machine_name, m.daily_capacity,
                  SUM(s.end_time - s.start_time) as total_hours
           FROM schedule s
           JOIN machines m ON s.machine_id = m.id
           GROUP BY s.day, s.machine_id
           ORDER BY s.day"""
    ).fetchall()
    conn.close()

    trend = []
    for r in rows:
        cap     = float(r["daily_capacity"]) if r["daily_capacity"] else 8.0
        util    = min((float(r["total_hours"]) / cap) * 100, 100)
        trend.append({
            "day":             r["day"],
            "machine_id":      r["machine_id"],
            "machine_name":    r["machine_name"],
            "utilization_pct": round(util, 1),
            "hours_used":      round(float(r["total_hours"]), 2),
        })

    return trend


# ────────────────────────────────────────────────────────────────────
# Profit Impact Overview
# ────────────────────────────────────────────────────────────────────

from datetime import datetime, timedelta

def profit_impact_summary() -> dict:
    """Compute total profit potential, dynamic delay penalty, and net impact."""
    conn = get_connection()
    jobs = [dict(r) for r in conn.execute("SELECT * FROM jobs WHERE status != 'cancelled'").fetchall()]
    schedule = [dict(r) for r in conn.execute(
        "SELECT s.*, j.due_date, j.delay_penalty, j.reputation_risk, j.profit_margin "
        "FROM schedule s JOIN jobs j ON s.job_id = j.id"
    ).fetchall()]
    conn.close()

    total_profit_potential = sum(float(j.get("profit_margin", 0)) for j in jobs)
    
    # Dynamic calculation based on schedule
    incurred_penalty = 0.0
    incurred_rep_risk = 0.0
    ref_date = datetime.now()
    
    for s in schedule:
        try:
            due = datetime.strptime(s["due_date"], "%Y-%m-%d")
            # Heuristic: s.end_time is hours from ref_date. 8h = 1 day.
            end_day_offset = int(s["end_time"] // 8)
            end_date = ref_date + timedelta(days=end_day_offset)
            
            if end_date > due:
                incurred_penalty += float(s.get("delay_penalty", 0))
                incurred_rep_risk += float(s.get("reputation_risk", 0))
        except Exception:
            pass

    net_impact = total_profit_potential - incurred_penalty - incurred_rep_risk

    return {
        "total_profit_potential":   round(total_profit_potential, 2),
        "total_delay_penalty_risk": round(incurred_penalty, 2),
        "total_reputation_risk":    round(incurred_rep_risk, 2),
        "net_factory_impact":       round(net_impact, 2),
        "contractual_job_count":    sum(1 for j in jobs if j.get("contractual")),
        "total_jobs_analysed":      len(jobs),
    }
