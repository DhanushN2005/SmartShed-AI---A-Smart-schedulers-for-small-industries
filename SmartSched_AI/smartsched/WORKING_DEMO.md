# 🕹️ SmartSched AI v2: Working Demo Guide
*Step-by-step Technical Walkthrough*

This guide explains the "Cause and Effect" of the main system features. Use this to understand what happens under the hood when you interact with the dashboard.

---

### 1. The Optimization Loop
*   **Action**: Click **"▶ Run Schedule"** in the Schedule tab.
*   **Hits**: `POST /api/schedule/run`
*   **What Happens**:
    1.  The backend clears all *unlocked* jobs from the schedule table.
    2.  The `run_full_schedule` engine calculates the **Urgency Score** for every pending job based on the weights in the **Optimizer** tab.
    3.  Jobs are assigned to compatible machines and workers based on lowest current workload.
    4.  **UI Benefit**: The schedule table populates instantly with new timelines and calculated Profit margins.

### 2. Job Locking (Governance)
*   **Action**: Click the **"Lock"** button on a specific row in the Schedule.
*   **Hits**: `POST /api/governance/lock/{job_id}?locked_by=supervisor`
*   **What Happens**:
    1.  The `job_lock_status` in the database is set to `1`.
    2.  An entry is added to the **Audit Log** (`audit_log` table).
    3.  **UI Benefit**: The "Locked Jobs" KPI card increases. If you click "Run Schedule" again, this job’s machine and time slot remain **frozen**, and other jobs are scheduled *around* it.

### 3. Machine Breakdown (Disruption)
*   **Action**: Click **"💥 Demo: Breakdown"** in the Schedule tab.
*   **Hits**: `POST /api/demo/machine-breakdown`
*   **What Happens**:
    1.  A random machine is set to `status='breakdown'`.
    2.  A new entry is added to the `disruptions` table.
    3.  The system identifies all jobs scheduled on that machine and sets them back to `pending`.
    4.  The system automatically triggers a "partial re-run" to move those jobs to other machines.
    5.  **UI Benefit**: The **Disruption Log** updates instantly with a red "🔴 Open" tag.

### 4. What-If Simulation
*   **Action**: In the **Simulation** tab, choose a Preset (e.g., Automotive) and click **"Run Simulation"**.
*   **Hits**: `POST /api/simulation/compare`
*   **What Happens**:
    1.  The `scenario_engine.py` creates two virtual "Future States":
        *   **State A (Accept)**: Adds the job and estimates profit vs. makespan delay.
        *   **State B (Reject)**: Calculates the ₹ cost of the lost opportunity.
    2.  The AI recommends an action based on which state has a higher **Net Factory Impact**.
    3.  **UI Benefit**: You get two side-by-side cards showing exactly how much ₹ you gain or lose by making that decision.

### 5. Checkpointing & Rollback
*   **Action**: Click **"💾 Save Checkpoint"** in the Versions tab.
*   **Hits**: `POST /api/versions/checkpoint?description=...`
*   **What Happens**:
    1.  The engine takes a JSON snapshot of the *entire* `schedule`, `jobs`, `machines`, and `workers` table.
    2.  This snapshot is saved as a BLOB in the `schedule_checkpoints` table.
    3.  If you later click **"↩ Rollback"**, the system clears the current database and overwrites it with this snapshot.
    4.  **UI Benefit**: Absolute safety. If an optimizer run or a disruption makes the schedule too chaotic, you can go back in time to the stable `v1` version.

### 6. Theme Switching
*   **Action**: Click the **🌓 toggle** in the header.
*   **Hits**: *LocalStorage only* (Client-side)
*   **What Happens**:
    1.  The JS logic sets the `data-theme` attribute on the root HTML element.
    2.  CSS Variables (e.g., `--bg`, `--text`) instantly update their HEX values.
    3.  The choice is saved to the browser's `localStorage`.
    4.  **UI Benefit**: Adaptive visibility specifically for high-contrast sunlight or low-light factory floor environments.

---
*SmartSched AI v2 – Decision Intelligence for Industry 4.0.*
