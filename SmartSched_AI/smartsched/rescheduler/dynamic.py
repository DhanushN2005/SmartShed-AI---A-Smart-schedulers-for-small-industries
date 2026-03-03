"""
SmartSched AI v2 – Dynamic Rescheduler (Upgraded)
===================================================
Key upgrades over v1:
  - Auto-saves checkpoint before EVERY disruptive operation
  - Skips locked jobs during reassignment
  - Handles simultaneous breakdown + rush order
  - Detects continuous overload and recommends overtime / outsourcing
  - Logs all actions to governance audit trail
"""

import json
from datetime import datetime
from database.models import get_connection
from scheduler.engine import SchedulingEngine, compute_urgency_score
from versioning.checkpoint import auto_checkpoint_before_reschedule
from governance.governance import _log_audit


class DynamicRescheduler:
    def __init__(self):
        self.log = []

    # ────────────────────────────────────────────────────────────────
    # Helper: release impacted jobs for re-scheduling
    # ────────────────────────────────────────────────────────────────

    def _release_jobs(self, conn, job_ids: list, new_status: str = "rescheduled"):
        """Remove scheduled entries and reset job status for re-processing."""
        if not job_ids:
            return
        placeholders = ",".join("?" * len(job_ids))
        # Only touch non-locked jobs
        conn.execute(
            f"""DELETE FROM schedule
                WHERE job_id IN ({placeholders})
                  AND status='scheduled'
                  AND job_id NOT IN (
                      SELECT id FROM jobs WHERE job_lock_status=1
                  )""",
            job_ids,
        )
        conn.execute(
            f"""UPDATE jobs SET status=?
                WHERE id IN ({placeholders}) AND job_lock_status=0""",
            [new_status] + job_ids,
        )

    # ────────────────────────────────────────────────────────────────
    # Case 1: Machine Breakdown
    # ────────────────────────────────────────────────────────────────

    def handle_machine_breakdown(self, machine_id: str) -> dict:
        # Auto-save checkpoint before disruption
        cp = auto_checkpoint_before_reschedule("machine_breakdown")

        conn = get_connection()
        conn.execute(
            "UPDATE machines SET status='breakdown', current_workload=0 WHERE id=?",
            (machine_id,),
        )

        impacted = conn.execute(
            """SELECT s.*, j.name as job_name, j.job_lock_status
               FROM schedule s
               JOIN jobs j ON s.job_id = j.id
               WHERE s.machine_id=? AND s.status='scheduled'""",
            (machine_id,),
        ).fetchall()

        impacted_job_ids = [row["job_id"] for row in impacted]
        locked_jobs      = [row["job_id"] for row in impacted if row["job_lock_status"]]

        conn.execute(
            "INSERT INTO disruptions(type,entity_id,description) VALUES('machine_breakdown',?,?)",
            (machine_id,
             f"Machine {machine_id} breakdown. {len(impacted_job_ids)} jobs impacted "
             f"({len(locked_jobs)} locked, cannot be moved)."),
        )

        self._release_jobs(conn, impacted_job_ids)
        conn.commit()
        conn.close()

        _log_audit("MACHINE_BREAKDOWN", "machine", machine_id,
                   details=f"Breakdown. {len(impacted_job_ids)} jobs released for rescheduling.")

        # Overload check
        overload = self._check_overload_after_breakdown(machine_id)

        engine = SchedulingEngine()
        result = engine.run()
        result.update({
            "disruption_type":  "machine_breakdown",
            "machine_id":       machine_id,
            "impacted_jobs":    impacted_job_ids,
            "locked_jobs_kept": locked_jobs,
            "checkpoint":       cp,
            "overload_warning": overload,
        })
        return result

    def _check_overload_after_breakdown(self, broken_machine_id: str) -> dict | None:
        """Detect if remaining machines of same type will be overloaded."""
        conn = get_connection()
        broken = conn.execute(
            "SELECT machine_type FROM machines WHERE id=?", (broken_machine_id,)
        ).fetchone()
        if not broken:
            conn.close()
            return None

        mtype   = broken["machine_type"]
        peers   = conn.execute(
            "SELECT id, name, current_workload, daily_capacity, overload_threshold "
            "FROM machines WHERE machine_type=? AND status='available'",
            (mtype,),
        ).fetchall()
        conn.close()

        overloaded = []
        for p in peers:
            cap   = float(p["daily_capacity"])
            wl    = float(p["current_workload"])
            pct   = (wl / cap * 100) if cap else 0
            if pct >= float(p["overload_threshold"]):
                overloaded.append({"machine_id": p["id"], "name": p["name"], "util_pct": round(pct, 1)})

        if overloaded:
            return {
                "warning": f"After breakdown of {broken_machine_id}, remaining {mtype} machines are overloaded.",
                "overloaded_machines": overloaded,
                "recommendation": "Consider overtime or outsourcing for affected jobs.",
            }
        return None

    # ────────────────────────────────────────────────────────────────
    # Case 2: Worker Absenteeism
    # ────────────────────────────────────────────────────────────────

    def handle_worker_absence(self, worker_id: str) -> dict:
        cp = auto_checkpoint_before_reschedule("worker_absence")

        conn = get_connection()
        conn.execute("UPDATE workers SET on_leave=1 WHERE id=?", (worker_id,))

        impacted = conn.execute(
            """SELECT s.*, j.name as job_name, j.job_lock_status
               FROM schedule s
               JOIN jobs j ON s.job_id = j.id
               WHERE s.worker_id=? AND s.status='scheduled'""",
            (worker_id,),
        ).fetchall()

        impacted_job_ids = [row["job_id"] for row in impacted]
        locked_jobs      = [row["job_id"] for row in impacted if row["job_lock_status"]]

        conn.execute(
            "INSERT INTO disruptions(type,entity_id,description) VALUES('worker_absence',?,?)",
            (worker_id,
             f"Worker {worker_id} absent. {len(impacted_job_ids)} jobs need reassignment."),
        )

        self._release_jobs(conn, impacted_job_ids)
        conn.commit()
        conn.close()

        _log_audit("WORKER_ABSENCE", "worker", worker_id,
                   details=f"Absent. {len(impacted_job_ids)} jobs released.")

        engine = SchedulingEngine()
        result = engine.run()
        result.update({
            "disruption_type":  "worker_absence",
            "worker_id":        worker_id,
            "impacted_jobs":    impacted_job_ids,
            "locked_jobs_kept": locked_jobs,
            "checkpoint":       cp,
        })
        return result

    # ────────────────────────────────────────────────────────────────
    # Case 3: Rush Order
    # ────────────────────────────────────────────────────────────────

    def handle_rush_order(self, job_data: dict) -> dict:
        cp = auto_checkpoint_before_reschedule("rush_order")

        job_data["priority"]    = 5
        job_data["status"]      = "pending"
        job_data["client_priority"] = 5
        job_data["contractual"] = 1
        if not job_data.get("due_date"):
            job_data["due_date"] = datetime.now().strftime("%Y-%m-%d")

        urgency = compute_urgency_score(job_data)
        job_data["urgency_score"] = urgency

        conn = get_connection()
        conn.execute(
            """INSERT OR REPLACE INTO jobs
               (id, name, processing_time, due_date, priority,
                required_machine_type, required_worker_skill, precedence,
                status, urgency_score, profit_margin, delay_penalty,
                client_priority, contractual, reputation_risk, material_available)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job_data["id"], job_data["name"],
                job_data["processing_time"], job_data["due_date"], 5,
                job_data["required_machine_type"], job_data["required_worker_skill"],
                job_data.get("precedence"),
                "pending", urgency,
                job_data.get("profit_margin",  50000),
                job_data.get("delay_penalty",  1000),
                5, 1,
                job_data.get("reputation_risk", 30),
                job_data.get("material_available", 1),
            ),
        )
        conn.execute(
            "INSERT INTO disruptions(type,entity_id,description) VALUES('rush_order',?,?)",
            (job_data["id"], f"Rush order {job_data['id']} inserted with max priority."),
        )
        conn.commit()
        conn.close()

        _log_audit("RUSH_ORDER_INSERTED", "job", job_data["id"],
                   details=f"Rush job '{job_data['name']}' inserted with priority 5.")

        engine = SchedulingEngine()
        result = engine.run()
        result.update({
            "disruption_type": "rush_order",
            "rush_job_id":     job_data["id"],
            "checkpoint":      cp,
        })
        return result

    # ────────────────────────────────────────────────────────────────
    # Case 4: Simultaneous Breakdown + Rush Order
    # ────────────────────────────────────────────────────────────────

    def handle_simultaneous_event(self, machine_id: str, rush_job: dict) -> dict:
        """
        Handle the hardest edge case: machine breaks down at the same time
        a rush order arrives. Steps:
        1. Process breakdown (checkpoint already saved)
        2. Insert rush order into the re-run
        3. Single scheduler run handles both
        """
        cp = auto_checkpoint_before_reschedule("simultaneous_breakdown_rush")

        conn = get_connection()
        conn.execute(
            "UPDATE machines SET status='breakdown', current_workload=0 WHERE id=?",
            (machine_id,),
        )
        impacted = conn.execute(
            """SELECT s.job_id FROM schedule s
               JOIN jobs j ON s.job_id=j.id
               WHERE s.machine_id=? AND s.status='scheduled' AND j.job_lock_status=0""",
            (machine_id,),
        ).fetchall()
        impacted_ids = [r["job_id"] for r in impacted]
        self._release_jobs(conn, impacted_ids)

        # Insert rush job
        rush_job.update({"priority": 5, "status": "pending", "client_priority": 5})
        urgency = compute_urgency_score(rush_job)
        conn.execute(
            """INSERT OR REPLACE INTO jobs
               (id, name, processing_time, due_date, priority,
                required_machine_type, required_worker_skill,
                status, urgency_score, material_available)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (rush_job["id"], rush_job["name"], rush_job["processing_time"],
             rush_job.get("due_date", datetime.now().strftime("%Y-%m-%d")),
             5, rush_job["required_machine_type"], rush_job["required_worker_skill"],
             "pending", urgency, rush_job.get("material_available", 1)),
        )
        conn.execute(
            "INSERT INTO disruptions(type,entity_id,description) VALUES('simultaneous_event',?,?)",
            (machine_id, f"Breakdown+Rush: machine {machine_id} down, rush job {rush_job['id']} inserted."),
        )
        conn.commit()
        conn.close()

        engine = SchedulingEngine()
        result = engine.run()
        result.update({
            "disruption_type":  "simultaneous_breakdown_rush",
            "machine_id":       machine_id,
            "rush_job_id":      rush_job["id"],
            "impacted_jobs":    impacted_ids,
            "checkpoint":       cp,
        })
        return result

    # ────────────────────────────────────────────────────────────────
    # Restore
    # ────────────────────────────────────────────────────────────────

    def restore_machine(self, machine_id: str) -> dict:
        conn = get_connection()
        conn.execute(
            "UPDATE machines SET status='available', maintenance_due=0 WHERE id=?",
            (machine_id,),
        )
        conn.execute(
            "UPDATE disruptions SET resolved=1, resolved_at=datetime('now') "
            "WHERE entity_id=? AND type='machine_breakdown' AND resolved=0",
            (machine_id,),
        )
        conn.commit()
        conn.close()
        _log_audit("MACHINE_RESTORED", "machine", machine_id)
        return {"status": "restored", "machine_id": machine_id}

    def restore_worker(self, worker_id: str) -> dict:
        conn = get_connection()
        conn.execute("UPDATE workers SET on_leave=0 WHERE id=?", (worker_id,))
        conn.execute(
            "UPDATE disruptions SET resolved=1, resolved_at=datetime('now') "
            "WHERE entity_id=? AND type='worker_absence' AND resolved=0",
            (worker_id,),
        )
        conn.commit()
        conn.close()
        _log_audit("WORKER_RESTORED", "worker", worker_id)
        return {"status": "restored", "worker_id": worker_id}
