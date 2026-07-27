# New Architecture (Split-Node)

This diagram represents our planned transition. The heavy I/O, AI routing and Database operations are shifted to the Vivo's powerful internal storage. The Firestick reverts to just being a network router and a Telegram bot host (low CPU, low IO).

```text
========================================================================================================================
                                      [ EXTERNAL INTERNET / USERS (HTTPS : 443) ]
========================================================================================================================

           [ NEW ARCHITECTURE (Split-Node) ]

+-------------------------------------------------+
|  Cloudflare Edge Network                        |
|  [ KV Storage: LEADER_ELECTION ]                |
+-------------------------------------------------+
          │ cloudflared ZTNA Tunnel (UDP)
          ▼
+-------------------------------------------------------------+
| NODE 1: AMAZON FIRESTICK (.113)                             |
|-------------------------------------------------------------|
| ROLE: Gateway Ingress & Chatbot Manager                     |
| ENGINE: Termux                                              |
|                                                             |
| [✅ LEADFLOW GATEWAY PROCESSES ]                            |
| - cloudflared (Tunnel Daemon)                               |
| - HAProxy / TCP Switch (Passes web traffic to Vivo)         |
| - resolve_devices.py                                        |
| - start_watchdog.sh                                         |
| - sshd                                                      |
|                                                             |
| [✅ TELEGRAM BOT DIRECTORIES (Remaining on Firestick) ]     |
| - ~/(stealdeals_userbot.py, tg_lead_bot) (Main parsing bot)                          |
| - ~/channel_mirror_bot (Posts/mirrors channels)             |
| - ~/support_bot (Customer service bot)                      |
| - *.session (stealdealsuser.session, etc)
| - *.sqlite (Individual bot databases, low I/O)              |
| *(Bots use low I/O, perfectly safe for Firestick storage)*  |
|                                                             |
| [❌ PROCESSES REMOVED (Eliminates OOM) ]                    |
| - leadflow.db, server.py, scheduler.py, agent logic         |
+-------------------------------------------------------------+
          │
          │  (Traffic passes straight through)
          ▼
+-------------------------------------------------------------+
| NODE 2: VIVO PHONE (.162:8765)                              |
|-------------------------------------------------------------|
| ROLE: Primary Database, Web Host, & Execution Node          |
| ENGINE: Termux + Native Android                             |
|                                                             |
| [ NETWORK DISCOVERY & DB (~/leadflow) ]                     |
| - resolve_devices.py                                        |
| - leadflow.db (SQLite handles mass R/W on big phone storage)|
|                                                             |
| [ SERVER LAYER (Termux) ]                                   |
| - server.py (FastAPI runs flawlessly with high RAM)         |
| - scheduler.py (APScheduler)                                |
| - start_watchdog.sh (Healer)                                |
|                                                             |
| [ AUTOMATION LAYER (Internal Localhost ADB) ]               |
| - Agent logic / AI generation                               |
| - instagram_sender.py (Local ADB without Wi-Fi dropouts)    |
| - imap_sync.py                                              |
| - Native Android UI Automator targets                       |
+-------------------------------------------------------------+
          │
          │ (Health Check Fail -> Takeover)
          ▼
+-------------------------------------------------------------+
| NODE 3: MAC BACKUP (.X:8765)                                |
|-------------------------------------------------------------|
| ROLE: Active-Active Over-The-Air Failover                   |
|                                                             |
| - leadflow.db (Replica Sync)                                |
| - server.py (Standby mode)                                  |
| - scheduler.py                                              |
| - start_watchdog.sh                                         |
| - agent logic / AI generation                               |
| - instagram_sender.py (WiFi ADB to Vivo)                    |
| - imap_sync.py                                              |
| - ~/(stealdeals_userbot.py, tg_lead_bot), channel_mirror_bot (Standby mode)          |
+-------------------------------------------------------------+
```
