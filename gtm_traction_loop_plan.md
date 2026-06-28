# LeadFlow GTM Traction Loop Implementation Plan

This plan outlines the changes required to integrate Matt Ganzak's **GTM Traction Loop** principles directly into the LeadFlow system. We will focus specifically on **Station 1 (Narrative / 1% Shift)** and **Station 5 (Value-First Warm-up Ladder)**.

---

## 📋 Objectives
1. **Refocus the Narrative:** Position LeadFlow outreach as a *"Mobile Performance & Booking Specialist"* rather than a generic web designer.
2. **Build the Warm-up Ladder:** Restructure follow-ups in `scheduler.py` to deliver specific value-building messages (Scorecards, Case Studies, and Value Stacks) over a structured 4-step sequence.

---

## 🛠️ Step-by-Step Execution Plan

### Phase 1: Narrative & Copywriting Prompts (`ai_writer.py`)
We will rewrite the system prompts in [ai_writer.py](ai_writer.py) to change the messaging structure:
- **Core USP Enforced:** Define our service as solving the "Mobile Conversion Gap" (speed score + responsive layout).
- **Outreach Template Update:** Make the initial email shorter, outcome-focused, and centered on the generated mobile demo.
- **Follow-up Generation:** Add functions to automatically generate three subsequent follow-up drafts for every business.

### Phase 2: Database Schema & Draft Generation (`database.py`)
We will update how drafts and follow-ups are stored in SQLite:
- **Extended Follow-ups:** Allow storing distinct templates/drafts for each sequence step (Sequence #1: Scorecard, Sequence #2: Case Study, Sequence #3: Final Stack).
- **Follow-up Generation Logic:** When a new lead is approved or created, the system will auto-generate all three follow-up steps immediately.

### Phase 3: The Value-First Nurturing Ladder (`scheduler.py`)
We will modify the follow-up dispatch logic:
- **Step 1 (The Initial Hook):** The main outreach email containing the custom demo link.
- **Step 2 (The Mobile Scorecard):** Sent 2 days later. A raw comparison of the lead's current speed score vs. our redesign speed score.
- **Step 3 (Case Study Proof):** Sent 3 days later. Relays a short success story of a similar local business.
- **Step 4 (The Irresistible Value Stack):** Sent 3 days later. A Fiverr-secured offer stacking web design, speed boost, Google Map optimization, and contact form setup.
- **Scheduler Logic:** Enforce strict timezone checks and optimal sending windows for all sequence steps.

---

## 🗓️ Implementation Roadmap

| Step | Task | Target Files | Status |
| :--- | :--- | :--- | :--- |
| **1** | Update `ai_writer.py` prompts to enforce Mobile Conversion USP | `ai_writer.py` | ⏳ Pending |
| **2** | Update database helpers to handle 3 distinct value follow-ups | `database.py` | ⏳ Pending |
| **3** | Restructure follow-up generation for new/approved leads | `server.py`, `database.py` | ⏳ Pending |
| **4** | Restructure dispatch engine to send the 4-step sequence | `scheduler.py` | ⏳ Pending |
| **5** | Run end-to-end sandbox tests with mock leads | `imap_sync.py`, `scheduler.py` | ⏳ Pending |
