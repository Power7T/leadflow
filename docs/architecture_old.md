# Old Architecture (Current State)

This diagram represents the actual structure we discovered. The Firestick is heavily overloaded, acting as the primary brain while the Vivo phone acts merely as a dumb execution robot.

```text
========================================================================================================================
                                      [ EXTERNAL INTERNET / USERS (HTTPS : 443) ]
========================================================================================================================

           [ OLD ARCHITECTURE (Flawed) ]

+-------------------------------------------------+
|  Cloudflare Edge Network                        |
|  [ KV Storage: LEADER_ELECTION ]                |
+-------------------------------------------------+
          │ cloudflared ZTNA Tunnel (UDP)
          ▼
+-------------------------------------------------+
| NODE 1: AMAZON FIRESTICK (.113)                 |
|-------------------------------------------------|
| ROLE: Primary Execution & ZTNA Gateway          |
| ENGINE: Termux                                  |
|                                                 |
| [✅ LEADFLOW PROCESSES (~/leadflow) ]           |
| - cloudflared (Tunnel Daemon)                   |
| - leadflow.db (SQLite Heavy I/O) [CRASHES]      |
| - server.py (FastAPI UI)                        |
| - scheduler.py (APScheduler)                    |
| - resolve_devices.py                            |
| - start_watchdog.sh                             |
| - Agent logic / AI generation                   |
| - instagram_sender.py                           |
| - imap_sync.py                                  |
|                                                 |
| [✅ TELEGRAM BOT PROCESSES (Unrelated) ]        |
| - ~/(stealdeals_userbot.py, tg_lead_bot.py)                                 |
| - *.session files\n| - ~/channel_mirror_bot                          |
| - ~/support_bot                                 |
+-------------------------------------------------+
          │
          │ Wi-Fi ADB (High Latency/Drops) 
          ▼
+-------------------------------------------------+
| NODE 2: VIVO PHONE (.162:5555)                  |
|-------------------------------------------------|
| ROLE: Dumb UI Execution Robot                   |
|                                                 |
| [ NETWORK DISCOVERY & DB ]                      |
| - (None, Firestick handles all)                 |
|                                                 |
| [ SERVER LAYER (Termux) ]                       |
| - (None, Firestick handles all)                 |
|                                                 |
| [ AUTOMATION EXECUTION ]                        |
| - Settings > Wireless Debugging (adbd:5555)     |
| - Instagram / Chromium Web Scrape               |
|                                                 |
| *(All logic comes across the Wi-Fi from the     |
|   overheated Firestick, causing lag/drops)*     |
+-------------------------------------------------+
          │ (Health Check Fail -> Takeover)
          ▼
+-------------------------------------------------+
| NODE 3: MAC BACKUP (.X:8765)                    |
|-------------------------------------------------|
| ROLE: Active-Active Over-The-Air Failover       |
|                                                 |
| - leadflow.db (Replica Sync)                    |
| - server.py (Standby mode)                      |
| - scheduler.py                                  |
| - start_watchdog.sh                             |
| - agent logic / AI generation                   |
| - instagram_sender.py (WiFi ADB to Vivo)        |
| - imap_sync.py                                  |
| - ~/(stealdeals_userbot.py, tg_lead_bot.py) (Standby mode)                  |
| - *.session files\n| - ~/channel_mirror_bot (Standby mode)           |
| - ~/support_bot (Standby mode)                  |
+-------------------------------------------------+
```
