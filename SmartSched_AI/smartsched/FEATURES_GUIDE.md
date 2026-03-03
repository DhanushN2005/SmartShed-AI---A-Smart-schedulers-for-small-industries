# 🏭 SmartSched AI v2: Full Feature & Scenario Guide
*Industrial Production Decision Governance System*

This guide explains every "Superpower" of the SmartSched system using real-world factory examples. Use this to explain the project to anyone—from factory owners to software engineers.

---

## 1. Multi-Objective Optimization (The "Brain")
*   **Problem:** A traditional factory manager schedules based on "which customer is yelling the loudest." This often wastes machine time and reduces profit.
*   **The Feature:** The AI considers **Makespan**, **Delay Penalties**, **Profit Margins**, and **Resource Balancing** all at once.
*   **Scenario:** You have 12 jobs. Job A is high profit but Job B has a massive penalty if late. The AI calculates that by starting Job B 30 minutes earlier on the CNC Lathe, it saves ₹5,000 in penalties without losing any profit on Job A.
*   **Tech Insight:** Uses a **Weighted Sum Model** that normalizes different business goals into a single "Urgency Score."

## 2. Human Governance & Job Locking
*   **Problem:** Supervisors don't trust AI 100%. They know that *Client X* is visiting the factory today, so their job *must* be running on the floor, even if the AI thinks another job is more "efficient."
*   **The Feature:** **Job Locking** allows a human to "freeze" a decision.
*   **Scenario:** You lock the "Textile Loom" job for Client X. Now, even if a high-priority "Rush Order" arrives, the AI is **forbidden** from moving Client X's job. It must find a different machine for the new order.
*   **Executive Insight:** It provides **Human-in-the-loop** control, ensuring technology serves the business strategy, not the other way around.

## 3. Dynamic Rescheduling (Resilience)
*   **Problem:** A factory's plan is usually "garbage" by 10:00 AM because a machine broke or a worker called in sick.
*   **The Feature:** **Disruption Handling Engine.**
*   **Scenario:** At 2:00 PM, a CNC machine fails. Normally, the supervisor would spend 2 hours on a phone calling clients to apologize. In SmartSched, you hit "Breakdown," and the AI instantly re-routes those jobs to "Milling Center 2," calculates the new delay, and updates your profit forecast in **5 seconds**.
*   **User Benefit:** Turns a two-hour crisis into a two-click resolution.

## 4. Simulation & "What-If" Analysis
*   **Problem:** Sales asks: "Can we handle this new 50,000 unit order?" Operations says "Maybe." Sales accepts it, and the factory crashes under the load.
*   **The Feature:** **Accept vs. Reject Scenario Comparison.**
*   **Scenario:** You input the new order details. The simulation creates two "Future Universes." 
    *   *Universe A:* You accept. You make ₹2 Lakhs, but you trigger ₹1.5 Lakhs in late penalties from other clients. Net Gain: ₹50k.
    *   *Universe B:* You reject. You lose the order, but your current clients stay happy. Net Impact: ₹0.
    *   **The Outcome:** The AI recommends "Reject" because the risk to your existing reputation is too high for a small ₹50k gain.

## 5. Risk Management (Proactive Health)
*   **Problem:** You don't know a machine is going to break until it actually smokes and stops.
*   **The Feature:** **Machine Reliability & Worker Overload Monitoring.**
*   **Scenario:** The system sees the "Drill Press" has been running at 95% capacity for 4 days and its reliability score has dropped. It flags a "Warning" alert. You schedule maintenance *before* it breaks, saving days of downtime.
*   **Worker Safety:** It also flags workers (like "Priya Sharma") who are at 100% utilization, preventing human error and accidents.

## 6. Versioning & Checkpoints (The "Undo" Button)
*   **Problem:** You tried a new schedule for a "Rush Order," but it made the factory floor too chaotic. You want to go back to how things were an hour ago.
*   **The Feature:** **Snapshot Rollback.**
*   **Scenario:** Before every big change, the system saves a "Checkpoint." If the supervisor realizes the new schedule is impossible for the workers to follow, they click **Rollback to v1**. Every machine, worker, and job is instantly restored to its previous state.
*   **Data Insight:** Full database state serialization—not just a log, but a complete "Save Game" for your factory.

## 7. Adaptive UI (Industrial Ergonomics)
*   **Problem:** Factory floors are bright during the day (Light Mode needed) but dark/blue-lit at night (Dark Mode needed to reduce eye strain). Text must be huge and visible regardless.
*   **The Feature:** **Adaptive Theme Engine.**
*   **The Outcome:** Whether a supervisor is checking the dashboard on a bright tablet in the sun or a dark control room at 3:00 AM, the information is high-contrast and crystal clear.

## 8. Financial KPIs (Real-Time Accounting)
*   **Problem:** Most factories only know if they made a profit at the end of the month.
*   **The Feature:** **Live Net Factory Impact.**
*   **Scenario:** As jobs get late, the "Penalty Risk" counter on the dashboard literally ticks up. The supervisor sees their "Net Profit" dropping in real-time. This creates a psychological drive to solve the delay *now*, rather than waiting for an accountant's report next month.

---
*SmartSched AI v2: Making Every Minute Profitable.*
