# OLD ARCHITECTURE (Firestick as the Brain)
```
[ CLOUDFLARE PUBLIC NET ]
          |
+---------------------------------------+
| FIRESTICK (The Overloaded Brain)      |
+---------------------------------------+
| - Cloudflared (Tunnels Web traffic)   |
| - leadflow.db (Constant disk writes)  |  <--- 🚨 CAUSES CRASHES / ZERO BYTES FREE
| - server.py (Runs FastAPI Web Server) |  <--- 🚨 CPU HEAVY
| - scheduler.py (Calculates queues)    |
+---------------------------------------+
          |
    (Wi-Fi ADB Command)
          |
+---------------------------------------+
| VIVO PHONE (Dumb UI Robot)            |
+---------------------------------------+
| - Instagram (Just taps screen)        |
+---------------------------------------+
```

# NEW ARCHITECTURE (Split-Node / Vivo as the Brain)
```
[ CLOUDFLARE PUBLIC NET ]
          |
+---------------------------------------+
| FIRESTICK (The Dumb Gateway Hub)      |
+---------------------------------------+
| - Cloudflared (Tunnels Web traffic)   |
| - IP Forwarding (Routes web to Phone) |
| - start_watchdog.sh (Lightweight)     |
| [STORAGE: 0%] [CPU LOAD: ~5%]         |  <--- ✅ NEVER CRASHES AGAIN
+---------------------------------------+
          |
    (Wi-Fi Background Ping)
          |
+---------------------------------------+
| VIVO PHONE (The Heavy Compute Brain)  |
+---------------------------------------+
| -> [ NATIVE TERMUX SHELL ]            |
|    - leadflow.db (Massive SQLite DB)  |  <--- ✅ HANDLES READS/WRITES INSTANTLY 
|    - server.py (FastAPI Web Server)   |  <--- ✅ BETTER CPU = FASTER DASHBOARD
|    - scheduler.py (Message queues)    |
| -> [ ANDROID AUTOMATION ]             |
|    - Instagram (UI Automator target)  |
+---------------------------------------+
```
