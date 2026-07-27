# The LeadFlow Monorepo Mental Model

When you look at the root directory of this repository, it looks like a massive flat dump of files. This is intentional, but to understand it, you must apply the **"Filter Lens"**.

The repository is built as a **Monorepo**—meaning one codebase meant to be deployed exactly identically to every physical device. Instead of branching code into strict hardware folders (which breaks Python imports and makes active-active failover a nightmare), the repo uses an environmental light switch (`.env`) to dynamically "turn off" scripts that don't belong on that specific node.

## How to Read the Codebase

Imagine looking at the repository through these three colored lenses based on the device you are deploying to:

### 🔴 The Firestick Lens (Gateway / Comms)
If you are deploying to the Amazon Firestick, cross out the heavy computation scripts.
- **ACTIVE:** `run_daemon.sh` (tunnels), `resolve_devices.py` (routing), `telegram_bot.py`
- **INVISIBLE (Do Not Run):** `server.py`, `scheduler.py`, `instagram_sender.py`, `ai_writer.py`, `leadflow.db`

### 🔵 The Vivo Lens (Brain / Database / Worker)
If you are deploying to the Vivo Phone, cross out the gateway scripts.
- **ACTIVE:** `server.py`, `scheduler.py`, `ai_writer.py`, `instagram_sender.py`, `leadflow.db`
- **INVISIBLE (Do Not Run):** `run_daemon.sh` (cloudflared), `telegram_bot.py`

### 🟢 The Mac Lens (God Mode / Sandbox)
If you are local on the Mac, everything is visible.
- **ACTIVE:** The entire ecosystem is available to run in Standby (`LEADFLOW_DEVICE_ROLE='backup'`).

---

## Why this is smarter than hardware folders (`/vivo`, `/firestick`):
1. **Zero Deployment Logic:** You just run `git pull` on any device. You don't need complex scripts that say "only move folder A to device B".
2. **Instant Failover:** If the Vivo dies, the Mac doesn't have to awkwardly execute scripts out of a `/vivo` folder; it just toggles its `.env` and standardly runs `server.py`.
3. **Shared Modules "Just Work":** `database.py` and `resolve_devices.py` are used by both the Vivo and the Firestick. Having a flat root means neither device has to worry about ugly relative Python imports (e.g., `sys.path.append('../shared')`). 
