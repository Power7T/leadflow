# LeadFlow Version History

## v1.0.0 (Old Architecture - Firestick Primary)
**Commit:** `1694d51` 
**Message:** Task: Integrate automated AI captcha and Gemini quota management alongside demographic previews

### 🏛 Architecture (Legacy)
- The Amazon Firestick (192.168.0.113) acted as the monolithic Primary Gateway & DB Execution Node.
- `server.py`, `scheduler.py`, `leadflow.db`, and `ai_writer.py` were fully hosted and executed within the Firestick's Termux instance.
- **Flaws Addressed by Deprecation:** The Firestick hardware suffered from memory starvation (OOM) due to high I/O (SQLite queries) and heavy processing required by FastAPI and automated AI generations. Execution over Wi-Fi ADB from Firestick to Vivo caused dropped connections and latency.

---

## v1.1.0 (New Split-Node Architecture)
**Current Status:** Deployed and Active (2026-07-27)

### 🏛 Architecture (Split-Node)
- **Node 1 - Gateway (Amazon Firestick):** Retains Telegram Chatbots (`stealdeals_userbot.py`, `tg_lead_bot`, etc.) and `cloudflared` tunnel ingress. Stripped of high CPU/RAM logic.
- **Node 2 - Primary DB & Server (Vivo Phone):** Assumed control of `leadflow.db`, `server.py`, `scheduler.py`. This leverages the Vivo's powerful internal processing, running UI Automator scripts and ADB natively via `localhost` (zero latency drop-offs).
- **Node 3 - Fallback (Mac):** Remains as Active-Active Replica. 

### 🔧 Applied Fixes
- `server.py` safely terminated on Firestick.
- `firestick_db_fix.py` applied on Firestick: Reset 641 invalid A/B tests to pending, `follow_ups` stats schema correctly applied.
- `server.py` actively running successfully on Vivo Node.
