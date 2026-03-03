"""
SmartSched AI v2 – FastAPI Backend (Extended)
===============================================
REST API covering all v2 features:
  - Jobs, Machines, Workers (CRUD + extended fields)
  - Scheduling & Dynamic Rescheduling
  - Risk Management Module
  - Human Governance Layer
  - Simulation & Scenario Engine
  - Versioning & Checkpoints
  - Multi-Objective Optimizer Settings
  - KPIs & Analytics
"""

import json
import csv
import io
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, HTTPException, UploadFile, File, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

# Core modules
from database.models import init_db, seed_demo_data, get_connection
from scheduler.engine import run_full_schedule, compute_urgency_score
from rescheduler.dynamic import DynamicRescheduler
from backend.kpis import compute_kpis
from agents.agents import run_agent_schedule

# New v2 modules
from risk.risk_engine import (
    assess_all_machine_risks, assess_all_worker_risks,
    detect_overload, compute_net_impact, recommend_decision
)
from governance.governance import (
    lock_job, unlock_job, manual_override,
    submit_for_approval, get_pending_approvals,
    approve_action, reject_action, get_audit_trail
)
from simulation.scenario_engine import (
    compare_scenarios, compute_stability_index,
    utilization_trend, profit_impact_summary
)
from versioning.checkpoint import (
    save_checkpoint, list_versions, rollback_to, get_diff
)
from optimizer.multi_objective import get_weights, update_weights

# Logging
try:
    from logger import logger
except Exception:
    import logging
    logger = logging.getLogger("smartsched")


# ────────────────────────────────────────────────────────────────────
# App Lifespan
# ────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("SmartSched AI v2 – Initialising database...")
    init_db()
    seed_demo_data()
    logger.info("SmartSched AI v2 – Ready.")
    yield
    logger.info("SmartSched AI v2 – Shutting down.")


app = FastAPI(
    title="SmartSched AI v2",
    description=(
        "Industrial-Grade Production Decision Governance System. "
        "Workforce & machine scheduling with risk management, governance, "
        "scenario simulation, and checkpoint versioning."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ────────────────────────────────────────────────────────────────────
# Pydantic Models
# ────────────────────────────────────────────────────────────────────

class JobCreate(BaseModel):
    id: str
    name: str
    processing_time: float = Field(..., gt=0)
    due_date: str
    priority: int = Field(3, ge=1, le=5)
    required_machine_type: str
    required_worker_skill: str
    precedence: Optional[str] = None
    # v2 fields
    profit_margin:     float = 0.0
    delay_penalty:     float = 0.0
    client_priority:   int   = Field(3, ge=1, le=5)
    contractual:       int   = 0
    reputation_risk:   float = 0.0
    material_available:int   = 1
    is_preemptable:    int   = 0


class MachineCreate(BaseModel):
    id: str
    name: str
    machine_type: str
    status: str            = "available"
    daily_capacity: float  = 8.0
    location: str          = ""
    notes: str             = ""
    reliability_score: float = 1.0
    overload_threshold:float = 90.0


class WorkerCreate(BaseModel):
    id: str
    name: str
    skills: List[str]
    shift_start: float = 8.0
    shift_end:   float = 16.0
    department:  str   = ""
    reliability_score:  float = 1.0
    overtime_eligible:  int   = 0


class RushOrderRequest(BaseModel):
    id: str
    name: str
    processing_time: float
    due_date: Optional[str]    = None
    required_machine_type: str
    required_worker_skill: str
    profit_margin:   float = 50000.0
    delay_penalty:   float = 1000.0
    reputation_risk: float = 30.0


class OverrideRequest(BaseModel):
    machine_id:   str
    worker_id:    str
    start_time:   float
    requested_by: str = "supervisor"


class WeightsUpdate(BaseModel):
    w1_makespan:    Optional[float] = None
    w2_delay:       Optional[float] = None
    w3_profit:      Optional[float] = None
    w4_utilization: Optional[float] = None


class SimulateJobRequest(BaseModel):
    id:                   str = "SIM001"
    name:                 str = "Simulated Job"
    processing_time:      float = 2.0
    due_date:             Optional[str] = None
    required_machine_type:str = "CNC"
    required_worker_skill:str = "CNC"
    profit_margin:        float = 10000.0
    delay_penalty:        float = 500.0
    reputation_risk:      float = 5.0
    contractual:          int   = 0
    material_available:   int   = 1
    efficiency_modifier:  float = 1.0  # 1.0 = 100%, 0.5 = 50% efficiency (takes 2x time)


class SimultaneousEventRequest(BaseModel):
    machine_id: str
    rush_job:   RushOrderRequest


class UserLogin(BaseModel):
    username: str
    password: str


# ────────────────────────────────────────────────────────────────────
# User Auth
# ────────────────────────────────────────────────────────────────────

@app.post("/api/login", tags=["System"])
def login(user: UserLogin):
    username = user.username.strip()
    password = user.password.strip()
    logger.info(f"Login attempt: {username}")
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM users WHERE username=? AND password=?",
        (username, password)
    ).fetchone()
    
    if not row:
        logger.warning(f"Failed login attempt for: {username}")
        conn.close()
        raise HTTPException(401, "Invalid credentials")
    
    u = dict(row)
    conn.execute(
        "UPDATE users SET last_login=? WHERE username=?",
        (datetime.now().isoformat(), user.username)
    )
    conn.commit()
    conn.close()
    
    return {
        "status": "success",
        "username": u["username"],
        "role": u["role"],
        "full_name": u["full_name"]
    }


# ────────────────────────────────────────────────────────────────────
# Health
# ────────────────────────────────────────────────────────────────────

@app.get("/api/health", tags=["System"])
def health():
    return {
        "status":    "ok",
        "version":   "2.0.0",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/login", response_class=HTMLResponse, tags=["System"])
def login_page():
    path = Path(__file__).parent.parent / "frontend" / "login.html"
    return HTMLResponse(content=path.read_text(encoding="utf-8"))


# ────────────────────────────────────────────────────────────────────
# Jobs
# ────────────────────────────────────────────────────────────────────

@app.get("/api/jobs", tags=["Jobs"])
def get_jobs(status: Optional[str] = None):
    conn = get_connection()
    if status:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status=? ORDER BY urgency_score DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY urgency_score DESC, priority DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/jobs", tags=["Jobs"])
def create_job(job: JobCreate):
    conn = get_connection()
    if conn.execute("SELECT id FROM jobs WHERE id=?", (job.id,)).fetchone():
        conn.close()
        raise HTTPException(400, f"Job {job.id} already exists")
    score = compute_urgency_score(job.dict())
    d = job.dict()
    conn.execute(
        """INSERT INTO jobs
           (id,name,processing_time,due_date,priority,required_machine_type,
            required_worker_skill,precedence,urgency_score,profit_margin,delay_penalty,
            client_priority,contractual,reputation_risk,material_available,is_preemptable)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (d["id"],d["name"],d["processing_time"],d["due_date"],d["priority"],
         d["required_machine_type"],d["required_worker_skill"],d["precedence"],score,
         d["profit_margin"],d["delay_penalty"],d["client_priority"],d["contractual"],
         d["reputation_risk"],d["material_available"],d["is_preemptable"]),
    )
    conn.commit(); conn.close()
    return {"status": "created", "job_id": job.id, "urgency_score": score}


@app.put("/api/jobs/{job_id}", tags=["Jobs"])
def update_job(job_id: str, job: JobCreate):
    conn = get_connection()
    score = compute_urgency_score(job.dict())
    d = job.dict()
    conn.execute(
        """UPDATE jobs SET name=?,processing_time=?,due_date=?,priority=?,
           required_machine_type=?,required_worker_skill=?,precedence=?,urgency_score=?,
           profit_margin=?,delay_penalty=?,client_priority=?,contractual=?,
           reputation_risk=?,material_available=?,is_preemptable=?
           WHERE id=?""",
        (d["name"],d["processing_time"],d["due_date"],d["priority"],
         d["required_machine_type"],d["required_worker_skill"],d["precedence"],score,
         d["profit_margin"],d["delay_penalty"],d["client_priority"],d["contractual"],
         d["reputation_risk"],d["material_available"],d["is_preemptable"],job_id),
    )
    conn.commit(); conn.close()
    return {"status": "updated", "job_id": job_id}


@app.delete("/api/jobs/{job_id}", tags=["Jobs"])
def delete_job(job_id: str):
    conn = get_connection()
    conn.execute("DELETE FROM schedule WHERE job_id=?", (job_id,))
    conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    conn.commit(); conn.close()
    return {"status": "deleted"}


@app.post("/api/jobs/upload-csv", tags=["Jobs"])
async def upload_jobs_csv(file: UploadFile = File(...)):
    content = await file.read()
    reader  = csv.DictReader(io.StringIO(content.decode("utf-8")))
    conn    = get_connection()
    inserted, errors = 0, []
    for row in reader:
        try:
            score = compute_urgency_score(row)
            conn.execute(
                """INSERT OR REPLACE INTO jobs
                   (id,name,processing_time,due_date,priority,required_machine_type,
                    required_worker_skill,precedence,urgency_score)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (row["id"], row.get("name",row["id"]), float(row["processing_time"]),
                 row["due_date"], int(row.get("priority",3)),
                 row["required_machine_type"], row["required_worker_skill"],
                 row.get("precedence") or None, score),
            )
            inserted += 1
        except Exception as e:
            errors.append(str(e))
    conn.commit(); conn.close()
    return {"inserted": inserted, "errors": errors}


@app.post("/api/jobs/{job_id}/lock", tags=["Jobs"])
def api_lock_job(job_id: str, locked_by: str = Query("supervisor")):
    return lock_job(job_id, locked_by)


@app.post("/api/jobs/{job_id}/unlock", tags=["Jobs"])
def api_unlock_job(job_id: str, unlocked_by: str = Query("supervisor")):
    return unlock_job(job_id, unlocked_by)


@app.put("/api/jobs/{job_id}/complete-partial", tags=["Jobs"])
def set_partial_completion(job_id: str, completion_pct: float = Query(..., ge=0, le=100)):
    conn = get_connection()
    conn.execute(
        "UPDATE jobs SET completion_pct=? WHERE id=?", (completion_pct, job_id)
    )
    conn.commit(); conn.close()
    return {"status": "updated", "job_id": job_id, "completion_pct": completion_pct}


@app.put("/api/jobs/{job_id}/material", tags=["Jobs"])
def set_material_availability(job_id: str, available: int = Query(..., ge=0, le=1)):
    conn = get_connection()
    conn.execute(
        "UPDATE jobs SET material_available=? WHERE id=?", (available, job_id)
    )
    conn.commit(); conn.close()
    return {"status": "updated", "job_id": job_id, "material_available": bool(available)}


# ────────────────────────────────────────────────────────────────────
# Machines
# ────────────────────────────────────────────────────────────────────

@app.get("/api/machines", tags=["Machines"])
def get_machines():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM machines ORDER BY machine_type, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/machines", tags=["Machines"])
def create_machine(machine: MachineCreate):
    conn = get_connection()
    d = machine.dict()
    conn.execute(
        """INSERT INTO machines
           (id,name,machine_type,status,daily_capacity,location,notes,
            reliability_score,overload_threshold)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (d["id"],d["name"],d["machine_type"],d["status"],d["daily_capacity"],
         d["location"],d["notes"],d["reliability_score"],d["overload_threshold"]),
    )
    conn.commit(); conn.close()
    return {"status": "created"}


@app.put("/api/machines/{machine_id}/status", tags=["Machines"])
def update_machine_status(machine_id: str, status: str = Query(...)):
    valid = {"available","busy","maintenance","breakdown"}
    if status not in valid:
        raise HTTPException(400, f"Status must be one of {valid}")
    conn = get_connection()
    conn.execute("UPDATE machines SET status=? WHERE id=?", (status, machine_id))
    conn.commit(); conn.close()
    return {"status": "updated", "machine_id": machine_id, "new_status": status}


@app.put("/api/machines/{machine_id}/reliability", tags=["Machines"])
def update_machine_reliability(machine_id: str, score: float = Query(..., ge=0, le=1)):
    conn = get_connection()
    conn.execute(
        "UPDATE machines SET reliability_score=? WHERE id=?", (score, machine_id)
    )
    conn.commit(); conn.close()
    return {"status": "updated", "machine_id": machine_id, "reliability_score": score}


@app.delete("/api/machines/{machine_id}", tags=["Machines"])
def delete_machine(machine_id: str):
    conn = get_connection()
    conn.execute("DELETE FROM machines WHERE id=?", (machine_id,))
    conn.commit(); conn.close()
    return {"status": "deleted"}


# ────────────────────────────────────────────────────────────────────
# Workers
# ────────────────────────────────────────────────────────────────────

@app.get("/api/workers", tags=["Workers"])
def get_workers():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM workers ORDER BY name").fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["skills"] = json.loads(d["skills"]) if isinstance(d["skills"], str) else d["skills"]
        result.append(d)
    return result


@app.post("/api/workers", tags=["Workers"])
def create_worker(worker: WorkerCreate):
    conn = get_connection()
    d = worker.dict()
    conn.execute(
        """INSERT INTO workers
           (id,name,skills,shift_start,shift_end,department,
            reliability_score,overtime_eligible)
           VALUES(?,?,?,?,?,?,?,?)""",
        (d["id"],d["name"],json.dumps(d["skills"]),d["shift_start"],d["shift_end"],
         d["department"],d["reliability_score"],d["overtime_eligible"]),
    )
    conn.commit(); conn.close()
    return {"status": "created"}


@app.put("/api/workers/{worker_id}/leave", tags=["Workers"])
def toggle_worker_leave(worker_id: str, on_leave: int = Query(...)):
    conn = get_connection()
    conn.execute("UPDATE workers SET on_leave=? WHERE id=?", (on_leave, worker_id))
    conn.commit(); conn.close()
    return {"status": "updated", "on_leave": bool(on_leave)}


@app.delete("/api/workers/{worker_id}", tags=["Workers"])
def delete_worker(worker_id: str):
    conn = get_connection()
    conn.execute("DELETE FROM workers WHERE id=?", (worker_id,))
    conn.commit(); conn.close()
    return {"status": "deleted"}


# ────────────────────────────────────────────────────────────────────
# Scheduling
# ────────────────────────────────────────────────────────────────────

@app.post("/api/schedule/run", tags=["Scheduling"])
def run_schedule(reference_date: Optional[str] = None):
    conn = get_connection()
    # 1. Clear only NON-LOCKED scheduled entries
    conn.execute("""
        DELETE FROM schedule 
        WHERE status='scheduled' 
        AND job_id NOT IN (SELECT id FROM jobs WHERE job_lock_status=1)
    """)
    # 2. Reset status for non-locked jobs
    conn.execute("UPDATE jobs SET status='pending' WHERE status='scheduled' AND job_lock_status=0")
    
    # 3. Recalculate machine/worker workloads based on remaining (locked) schedule
    conn.execute("UPDATE machines SET current_workload=0")
    conn.execute("UPDATE workers SET assigned_hours=0")
    
    # Restore workloads from locked/in-progress jobs
    active = conn.execute("SELECT job_id, machine_id, worker_id, (end_time - start_time) as duration FROM schedule WHERE status IN ('scheduled','in_progress')").fetchall()
    for row in active:
        conn.execute("UPDATE machines SET current_workload = current_workload + ? WHERE id=?", (row["duration"], row["machine_id"]))
        conn.execute("UPDATE workers SET assigned_hours = assigned_hours + ? WHERE id=?", (row["duration"], row["worker_id"]))
        
    conn.commit(); conn.close()
    return run_full_schedule(reference_date)


@app.get("/api/schedule", tags=["Scheduling"])
def get_schedule():
    conn = get_connection()
    rows = conn.execute(
        """SELECT s.*, j.name as job_name, j.due_date, j.priority, j.urgency_score,
                  j.profit_margin, j.job_lock_status,
                  m.name as machine_name, m.machine_type, m.reliability_score,
                  w.name as worker_name
           FROM schedule s
           JOIN jobs j ON s.job_id   = j.id
           JOIN machines m ON s.machine_id = m.id
           JOIN workers  w ON s.worker_id  = w.id
           ORDER BY s.start_time"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.delete("/api/schedule/clear", tags=["Scheduling"])
def clear_schedule():
    conn = get_connection()
    conn.execute("DELETE FROM schedule")
    conn.execute("UPDATE jobs SET status='pending'")
    conn.execute("UPDATE machines SET current_workload=0")
    conn.execute("UPDATE workers SET assigned_hours=0")
    conn.commit(); conn.close()
    return {"status": "cleared"}


# ────────────────────────────────────────────────────────────────────
# Dynamic Rescheduling
# ────────────────────────────────────────────────────────────────────

rescheduler = DynamicRescheduler()


@app.post("/api/reschedule/machine-breakdown/{machine_id}", tags=["Rescheduling"])
def machine_breakdown(machine_id: str):
    return rescheduler.handle_machine_breakdown(machine_id)


@app.post("/api/reschedule/worker-absence/{worker_id}", tags=["Rescheduling"])
def worker_absence(worker_id: str):
    return rescheduler.handle_worker_absence(worker_id)


@app.post("/api/reschedule/rush-order", tags=["Rescheduling"])
def rush_order(order: RushOrderRequest):
    return rescheduler.handle_rush_order(order.dict())


@app.post("/api/reschedule/simultaneous", tags=["Rescheduling"])
def simultaneous_event(req: SimultaneousEventRequest):
    return rescheduler.handle_simultaneous_event(req.machine_id, req.rush_job.dict())


@app.post("/api/reschedule/restore-machine/{machine_id}", tags=["Rescheduling"])
def restore_machine(machine_id: str):
    return rescheduler.restore_machine(machine_id)


@app.post("/api/reschedule/restore-worker/{worker_id}", tags=["Rescheduling"])
def restore_worker(worker_id: str):
    return rescheduler.restore_worker(worker_id)


# ────────────────────────────────────────────────────────────────────
# KPIs
# ────────────────────────────────────────────────────────────────────

@app.get("/api/kpis", tags=["Analytics"])
def get_kpis():
    return compute_kpis()


# ────────────────────────────────────────────────────────────────────
# Agents
# ────────────────────────────────────────────────────────────────────

@app.get("/api/agents/run", tags=["Agents"])
def run_agents():
    conn = get_connection()
    machines    = [dict(r) for r in conn.execute(
        "SELECT * FROM machines WHERE status='available'"
    ).fetchall()]
    workers_raw = [dict(r) for r in conn.execute(
        "SELECT * FROM workers WHERE on_leave=0"
    ).fetchall()]
    jobs = [dict(r) for r in conn.execute(
        "SELECT * FROM jobs WHERE status='pending'"
    ).fetchall()]
    conn.close()
    workers = []
    for w in workers_raw:
        w["skills"] = json.loads(w["skills"]) if isinstance(w["skills"], str) else w["skills"]
        workers.append(w)
    return run_agent_schedule(machines, workers, jobs)


# ────────────────────────────────────────────────────────────────────
# Risk Management
# ────────────────────────────────────────────────────────────────────

@app.get("/api/risk/machines", tags=["Risk"])
def get_machine_risks():
    return assess_all_machine_risks()


@app.get("/api/risk/workers", tags=["Risk"])
def get_worker_risks():
    return assess_all_worker_risks()


@app.get("/api/risk/overload", tags=["Risk"])
def get_overload_status():
    return detect_overload()


@app.get("/api/risk/net-impact/{job_id}", tags=["Risk"])
def get_net_impact(job_id: str, days_delayed: float = Query(0.0)):
    conn = get_connection()
    row  = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"Job {job_id} not found")
    return compute_net_impact(dict(row), days_delayed)


@app.get("/api/risk/decision/{job_id}", tags=["Risk"])
def get_decision_recommendation(job_id: str, days_delayed: float = Query(0.0)):
    conn = get_connection()
    row  = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"Job {job_id} not found")
    return recommend_decision(dict(row), days_delayed)


# ────────────────────────────────────────────────────────────────────
# Governance
# ────────────────────────────────────────────────────────────────────

@app.post("/api/governance/lock/{job_id}", tags=["Governance"])
def api_lock(job_id: str, locked_by: str = Query("supervisor")):
    return lock_job(job_id, locked_by)


@app.post("/api/governance/unlock/{job_id}", tags=["Governance"])
def api_unlock(job_id: str, unlocked_by: str = Query("supervisor")):
    return unlock_job(job_id, unlocked_by)


@app.post("/api/governance/override/{job_id}", tags=["Governance"])
def api_override(job_id: str, req: OverrideRequest):
    return manual_override(
        job_id, req.machine_id, req.worker_id,
        req.start_time, req.requested_by,
    )


@app.get("/api/governance/audit", tags=["Governance"])
def api_audit_trail(entity_id: Optional[str] = None, limit: int = Query(50)):
    return get_audit_trail(entity_id, limit)


@app.get("/api/governance/approvals", tags=["Governance"])
def api_get_approvals():
    return get_pending_approvals()


@app.post("/api/governance/approve/{approval_id}", tags=["Governance"])
def api_approve(approval_id: int, approved_by: str = Query("supervisor")):
    return approve_action(approval_id, approved_by)


@app.post("/api/governance/reject/{approval_id}", tags=["Governance"])
def api_reject(approval_id: int, rejected_by: str = Query("supervisor"), reason: str = Query("")):
    return reject_action(approval_id, rejected_by, reason)


@app.post("/api/governance/submit-approval", tags=["Governance"])
def api_submit_approval(
    job_id: str = Body(...),
    action: str = Body(...),
    requested_by: str = Body("system"),
    payload: dict = Body({}),
):
    return submit_for_approval(job_id, action, payload, requested_by)


# ────────────────────────────────────────────────────────────────────
# Simulation & Analytics
# ────────────────────────────────────────────────────────────────────

@app.post("/api/simulation/compare", tags=["Simulation"])
def api_compare_scenarios(job: SimulateJobRequest):
    return compare_scenarios(job.dict())


@app.get("/api/simulation/stability", tags=["Simulation"])
def api_stability():
    return compute_stability_index()


@app.get("/api/simulation/trends", tags=["Simulation"])
def api_trends():
    return utilization_trend()


@app.get("/api/simulation/profit-impact", tags=["Simulation"])
def api_profit_impact():
    return profit_impact_summary()


# ────────────────────────────────────────────────────────────────────
# Versioning / Checkpoints
# ────────────────────────────────────────────────────────────────────

@app.get("/api/versions", tags=["Versioning"])
def api_list_versions():
    return list_versions()


@app.post("/api/versions/checkpoint", tags=["Versioning"])
def api_save_checkpoint(description: str = Query("")):
    return save_checkpoint(description)


@app.post("/api/versions/rollback/{checkpoint_id}", tags=["Versioning"])
def api_rollback(checkpoint_id: int):
    result = rollback_to(checkpoint_id)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@app.get("/api/versions/diff", tags=["Versioning"])
def api_diff(v1: int = Query(...), v2: int = Query(...)):
    return get_diff(v1, v2)


# ────────────────────────────────────────────────────────────────────
# Optimizer Settings
# ────────────────────────────────────────────────────────────────────

@app.get("/api/optimizer/settings", tags=["Optimizer"])
def api_get_weights():
    return get_weights()


@app.put("/api/optimizer/settings", tags=["Optimizer"])
def api_update_weights(weights: WeightsUpdate):
    new_w = {k: v for k, v in weights.dict().items() if v is not None}
    if not new_w:
        raise HTTPException(400, "Provide at least one weight to update.")
    return update_weights(new_w)


# ────────────────────────────────────────────────────────────────────
# Disruption Log
# ────────────────────────────────────────────────────────────────────

@app.get("/api/disruptions", tags=["Analytics"])
def get_disruptions():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM disruptions ORDER BY occurred_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ────────────────────────────────────────────────────────────────────
# Demo Scenarios
# ────────────────────────────────────────────────────────────────────

@app.post("/api/demo/reset", tags=["Demo"])
def demo_reset():
    conn = get_connection()
    for table in ["schedule", "disruptions", "schedule_checkpoints", "audit_log", "approval_queue"]:
        conn.execute(f"DELETE FROM {table}")
    conn.execute("UPDATE jobs SET status='pending', urgency_score=0, completion_pct=0, job_lock_status=0")
    conn.execute("UPDATE machines SET status='available', current_workload=0, maintenance_due=0")
    conn.execute("UPDATE workers SET on_leave=0, assigned_hours=0")
    conn.commit(); conn.close()
    return {"status": "reset"}


@app.post("/api/demo/normal-schedule", tags=["Demo"])
def demo_normal():
    demo_reset()
    return run_schedule()


@app.post("/api/demo/machine-breakdown", tags=["Demo"])
def demo_breakdown():
    demo_reset()
    run_schedule()
    return rescheduler.handle_machine_breakdown("M001")


@app.post("/api/demo/worker-absence", tags=["Demo"])
def demo_absence():
    demo_reset()
    run_schedule()
    return rescheduler.handle_worker_absence("W001")


@app.post("/api/demo/rush-order", tags=["Demo"])
def demo_rush():
    demo_reset()
    run_schedule()
    order = {
        "id":                   "J_RUSH_001",
        "name":                 "URGENT: Customer Order #9901",
        "processing_time":      1.5,
        "due_date":             datetime.now().strftime("%Y-%m-%d"),
        "required_machine_type":"CNC",
        "required_worker_skill":"CNC",
        "profit_margin":        80000,
        "delay_penalty":        5000,
        "reputation_risk":      40.0,
    }
    return rescheduler.handle_rush_order(order)


@app.post("/api/demo/simultaneous", tags=["Demo"])
def demo_simultaneous():
    demo_reset()
    run_schedule()
    rush = {
        "id": "J_RUSH_SIM",
        "name": "URGENT: Rush + Breakdown Scenario",
        "processing_time": 2.0,
        "required_machine_type": "Milling",
        "required_worker_skill": "Milling",
    }
    return rescheduler.handle_simultaneous_event("M003", rush)


# ────────────────────────────────────────────────────────────────────
# Serve Frontend
# ────────────────────────────────────────────────────────────────────

import os
from pathlib import Path

frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    static_path = frontend_path / "static"
    if static_path.exists():
        app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
    def serve_frontend(full_path: str = ""):
        index = frontend_path / "index.html"
        if index.exists():
            return HTMLResponse(index.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>SmartSched AI v2</h1><p>Frontend not found.</p>")
