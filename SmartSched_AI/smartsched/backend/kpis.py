"""
SmartSched AI v2 – KPI Engine (Extended)
=========================================
New KPIs added:
  - Profit potential, delay penalty exposure, net factory impact
  - Stability index (from simulation engine)
  - Risk summary (from risk engine)
  - Disruption analytics
"""

import json
from datetime import datetime
from database.models import get_connection


def compute_kpis() -> dict:
    conn = get_connection()

    # ── Jobs ──────────────────────────────────────────────────────────
    jobs       = [dict(r) for r in conn.execute("SELECT * FROM jobs").fetchall()]
    total_jobs = len(jobs)
    pending    = sum(1 for j in jobs if j["status"] == "pending")
    scheduled  = sum(1 for j in jobs if j["status"] == "scheduled")
    completed  = sum(1 for j in jobs if j["status"] == "completed")
    locked     = sum(1 for j in jobs if j.get("job_lock_status"))
    no_material= sum(1 for j in jobs if not j.get("material_available", 1))
    contractual= sum(1 for j in jobs if j.get("contractual"))

    # Profit KPIs (Base Potential)
    total_profit     = sum(float(j.get("profit_margin",  0)) for j in jobs)
    contractual      = sum(1 for j in jobs if j.get("contractual"))
    # (Penalties and Net Impact will be calculated dynamically below based on actual schedule)

    # ── Machines ──────────────────────────────────────────────────────
    machines         = [dict(r) for r in conn.execute("SELECT * FROM machines").fetchall()]
    total_machines   = len(machines)
    available_mach   = sum(1 for m in machines if m["status"] == "available")
    broken_mach      = sum(1 for m in machines if m["status"] in ("breakdown", "maintenance"))
    maint_due_count  = sum(1 for m in machines if m.get("maintenance_due"))

    machine_utils  = []
    total_idle     = 0.0
    overloaded_mach= 0
    avg_reliability= 0.0
    for m in machines:
        cap  = float(m["daily_capacity"]) if m["daily_capacity"] else 8.0
        wl   = float(m["current_workload"]) if m["current_workload"] else 0.0
        util = min(round((wl / cap) * 100, 1), 100) if cap > 0 else 0
        idle = max(0.0, cap - wl)
        rel  = float(m.get("reliability_score", 1.0))
        total_idle     += idle
        avg_reliability += rel
        if util > float(m.get("overload_threshold", 90)):
            overloaded_mach += 1
        machine_utils.append({
            "id":              m["id"],
            "name":            m["name"],
            "type":            m["machine_type"],
            "status":          m["status"],
            "utilization":     util,
            "idle_hours":      round(idle, 2),
            "workload":        round(wl, 2),
            "capacity":        cap,
            "reliability":     rel,
            "maintenance_due": bool(m.get("maintenance_due")),
        })
    avg_machine_util = (
        round(sum(u["utilization"] for u in machine_utils) / len(machine_utils), 1)
        if machine_utils else 0
    )
    avg_reliability = round(avg_reliability / total_machines, 3) if total_machines else 1.0

    # ── Workers ───────────────────────────────────────────────────────
    workers       = [dict(r) for r in conn.execute("SELECT * FROM workers").fetchall()]
    worker_utils  = []
    overloaded_w  = 0
    for w in workers:
        sh     = float(w["shift_end"]) - float(w["shift_start"])
        asgn   = float(w.get("assigned_hours", 0.0))
        util   = min(round((asgn / sh) * 100, 1), 100) if sh > 0 else 0
        if util > 90:
            overloaded_w += 1
        skills = w["skills"]
        if isinstance(skills, str):
            try:    skills = json.loads(skills)
            except: skills = [skills]
        worker_utils.append({
            "id":               w["id"],
            "name":             w["name"],
            "skills":           skills,
            "utilization":      util,
            "assigned_hours":   round(asgn, 2),
            "shift_hours":      sh,
            "on_leave":         bool(w["on_leave"]),
            "reliability":      float(w.get("reliability_score", 1.0)),
            "overtime_eligible":bool(w.get("overtime_eligible")),
        })
    avg_worker_util = (
        round(sum(u["utilization"] for u in worker_utils) / len(worker_utils), 1)
        if worker_utils else 0
    )

    # ── Schedule ──────────────────────────────────────────────────────
    schedule = [dict(r) for r in conn.execute(
        "SELECT s.*, j.due_date, j.name as job_name, j.delay_penalty, j.reputation_risk "
        "FROM schedule s JOIN jobs j ON s.job_id=j.id"
    ).fetchall()]

    incurred_penalty  = 0.0
    incurred_rep_risk = 0.0
    on_time  = 0
    late     = 0
    makespan = 0.0

    if schedule:
        makespan = round(
            max(s["end_time"] for s in schedule) - min(s["start_time"] for s in schedule),
            2,
        )
        ref_date = datetime.now()
        import datetime as dt_module
        for s in schedule:
            try:
                due           = datetime.strptime(s["due_date"], "%Y-%m-%d")
                end_day_offset= int(s["end_time"] // 8)
                end_date      = ref_date + dt_module.timedelta(days=end_day_offset)
                if end_date <= due:
                    on_time += 1
                else:
                    late += 1
                    incurred_penalty  += float(s.get("delay_penalty", 0))
                    incurred_rep_risk += float(s.get("reputation_risk", 0))
            except Exception:
                on_time += 1

    otd_pct = round((on_time / len(schedule) * 100), 1) if schedule else 0
    net_impact = total_profit - incurred_penalty - incurred_rep_risk

    # ── Disruptions ───────────────────────────────────────────────────
    disruptions = [dict(r) for r in conn.execute(
        "SELECT * FROM disruptions ORDER BY occurred_at DESC LIMIT 20"
    ).fetchall()]
    open_disruptions = sum(1 for d in disruptions if not d.get("resolved"))

    conn.close()

    # ── Risk & Stability (from modules) ───────────────────────────────
    stability = None
    try:
        from simulation.scenario_engine import compute_stability_index
        stability = compute_stability_index()
    except Exception:
        pass

    risk_summary = None
    try:
        from risk.risk_engine import detect_overload
        risk_summary = detect_overload()
    except Exception:
        pass

    active_mach      = sum(1 for m in machines if float(m["current_workload"]) > 0)

    return {
        "summary": {
            "total_jobs":         total_jobs,
            "pending_jobs":       pending,
            "scheduled_jobs":     scheduled,
            "completed_jobs":     completed,
            "locked_jobs":        locked,
            "no_material_jobs":   no_material,
            "contractual_jobs":   contractual,
            "total_machines":     total_machines,
            "available_machines": available_mach,
            "active_machines":    active_mach,
            "broken_machines":    broken_mach,
            "maintenance_due":    maint_due_count,
            "open_disruptions":   open_disruptions,
        },
        "financial_kpis": {
            "total_profit_potential":   round(total_profit, 2),
            "total_delay_penalty_risk": round(incurred_penalty, 2),
            "total_reputation_risk":    round(incurred_rep_risk, 2),
            "net_factory_impact":       round(net_impact, 2),
            "contractual_job_count":    contractual,
        },
        "machine_kpis": {
            "avg_utilization_pct":  avg_machine_util,
            "total_idle_hours":     round(total_idle, 2),
            "overloaded_count":     overloaded_mach,
            "avg_reliability":      avg_reliability,
            "maintenance_due_count":maint_due_count,
            "machines":             machine_utils,
        },
        "worker_kpis": {
            "avg_utilization_pct": avg_worker_util,
            "overloaded_count":    overloaded_w,
            "workers":             worker_utils,
        },
        "schedule_kpis": {
            "makespan_hours":       makespan,
            "on_time_delivery_pct": otd_pct,
            "on_time_count":        on_time,
            "late_count":           late,
            "total_scheduled":      len(schedule),
        },
        "stability":   stability,
        "risk":        risk_summary,
        "disruptions": disruptions,
    }
