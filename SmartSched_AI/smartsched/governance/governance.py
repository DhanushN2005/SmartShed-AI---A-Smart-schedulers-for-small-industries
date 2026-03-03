"""
SmartSched AI v2 – Human Governance Layer
==========================================
Implements:
  - Job locking (prevents rescheduling of committed jobs)
  - Manual override (supervisor assigns job to specific machine/worker)
  - Approval workflow for high-risk reshuffles
  - Full audit trail logging
"""

from datetime import datetime
from database.models import get_connection


# ────────────────────────────────────────────────────────────────────
# Audit Trail
# ────────────────────────────────────────────────────────────────────

def _log_audit(action: str, entity_type: str, entity_id: str,
               performed_by: str = "system", details: str = ""):
    conn = get_connection()
    conn.execute(
        """INSERT INTO audit_log(action, entity_type, entity_id, performed_by, details)
           VALUES(?, ?, ?, ?, ?)""",
        (action, entity_type, entity_id, performed_by, details),
    )
    conn.commit()
    conn.close()


def get_audit_trail(entity_id: str = None, limit: int = 100) -> list:
    """Return audit log entries, optionally filtered by entity_id."""
    conn = get_connection()
    if entity_id:
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE entity_id=? ORDER BY occurred_at DESC LIMIT ?",
            (entity_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY occurred_at DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ────────────────────────────────────────────────────────────────────
# Job Locking
# ────────────────────────────────────────────────────────────────────

def lock_job(job_id: str, locked_by: str = "supervisor") -> dict:
    """
    Lock a job so it cannot be moved by the auto-scheduler.
    Locked jobs are skipped during dynamic rescheduling.
    """
    conn = get_connection()
    row = conn.execute("SELECT id, name FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        conn.close()
        return {"error": f"Job {job_id} not found"}

    conn.execute(
        """UPDATE jobs
           SET job_lock_status=1, locked_by=?, locked_at=datetime('now')
           WHERE id=?""",
        (locked_by, job_id),
    )
    conn.commit()
    conn.close()

    _log_audit("JOB_LOCKED", "job", job_id, locked_by,
               f"Job '{row['name']}' locked by {locked_by}.")
    return {"status": "locked", "job_id": job_id, "locked_by": locked_by}


def unlock_job(job_id: str, unlocked_by: str = "supervisor") -> dict:
    """Remove the lock from a job."""
    conn = get_connection()
    row = conn.execute("SELECT id, name FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        conn.close()
        return {"error": f"Job {job_id} not found"}

    conn.execute(
        "UPDATE jobs SET job_lock_status=0, locked_by=NULL, locked_at=NULL WHERE id=?",
        (job_id,),
    )
    conn.commit()
    conn.close()

    _log_audit("JOB_UNLOCKED", "job", job_id, unlocked_by,
               f"Job '{row['name']}' unlocked by {unlocked_by}.")
    return {"status": "unlocked", "job_id": job_id}


# ────────────────────────────────────────────────────────────────────
# Manual Override
# ────────────────────────────────────────────────────────────────────

def manual_override(job_id: str, machine_id: str, worker_id: str,
                    start_time: float, requested_by: str = "supervisor") -> dict:
    """
    Directly assign a job to a specific machine+worker+start time.
    Bypasses the scheduler; the assignment is written directly to schedule.
    An audit entry is created for traceability.
    """
    conn = get_connection()
    job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        conn.close()
        return {"error": f"Job {job_id} not found"}

    machine = conn.execute("SELECT * FROM machines WHERE id=?", (machine_id,)).fetchone()
    worker  = conn.execute("SELECT * FROM workers WHERE id=?", (worker_id,)).fetchone()
    if not machine or not worker:
        conn.close()
        return {"error": "Invalid machine_id or worker_id"}

    job = dict(job)
    end_time = start_time + float(job["processing_time"])

    # Remove any existing scheduled entry for this job
    conn.execute(
        "DELETE FROM schedule WHERE job_id=? AND status='scheduled'", (job_id,)
    )

    # Insert override
    conn.execute(
        """INSERT INTO schedule(job_id, machine_id, worker_id, start_time, end_time, status)
           VALUES(?, ?, ?, ?, ?, 'scheduled')""",
        (job_id, machine_id, worker_id, start_time, end_time),
    )
    conn.execute("UPDATE jobs SET status='scheduled' WHERE id=?", (job_id,))
    
    # Updated: Sync workloads
    duration = end_time - start_time
    conn.execute("UPDATE machines SET current_workload = current_workload + ? WHERE id=?", (duration, machine_id))
    conn.execute("UPDATE workers SET assigned_hours = assigned_hours + ? WHERE id=?", (duration, worker_id))
    
    conn.commit()
    conn.close()

    _log_audit(
        "MANUAL_OVERRIDE", "job", job_id, requested_by,
        f"Job '{job['name']}' manually assigned to machine {machine_id}, "
        f"worker {worker_id}, start={start_time:.2f}h by {requested_by}.",
    )

    return {
        "status":       "overridden",
        "job_id":       job_id,
        "machine_id":   machine_id,
        "worker_id":    worker_id,
        "start_time":   start_time,
        "end_time":     end_time,
        "requested_by": requested_by,
    }


# ────────────────────────────────────────────────────────────────────
# Approval Workflow
# ────────────────────────────────────────────────────────────────────

def submit_for_approval(job_id: str, action: str,
                        payload: dict = None, requested_by: str = "system") -> dict:
    """Push a high-risk action to the approval queue for supervisor review."""
    import json
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO approval_queue(job_id, action, payload, requested_by)
           VALUES(?, ?, ?, ?)""",
        (job_id, action, json.dumps(payload or {}), requested_by),
    )
    approval_id = cur.lastrowid
    conn.commit()
    conn.close()

    _log_audit("APPROVAL_REQUESTED", "job", job_id, requested_by,
               f"Action '{action}' submitted for approval (approval_id={approval_id}).")

    return {
        "approval_id":   approval_id,
        "job_id":        job_id,
        "action":        action,
        "status":        "pending",
        "requested_by":  requested_by,
    }


def get_pending_approvals() -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM approval_queue WHERE status='pending' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def approve_action(approval_id: int, approved_by: str = "supervisor") -> dict:
    """Approve a queued action and execute it."""
    import json
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM approval_queue WHERE id=?", (approval_id,)
    ).fetchone()
    if not row:
        conn.close()
        return {"error": f"Approval {approval_id} not found"}

    entry = dict(row)
    if entry["status"] != "pending":
        conn.close()
        return {"error": f"Approval already {entry['status']}"}

    conn.execute(
        """UPDATE approval_queue
           SET status='approved', reviewed_by=?, reviewed_at=datetime('now')
           WHERE id=?""",
        (approved_by, approval_id),
    )
    conn.commit()
    conn.close()

    _log_audit("APPROVAL_GRANTED", "job", entry["job_id"], approved_by,
               f"Action '{entry['action']}' approved (approval_id={approval_id}).")

    # Execute the approved action
    payload = json.loads(entry.get("payload") or "{}")
    result  = _execute_approved_action(entry["action"], entry["job_id"], payload)

    return {
        "approval_id":  approval_id,
        "status":       "approved",
        "approved_by":  approved_by,
        "execution":    result,
    }


def reject_action(approval_id: int, rejected_by: str = "supervisor",
                  reason: str = "") -> dict:
    """Reject a queued action."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM approval_queue WHERE id=?", (approval_id,)
    ).fetchone()
    if not row:
        conn.close()
        return {"error": f"Approval {approval_id} not found"}

    entry = dict(row)
    conn.execute(
        """UPDATE approval_queue
           SET status='rejected', reviewed_by=?, reviewed_at=datetime('now'), reason=?
           WHERE id=?""",
        (rejected_by, reason, approval_id),
    )
    conn.commit()
    conn.close()

    _log_audit("APPROVAL_REJECTED", "job", entry["job_id"], rejected_by,
               f"Action '{entry['action']}' rejected. Reason: {reason}")

    return {"approval_id": approval_id, "status": "rejected", "reason": reason}


def _execute_approved_action(action: str, job_id: str, payload: dict) -> dict:
    """Dispatch approved actions to the relevant handler."""
    if action == "RESCHEDULE":
        from scheduler.engine import run_full_schedule
        return run_full_schedule()
    elif action == "MANUAL_OVERRIDE":
        return manual_override(
            job_id,
            payload.get("machine_id", ""),
            payload.get("worker_id", ""),
            payload.get("start_time", 0),
            requested_by="approval_system",
        )
    return {"info": f"Action '{action}' acknowledged but no handler registered."}
