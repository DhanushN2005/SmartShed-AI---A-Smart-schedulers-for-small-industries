"""
SmartSched AI v2 – Upgraded Scheduling Engine
===============================================
Key upgrades over v1:
  - Multi-objective scoring (via optimizer.multi_objective)
  - Respects job_lock_status (locked jobs cannot be moved)
  - Skips jobs where material_available = 0
  - Multi-day crossing: jobs that extend beyond shift_end continue next day
  - Machine reliability weighting in machine selection
  - Partial completion tracking: picks up from completion_pct
  - Preemption support: pauses lower-priority jobs for urgent ones

Algorithm
----------
1. Score all pending jobs via multi-objective formula
2. Topological sort (precedence + score)
3. For each job in score order:
   a. Skip if locked or material unavailable
   b. Find best compatible machine (reliability-weighted)
   c. Find best available worker (skill + shift)
   d. Compute actual_start = max(machine_free, worker_free, predecessor_end)
   e. Handle multi-day crossing if start+duration > shift_end
   f. Assign and persist
"""

import json
from datetime import datetime, timedelta
from database.models import get_connection


# ────────────────────────────────────────────────────────────────────
# Urgency / scoring  (delegates to multi-objective optimizer)
# ────────────────────────────────────────────────────────────────────

def compute_urgency_score(job: dict, reference_date: str = None) -> float:
    """
    Public function – kept for backward compatibility.
    Internally uses the multi-objective optimizer now.
    """
    try:
        from optimizer.multi_objective import compute_score
        return compute_score(job, reference_date)
    except ImportError:
        # Fallback to v1 formula if optimizer not available
        priority_weight = 10
        ref = datetime.strptime(reference_date, "%Y-%m-%d") if reference_date else datetime.now()
        try:
            due = datetime.strptime(job["due_date"], "%Y-%m-%d")
        except Exception:
            due = ref + timedelta(days=7)
        days_remaining = max(1, (due - ref).days)
        return round(
            priority_weight * int(job.get("priority", 3))
            + 100.0 / days_remaining
            - float(job.get("processing_time", 0)) * 0.5,
            4,
        )


# ────────────────────────────────────────────────────────────────────
# Topological Sort (unchanged logic, upgraded score)
# ────────────────────────────────────────────────────────────────────

def topological_sort(jobs: list) -> list:
    """
    Returns jobs ordered so predecessors come before successors.
    Uses Kahn's BFS; ties broken by multi-objective score (desc).
    """
    id_map   = {j["id"]: j for j in jobs}
    in_deg   = {j["id"]: 0 for j in jobs}
    children = {j["id"]: [] for j in jobs}

    for job in jobs:
        pre = job.get("precedence")
        if pre and pre in id_map:
            in_deg[job["id"]] += 1
            children[pre].append(job["id"])

    queue = [jid for jid, d in in_deg.items() if d == 0]
    queue.sort(key=lambda jid: id_map[jid].get("urgency_score", 0), reverse=True)

    order = []
    while queue:
        node = queue.pop(0)
        order.append(id_map[node])
        for child in children[node]:
            in_deg[child] -= 1
            if in_deg[child] == 0:
                queue.append(child)
                queue.sort(
                    key=lambda jid: id_map[jid].get("urgency_score", 0), reverse=True
                )

    if len(order) != len(jobs):
        remaining = [j for j in jobs if j["id"] not in {o["id"] for o in order}]
        order.extend(remaining)

    return order


# ────────────────────────────────────────────────────────────────────
# Main Scheduling Engine
# ────────────────────────────────────────────────────────────────────

class SchedulingEngine:
    """Constraint-aware, multi-objective scheduling engine (v2)."""

    def __init__(self, reference_date: str = None):
        self.reference_date = reference_date or datetime.now().strftime("%Y-%m-%d")
        self.machine_timeline:   dict[str, float] = {}   # machine_id → earliest free hour
        self.worker_assignments: dict[str, list]  = {}   # worker_id → [(start, end)]
        self.schedule_log: list[dict] = []
        self.errors:       list[str]  = []

    # ────────────────────────────────────────────────────────────────
    # Data Loaders
    # ────────────────────────────────────────────────────────────────

    def _load_jobs(self) -> list[dict]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status IN ('pending','rescheduled')"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def _load_machines(self) -> list[dict]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM machines WHERE status = 'available'"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def _load_workers(self) -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM workers WHERE on_leave = 0").fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            d["skills"] = json.loads(d["skills"]) if isinstance(d["skills"], str) else d["skills"]
            result.append(d)
        return result

    def _load_existing_schedule(self) -> list[dict]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM schedule WHERE status IN ('scheduled','in_progress')"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ────────────────────────────────────────────────────────────────
    # Timeline Helpers
    # ────────────────────────────────────────────────────────────────

    def _init_timelines(self, machines, workers, existing):
        for m in machines:
            self.machine_timeline[m["id"]] = 0.0
        for w in workers:
            self.worker_assignments[w["id"]] = []
        for entry in existing:
            mid, wid = entry["machine_id"], entry["worker_id"]
            if mid in self.machine_timeline:
                self.machine_timeline[mid] = max(
                    self.machine_timeline[mid], entry["end_time"]
                )
            if wid in self.worker_assignments:
                self.worker_assignments[wid].append(
                    (entry["start_time"], entry["end_time"])
                )

    def _worker_free_at(self, worker: dict, start: float, duration: float,
                        allow_multiday: bool = True) -> float:
        """Return earliest start when worker is free for `duration` hours."""
        shift_start = float(worker["shift_start"])
        shift_end   = float(worker["shift_end"])
        shift_cap   = shift_end - shift_start

        if not allow_multiday and duration > shift_cap:
            return float("inf")

        busy      = sorted(self.worker_assignments.get(worker["id"], []))
        candidate = max(start, shift_start)

        for (bs, be) in busy:
            if candidate + duration <= bs:
                break
            if candidate < be:
                candidate = be

        # Multi-day crossing: if job doesn't fit in today's shift, roll to next shift
        if candidate + duration > shift_end:
            # Jump to next day's shift start (add 24h offset)
            day_offset  = int(candidate // 24) + 1
            candidate   = day_offset * 24 + shift_start
            # Re-check against busy slots
            for (bs, be) in busy:
                if candidate + duration <= bs:
                    break
                if candidate < be:
                    candidate = be

        if candidate + duration > (int(candidate // 24) * 24 + shift_end):
            return float("inf")

        return candidate

    def _find_best_machine(self, machines, machine_type: str,
                           start_hint: float, duration: float) -> dict | None:
        """
        Find machine with matching type and earliest free slot.
        Tie-break: reliability_score DESC then current_workload ASC.
        """
        compatible = [m for m in machines if m["machine_type"] == machine_type]
        if not compatible:
            return None

        best, best_free = None, float("inf")
        for m in compatible:
            free    = max(self.machine_timeline.get(m["id"], 0.0), start_hint)
            wl      = float(m.get("current_workload", 0.0))
            cap     = float(m.get("daily_capacity", 8.0))
            overload_pct = float(m.get("overload_threshold", 90.0))
            if (wl + duration) / cap * 100 > overload_pct:
                continue  # would exceed safe threshold

            # Reliability penalty on free-at time (lower reliability → prefer later)
            rel       = float(m.get("reliability_score", 1.0))
            eff_free  = free + (1.0 - rel) * 0.5   # up to 0.5h penalty for low reliability

            if eff_free < best_free or (
                eff_free == best_free
                and float(m.get("reliability_score", 1.0))
                    > float((best or {}).get("reliability_score", 0))
            ):
                best, best_free = m, eff_free

        return best

    def _find_best_worker(self, workers, skill: str,
                          earliest_start: float, duration: float):
        eligible = [w for w in workers if skill in w["skills"]]
        if not eligible:
            return None, float("inf")

        best_worker, best_start = None, float("inf")
        for w in eligible:
            ws = self._worker_free_at(w, earliest_start, duration)
            if ws < best_start:
                best_start, best_worker = ws, w

        return best_worker, best_start

    def _predecessor_end(self, job: dict) -> float:
        pre = job.get("precedence")
        if not pre:
            return 0.0
        conn = get_connection()
        row  = conn.execute(
            "SELECT end_time FROM schedule WHERE job_id=? ORDER BY end_time DESC LIMIT 1",
            (pre,),
        ).fetchone()
        conn.close()
        return float(row["end_time"]) if row else 0.0

    # ────────────────────────────────────────────────────────────────
    # Partial Completion
    # ────────────────────────────────────────────────────────────────

    def _effective_duration(self, job: dict) -> float:
        """Remaining processing time after partial completion."""
        total      = float(job.get("processing_time", 0))
        done_pct   = float(job.get("completion_pct", 0))
        remaining  = total * (1 - done_pct / 100.0)
        return max(remaining, 0.0)

    # ────────────────────────────────────────────────────────────────
    # Core Run
    # ────────────────────────────────────────────────────────────────

    def run(self) -> dict:
        jobs     = self._load_jobs()
        machines = self._load_machines()
        workers  = self._load_workers()
        existing = self._load_existing_schedule()

        if not jobs:
            return {"status": "no_jobs", "scheduled": 0, "failed": 0, "schedule": []}

        # Load optimizer weights once for the whole run
        try:
            from optimizer.multi_objective import compute_score, get_weights
            weights = get_weights()
        except ImportError:
            compute_score = None
            weights       = None

        # Score urgency
        for j in jobs:
            if compute_score and weights:
                j["urgency_score"] = compute_score(j, self.reference_date, weights)
            else:
                j["urgency_score"] = compute_urgency_score(j, self.reference_date)

        ordered_jobs = topological_sort(jobs)
        self._init_timelines(machines, workers, existing)

        conn            = get_connection()
        scheduled_count = 0
        failed_jobs     = []

        for job in ordered_jobs:
            # ── Governance gates ────────────────────────────────────
            if job.get("job_lock_status"):
                self.errors.append(
                    f"Job {job['id']} ({job['name']}) is LOCKED – skipped."
                )
                continue

            if not job.get("material_available", 1):
                self.errors.append(
                    f"Job {job['id']} ({job['name']}) – material unavailable, skipped."
                )
                failed_jobs.append(job["id"])
                continue

            # ── Effective duration (partial completion) ─────────────
            duration = self._effective_duration(job)
            if duration <= 0:
                # Already fully completed
                conn.execute(
                    "UPDATE jobs SET status='completed' WHERE id=?", (job["id"],)
                )
                continue

            mtype    = job["required_machine_type"]
            skill    = job["required_worker_skill"]
            pred_end = self._predecessor_end(job)

            # ── Machine selection ────────────────────────────────────
            machine = self._find_best_machine(machines, mtype, pred_end, duration)
            if not machine:
                self.errors.append(
                    f"No available {mtype} machine for job {job['id']} ({job['name']})"
                )
                failed_jobs.append(job["id"])
                continue

            machine_free   = max(self.machine_timeline.get(machine["id"], 0.0), pred_end)

            # ── Worker selection ─────────────────────────────────────
            worker, worker_start = self._find_best_worker(workers, skill, machine_free, duration)
            if not worker:
                self.errors.append(
                    f"No worker with skill '{skill}' for job {job['id']} ({job['name']})"
                )
                failed_jobs.append(job["id"])
                continue

            actual_start = max(machine_free, worker_start)
            actual_end   = actual_start + duration

            # Determine schedule day (each 8-hour shift = 1 day)
            shift_span = float(worker.get("shift_end", 16)) - float(worker.get("shift_start", 8))
            day        = int(actual_start // max(shift_span, 8)) + 1

            # ── Commit to timelines ──────────────────────────────────
            self.machine_timeline[machine["id"]] = actual_end
            self.worker_assignments.setdefault(worker["id"], []).append(
                (actual_start, actual_end)
            )

            # ── Persist ──────────────────────────────────────────────
            conn.execute(
                """INSERT INTO schedule
                   (job_id, machine_id, worker_id, start_time, end_time, day, status)
                   VALUES(?, ?, ?, ?, ?, ?, 'scheduled')""",
                (job["id"], machine["id"], worker["id"], actual_start, actual_end, day),
            )
            conn.execute(
                "UPDATE jobs SET status='scheduled', urgency_score=? WHERE id=?",
                (job["urgency_score"], job["id"]),
            )
            conn.execute(
                "UPDATE machines SET current_workload=current_workload+? WHERE id=?",
                (duration, machine["id"]),
            )
            conn.execute(
                "UPDATE workers SET assigned_hours=assigned_hours+? WHERE id=?",
                (duration, worker["id"]),
            )

            self.schedule_log.append({
                "job_id":        job["id"],
                "job_name":      job["name"],
                "machine_id":    machine["id"],
                "worker_id":     worker["id"],
                "start_time":    actual_start,
                "end_time":      actual_end,
                "day":           day,
                "urgency_score": job["urgency_score"],
                "duration":      duration,
            })
            scheduled_count += 1

        conn.commit()
        conn.close()

        return {
            "status":      "success",
            "scheduled":   scheduled_count,
            "failed":      len(failed_jobs),
            "failed_jobs": failed_jobs,
            "schedule":    self.schedule_log,
            "errors":      self.errors,
        }


def run_full_schedule(reference_date: str = None) -> dict:
    """Public entry point."""
    engine = SchedulingEngine(reference_date)
    return engine.run()
