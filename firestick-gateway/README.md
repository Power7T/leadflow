# LeadFlow Go Gateway (Firestick)

This directory contains the modernized, Go-based gateway designed specifically for the Firestick hardware within the 3-node LeadFlow ecosystem.

## Node Hierarchy (Failover Design)
The system operates on a coordinated 3-tier hierarchy using Cloudflare KV stores as the source of truth for leadership:

1. \*\*Primary Node (Vivo Phone):\*\* 
   * Runs the standard Python LeadFlow engine natively in Termux.
   * Writes the `leader:heartbeat` timestamp to Cloudflare KV every 5-30 minutes.

2. \*\*Secondary Node (Firestick):\*\*
   * Runs this Go-based `leadflow-gateway` containing a watchdog thread (`watchdog.go`).
   * The watchdog checks `leader:heartbeat` every 3 minutes.
   * \*\*Failover:\*\* If the heartbeat is > 10 minutes old, the Firestick assumes the Vivo crashed. It boots its own lightweight Go `autopilot.go` and starts scraping leads using `Serper.dev`.
   * While running, the Firestick *overwrites* the `leader:heartbeat` timestamp in Cloudflare so the Mac remains idle.
   * \*\*Reclamation:\*\* If the Vivo comes back online, it will write a fresh True primary timestamp. The Firestick's watchdog will detect the new ping, immediately kill its Go-autopilot, and yield control back to the Vivo.

3. \*\*Tertiary Node (Mac):\*\*
   * Runs the standard Python `leadflow` scheduler.
   * Python `scheduler.py` queries Cloudflare KV. If the heartbeat is > 15 minutes old, **both** the Vivo and the Firestick have crashed. The Mac will then launch the main Python autopilot to keep outreach alive natively.

## How to Deploy to Firestick
Ensure you are connected via Wireless ADB from the Mac to the Firestick:
```bash
cd ~/leadflow-gateway
GOOS=linux GOARCH=arm GOARM=7 go build -o leadflow-gateway-armv7 .
adb -s 192.168.8.246:5555 push leadflow-gateway-armv7 /data/local/tmp/leadflow-gateway
adb -s 192.168.8.246:5555 shell "chmod +x /data/local/tmp/leadflow-gateway"
```

## How to Run Watchdog on Firestick
```bash
adb -s 192.168.8.246:5555 shell "LEADFLOW_PUBLIC_URL=... SECRET_TOKEN=... /data/local/tmp/leadflow-gateway watchdog &"
```
