# LeadFlow Repository & Deployment Architecture

```text
========================================================================================
[ MAC (macOS) : The Source of Truth & Local Fallback ]
========================================================================================

~/leadflow (GitHub Source of Truth)
├── .env (LEADFLOW_DEVICE_ROLE='backup')
├── architecture maps (docs/*, version.md, state.md)
├── leadflow.db (Replicated backup database via sync_engine.py)
├── server.py (Runs locally but ignores HTTP traffic natively due to Cloudflare split)
├── scheduler.py (Runs fallback CRON logic via `is_leader()` check)
├── ai_writer.py (Executes fallback AI tasks if Mac assumes primary)
├── start_watchdog.sh
├── ... <and all repos/code files below>

           |
           | rsync / git pull
           v

========================================================================================
[ NODE 1: AMAZON FIRESTICK (Termux) - IP: 192.168.0.113 ]
========================================================================================

/data/data/com.termux/files/home/leadflow/
├── .env (LEADFLOW_DEVICE_ROLE='primary')
├── [EXECUTED SCRIPTS]
│    ├── run_daemon.sh (Hosts the cloudflared tunneling)
│    ├── start_watchdog.sh (Process watcher)
│    ├── resolve_devices.py (Scans local network IPs)
│    ├── stealdeals_userbot.py (Telegram operations - Low I/O)
│    └── tg_lead_bot.py 
├── [DEAD SCRIPTS (Intentionally Not Run on Firestick to avoid OOM)]
│    ├── leadflow.db (Ignored on Firestick)
│    ├── server.py
│    ├── scheduler.py
│    └── ai_writer.py
├── ... <all remaining files natively copied over by rsync>

           |
           | TCP Routing 8765/8766 (Web Traffic)
           v

========================================================================================
[ NODE 2: VIVO PHONE (Termux) - IP: 192.168.0.162 ] 
========================================================================================

/data/data/com.termux/files/home/leadflow/
├── .env (LEADFLOW_DEVICE_ROLE='web_db_execution_node') 
├── [EXECUTED SCRIPTS]
│    ├── leadflow.db (The active Database)
│    ├── server.py (FastAPI UI)
│    ├── scheduler.py (Active background chron jobs)
│    ├── ai_writer.py (High CPU processing)
│    ├── instagram_sender.py (Natively drives localhost:5555 ADB UI Automator)
│    └── imap_sync.py
├── [DEAD SCRIPTS (Intentionally Not Run on Vivo)]
│    ├── cloudflared (Handled upstream by Firestick)
│    └── stealdeals_userbot.py
├── ... <all remaining files natively copied over by rsync>
```
