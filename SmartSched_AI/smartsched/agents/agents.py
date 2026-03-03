"""
SmartSched AI – Agent-Based Extension
========================================
Simple multi-agent abstraction for negotiation-style scheduling.
Each agent evaluates constraints from its own perspective and
proposes allocations. The SupervisorAgent arbitrates.

Agents
------
- MachineAgent    : evaluates if a machine can accept a job
- WorkerAgent     : evaluates if a worker can accept a job
- JobAgent        : advocates for its job's urgency
- SupervisorAgent : collects bids, selects best allocation
"""

import json
from database.models import get_connection


class MachineAgent:
    """Represents a single machine. Evaluates job feasibility."""

    def __init__(self, machine_data: dict):
        self.data = machine_data
        self.free_at = 0.0  # set externally

    @property
    def id(self):
        return self.data["id"]

    def can_accept(self, job: dict, earliest_start: float) -> dict:
        """
        Returns a bid dict if machine can accept the job, else None.
        Bid includes: machine_id, proposed_start, proposed_end, load_after.
        """
        if self.data["status"] != "available":
            return None
        if self.data["machine_type"] != job["required_machine_type"]:
            return None

        proposed_start = max(self.free_at, earliest_start)
        proposed_end = proposed_start + float(job["processing_time"])

        remaining = self.data["daily_capacity"] - self.data["current_workload"]
        if float(job["processing_time"]) > remaining:
            return None

        load_pct = (float(job["processing_time"])) / \
                   self.data["daily_capacity"] * 100

        return {
            "machine_id": self.id,
            "proposed_start": proposed_start,
            "proposed_end": proposed_end,
            "load_after_pct": round(load_pct, 1),
            "current_workload": self.data["current_workload"],
        }

    def accept_bid(self, duration: float, start: float):
        """Update internal state after bid is accepted."""
        self.free_at = start + duration
        self.data["current_workload"] += duration


class WorkerAgent:
    """Represents a single worker. Evaluates skill and shift availability."""

    def __init__(self, worker_data: dict):
        self.data = worker_data
        self.assignments = []

    @property
    def id(self):
        return self.data["id"]

    def _busy_at(self, start: float, duration: float) -> bool:
        for (s, e) in self.assignments:
            if not (start + duration <= s or start >= e):
                return True
        return False

    def can_accept(self, job: dict, earliest_start: float) -> dict | None:
        """Returns a bid dict if worker can cover the job."""
        skills = self.data["skills"]
        if isinstance(skills, str):
            skills = json.loads(skills)

        if job["required_worker_skill"] not in skills:
            return None
        if self.data["on_leave"]:
            return None

        shift_start = float(self.data["shift_start"])
        shift_end = float(self.data["shift_end"])
        duration = float(job["processing_time"])

        candidate = max(earliest_start, shift_start)
        # Find first slot in shift
        for (bs, be) in sorted(self.assignments):
            if candidate + duration <= bs:
                break
            if candidate < be:
                candidate = be

        if candidate + duration > shift_end:
            return None

        util = (duration) / (shift_end - shift_start) * 100

        return {
            "worker_id": self.id,
            "worker_name": self.data["name"],
            "proposed_start": candidate,
            "utilization_after_pct": round(util, 1),
        }

    def accept_bid(self, start: float, end: float):
        self.assignments.append((start, end))
        self.data["assigned_hours"] += (end - start)


class JobAgent:
    """Represents a job's interests – mainly urgency advocacy."""

    def __init__(self, job_data: dict):
        self.data = job_data

    @property
    def id(self):
        return self.data["id"]

    def urgency_report(self) -> dict:
        return {
            "job_id": self.id,
            "name": self.data["name"],
            "urgency_score": self.data.get("urgency_score", 0),
            "priority": self.data["priority"],
            "due_date": self.data["due_date"],
            "processing_time": self.data["processing_time"],
        }


class SupervisorAgent:
    """
    Orchestrates negotiation:
    1. JobAgents report urgency.
    2. MachineAgents bid on each job.
    3. WorkerAgents bid on each job.
    4. SupervisorAgent selects best (earliest start) allocation.
    """

    def __init__(self, machines: list[dict], workers: list[dict]):
        self.machine_agents = [MachineAgent(m) for m in machines]
        self.worker_agents = [WorkerAgent(w) for w in workers]
        self.negotiation_log = []

    def negotiate(self, jobs: list[dict]) -> list[dict]:
        """
        Run negotiation for a list of jobs (already sorted by urgency).
        Returns list of allocation dicts.
        """
        allocations = []

        for job in jobs:
            ja = JobAgent(job)
            urgency = ja.urgency_report()
            pred_end = self._predecessor_end(job)

            # Collect machine bids
            machine_bids = []
            for ma in self.machine_agents:
                bid = ma.can_accept(job, pred_end)
                if bid:
                    machine_bids.append((ma, bid))

            # Collect worker bids for each machine bid
            best_alloc = None
            best_start = float("inf")

            for (ma, m_bid) in machine_bids:
                worker_bids = []
                for wa in self.worker_agents:
                    w_bid = wa.can_accept(job, m_bid["proposed_start"])
                    if w_bid:
                        worker_bids.append((wa, w_bid))

                for (wa, w_bid) in worker_bids:
                    actual_start = max(m_bid["proposed_start"], w_bid["proposed_start"])
                    if actual_start < best_start:
                        best_start = actual_start
                        best_alloc = {
                            "job_id": job["id"],
                            "job_name": job["name"],
                            "machine_agent": ma,
                            "worker_agent": wa,
                            "machine_bid": m_bid,
                            "worker_bid": w_bid,
                            "actual_start": actual_start,
                            "actual_end": actual_start + float(job["processing_time"]),
                            "urgency": urgency,
                        }

            if best_alloc:
                best_alloc["machine_agent"].accept_bid(
                    float(job["processing_time"]), best_alloc["actual_start"]
                )
                best_alloc["worker_agent"].accept_bid(
                    best_alloc["actual_start"], best_alloc["actual_end"]
                )
                allocations.append(best_alloc)
                self.negotiation_log.append({
                    "job_id": job["id"],
                    "status": "allocated",
                    "machine": best_alloc["machine_bid"]["machine_id"],
                    "worker": best_alloc["worker_bid"]["worker_id"],
                    "start": best_alloc["actual_start"],
                    "end": best_alloc["actual_end"],
                })
            else:
                self.negotiation_log.append({
                    "job_id": job["id"],
                    "status": "unallocated",
                    "reason": "No compatible machine+worker pair found",
                })

        return allocations

    def _predecessor_end(self, job: dict) -> float:
        pre = job.get("precedence")
        if not pre:
            return 0.0
        conn = get_connection()
        row = conn.execute(
            "SELECT end_time FROM schedule WHERE job_id=? ORDER BY end_time DESC LIMIT 1",
            (pre,),
        ).fetchone()
        conn.close()
        return float(row["end_time"]) if row else 0.0

    def get_negotiation_summary(self) -> list[dict]:
        return self.negotiation_log


def run_agent_schedule(machines: list, workers: list, jobs: list) -> dict:
    """Entry point for agent-based scheduling run."""
    from scheduler.engine import topological_sort, compute_urgency_score
    from datetime import datetime

    ref = datetime.now().strftime("%Y-%m-%d")
    for j in jobs:
        j["urgency_score"] = compute_urgency_score(j, ref)

    ordered = topological_sort(jobs)
    supervisor = SupervisorAgent(machines, workers)
    allocations = supervisor.negotiate(ordered)

    return {
        "allocations": len(allocations),
        "log": supervisor.get_negotiation_summary(),
        "details": [
            {
                "job_id": a["job_id"],
                "job_name": a["job_name"],
                "machine_id": a["machine_bid"]["machine_id"],
                "worker_id": a["worker_bid"]["worker_id"],
                "worker_name": a["worker_bid"]["worker_name"],
                "start": a["actual_start"],
                "end": a["actual_end"],
                "machine_load_pct": a["machine_bid"]["load_after_pct"],
                "worker_util_pct": a["worker_bid"]["utilization_after_pct"],
            }
            for a in allocations
        ],
    }
