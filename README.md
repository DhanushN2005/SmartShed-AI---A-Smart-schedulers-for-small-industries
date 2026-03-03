# SmartShed-AI---A-Smart-schedulers-for-small-industries
### *The Industrial "Digital Twin" for Production Decision Governance*

SmartSched AI v2 is a high-performance scheduling and decision-support system designed for modern factories. It moves beyond simple "Gantt charts" by integrating **Financial Impact**, **Risk Mitigation**, and **Human Governance** into one real-time dashboard.

---

## 🚀 Simple Working Demo (The "Supervisor Flow")
To see the power of the project in 2 minutes, follow this flow:

1.  **Initialize**: Log in as a `Supervisor` and navigate to the **Schedule** tab.
2.  **Optimize**: Click **Run Schedule**. The AI compares millions of combinations to find a plan that balances profit, speed (makespan), and on-time delivery.
3.  **Commit**: Identify your 3 most critical jobs and click **Lock**. This tells the AI: "No matter what happens, do not move these."
4.  **Handle Chaos**: Navigate to **Disruptions** and click **Demo: Machine Breakdown**. 
    *   *Watch:* The AI instantly reshuffles all *unlocked* jobs but keeps your 3 locked jobs exactly where they are.
5.  **Audit**: Check the **Disruption Log** to see the entry. Once the demo is over, click **Resolve** to restore factory capacity and see your **KPIs** turn green again.

---

## 🛠 Scenarios it Solves
SmartSched AI v2 is built for high-stress manufacturing environments where things go wrong:

*   **The Rush Order Dilemma**: A customer offers a ₹50,000 bonus for a 1-day delivery. *Use the **Simulation** tab* to see if accepting this will cause ₹60,000 in late penalties for other clients.
*   **The Breakdown Crisis**: Your main CNC machine fails mid-shift. The system instantly identifies which jobs are at risk and re-routes them to sub-optimal machines to minimize reputation damage.
*   **Worker Burnout**: The **Risk Engine** flags workers with >90% utilization. It suggests re-allocating tasks to under-utilized workers before a safety incident occurs.
*   **Version Rollback**: Did a "What-If" scenario make things worse? Go to the **Versions** tab and roll the entire factory back to `v1` with one click.

---

## 📊 Data Requirements
The system is "Data-Hungry" for precision. To get the best results, it needs:

### ⚙️ Job Data
*   **Processing Time**: How many hours it takes (base).
*   **Due Date**: The hard deadline.
*   **Profit Margin**: The ₹ value of completing the job.
*   **Penalties**: The hourly cost of being late.
*   **Requirements**: Which machine type (e.g., CNC, Welding) and worker skill (e.g., Assembly) are needed.

### 🏭 Resource Data
*   **Machines**: ID, Type, and **Reliability Score** (prevents AI from over-trusting old machines).
*   **Workers**: ID, Skill-sets, and **Shift Hours** (Start/End times).

---

## 💻 Tech Stack
*   **Backend**: Python 3.10+, FastAPI (Asynchronous API).
*   **Database**: SQLite with WAL (Write-Ahead Logging) for high concurrency.
*   **Frontend**: Vanilla HTML5/JavaScript, CSS3 with **Adaptive Theme Engine** (Dark/Light modes).
*   **Engine**: Custom Multi-Objective Optimizer (Weighted Sum Model).

---
*Developed for Industrial Excellence.*
