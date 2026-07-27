# LeadFlow Architecture Specification: Split-Node Remote Management & Bidirectional Failover

**Document Type:** Architecture RFC / Technical Whitepaper
**Component:** Split-Node Topology, Edge Routing, and High-Availability State Management
**Status:** Approved for Implementation (V2 - Split-Node Update)

---

## 1. Executive Summary

The LeadFlow platform operates a distributed, highly-available device automation fleet bridging local network execution with seamless remote operability. To completely eliminate Edge-Node crashing, OOM constraints, and Zero-Byte Free errors, the system utilizes a **Split-Node Architecture**. 

The Amazon Firestick serves strictly as an always-on dumb ZTNA gateway, while all heavy database operations (`leadflow.db`), FastAPI web hosting, and automation generation are offloaded directly to a dedicated Vivo Android node running Termux. 

---

## 2. Infrastructure Topology (Split-Node)

The architecture dynamically accommodates untethered remote offloading while eliminating DB-read latency on the execution device.

### 2.1 Active-Active Split-Node Topology Diagram

```ascii
                                   CLOUDFLARE EDGE NETWORK
                               +-----------------------------+
                               |                             |           
  +------------------+         |   +---------------------+   |           +---------------------------------+
  |  REMOTE SITE     |         |   | CF Access / Tunnel  |   |           |  HOME NETWORK (Untrusted WAN)   |
  |                  |         |   | (ZTNA Identity)     |   |           |                                 |
  | +--------------+ |  HTTPS  |   +----------+----------+   | Multiplexed +---------------+                 |
  | | Developer Mac| | (TLS)   |              |              | UDP (QUIC)| | OpenWRT Router|                 |
  | | (Backup Node)| |-------->|    Tunnel    |   Tunnel     |<----------| | (Gateway)     |                 |
  | +--------------+ |         |    Ingress   |   Egress     |           | +-------+-------+                 |
  +--------+---------+         |              |              |           |         |                         |
           |                   +--------------|--------------+           |         | Local Wi-Fi (Subnet)    |
           |                                  |                          |         |                         |
           |                                  v                          |         v                         |
           |                       +---------------------+               | +-------------------------+       |
           |                       | CF Worker Node      |               | | NODE 1: Firestick (.113)|       |
           | REST                  | (Leader Election)   |               | | (Dumb Gateway)          |       |
           +---------------------->| KV Store            |<==============| | - cloudflared         |       |
                                   +---------------------+               | | - port_forwarding       |       |
                                                                         | +-------------------------+       |
                                                                         |         |                         |
                                                                         |         | (TCP Forward via LAN)   |
                                                                         |         v                         |
                                                                         | +-------------------------+       |
                                                                         | | NODE 2: Vivo Phone      |       |
                                                                         | | (Primary execution Node)|       |
                                                                         | | - leadflow.db (SQLite)  |       |
                                                                         | | - server.py / scheduler |       |
                                                                         | | - Native UI Automator   |       |
                                                                         | +-------------------------+       |
                                                                         +---------------------------------+
```

---

## 3. Storage & Compute Offloading

By severing the database from the Firestick, we resolve hard-fault CPU/Disk crashing. 
* **Firestick Role:** Strictly runs `cloudflared`. It listens for inbound requests on port 8765 and transparently forwards them to the Vivo's dynamically resolved IP. 
* **Vivo Role:** Operates a native `sshd` and Python environment via Termux. It serves the FastAPI framework directly from memory and manipulates `leadflow.db` locally. Because the Instagram app is on the *same device* as the database, UI-Automation uses `adb -s localhost:5555 shell input tap...`, creating zero-millisecond latency.

---

## 4. Leader Election & Bidirectional Failover

To prevent split-brain queue processing (e.g. Mac and Vivo attempting to send the same Instagram DM simultaneously), the Cloudflare Worker KV `is_leader()` logic tracks state.

### 4.1 Failover Mechanics
1. **Primary Operation:** The Vivo Phone polls the Worker, asserts leadership, and executes jobs locally via native ADB loopback. The Mac, pinging the Worker remotely, is rejected and safely idles.
2. **Mac Remote Takeover:** If the Vivo loses network connectivity, it fails to send its 30-second heartbeat. The CF Worker expires the lock in the KV Store. 
3. **Execution Routing:** The Mac's next `is_leader()` invocation successfully captures the lock. The Mac becomes the primary executor. Because it is remote, it routes its execution commands through the Cloudflare Tunnel => Firestick Forwarder => Vivo internal ADB daemon.

---

## 5. Security & Battery Lifecycle

* **Native Loopback:** ADB execution commands never jump across open routers unless routing from the Failover Mac.
* **Lifecycle Management:** Because the Vivo is designated as a 24/7 plugged-in node, its charging threshold is capped utilizing `/sys/class/power_supply` software locks to prevent Lithium-Ion battery expansion under continuous AC load.
