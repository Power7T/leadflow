# LeadFlow Architecture Specification: Remote Management & Bidirectional Failover

**Document Type:** Architecture RFC / Technical Whitepaper
**Component:** System Topology, Edge Routing, and High-Availability State Management
**Status:** Approved for Implementation

---

## 1. Executive Summary

The LeadFlow platform operates a distributed, highly-available device automation fleet bridging local network execution with seamless remote operability. To support untethered operations without compromising local execution latency, the system utilizes an Edge-routed Cloudflare Zero Trust Network (ZTNA) overlay. 

This RFC specifies the topology and mechanisms required to maintain strict **Bidirectional Failover**, **Remote ADB Command Routing**, and **State Synchronization** when the developer workstation (Mac) is fully detached from the primary local network (Home Environment), utilizing a localized deployment of `cloudflared` within a Termux environment on the Amazon Firestick.

---

## 2. Infrastructure Topology

The architecture dynamically adapts between "Tethered" (Mac at Home) and "Remote" (Mac Roaming). The local network layer relies on unencapsulated Wi-Fi / ADB connections, whereas the remote layer relies on secure Anycast edge routing.

### 2.1 Active-Active Remote Topology Diagram

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
           |                       | CF Worker Node      |               | | Amazon Firestick        |       |
           | REST                  | (Leader Election)   |               | | (Primary Node)          |       |
           +---------------------->| KV Store            |<==============| | - Termux                |       |
                                   +---------------------+               | | - cloudflared daemon    |       |
                                                                         | | - SQLite / Queue Mgr    |       |
                                                                         | +-------------------------+       |
                                                                         |         |                         |
                                                                         |         | ADB over TCP/IP         |
                                                                         |         v                         |
                                                                         | +-------------------------+       |
                                                                         | | Vivo Phone (Worker)     |       |
                                                                         | | - Target Execution Node |       |
                                                                         | +-------------------------+       |
                                                                         +---------------------------------+
```

---

## 3. Remote Management & Routing Layer

### 3.1 Persistent Zero Trust Tunnels
The local anchor for the remote capability is the Amazon Firestick. It runs `cloudflared` persistently within a Termux environment. The tunnel operates outbound-only to the Cloudflare Edge, meaning no inbound ports need to be opened on the OpenWRT firewall.

### 3.2 Remote ADB & SSH Reverse Proxy Routing
When the Mac is remote, it cannot issue raw ADB commands to the Vivo phone or OpenWRT router over the internet. Instead, it utilizes the Cloudflare tunnel as a bastion interface.

**The Routing Flow:**
1. The Mac establishes an authenticated execution session via `cloudflared access ssh`.
2. The Mac binds a local port to the remote Termux SSH daemon over the tunnel:
   `ssh -L 5037:localhost:5037 user@firestick-tunnel.leadflow.com`
3. The Mac directs its local ADB client server to the forwarded port.
4. **Execution:** When the Mac executes `adb -s <vivo-ip>:5555 shell ...`, the command travels encrypted over the Cloudflare tunnel, terminates at the Firestick's Termux daemon, and translates directly into a local Wi-Fi ADB command targeting the Vivo or OpenWRT.

**Deployment & Upgrades:** 
For pushing code updates to the Firestick, Vivo, or OpenWRT, the Mac utilizes standard `scp` or `rsync` over this established SSH-over-CF tunnel, maintaining an identical deployment workflow to local operation.

---

## 4. Leader Election & Bidirectional Failover

To prevent split-brain queue processing (where both the Mac and Firestick attempt to execute the same LeadFlow tasks while disconnected), the system retains the existing Cloudflare Worker KV `is_leader()` logic intact.

### 4.1 Failover State Machine Diagram

```ascii
      MAC NODE (Backup)                                     FIRESTICK NODE (Primary)
      Current State: WAITING                                Current State: LEADER
      
      [ Heartbeat Loop ]                                    [ Heartbeat Loop ]
             |                                                     |
             |                                                     | (PUT /heartbeat)
             v                                                     v
    +-------------------------------------------------------------------------+
    | EDGE COMPUTE: Cloudflare Worker (KV Binding: LEADFLOW_STATE)            |
    |                                                                         |
    |  Key: `current_leader`        Value: `firestick`                        |
    |  Key: `last_heartbeat`        Value: `1716900210`                       |
    |                                                                         |
    |  Logic: `is_leader(node_id)`                                            |
    |   1. If `current_leader` == node_id, return TRUE                        |
    |   2. If `current_leader` != node_id:                                    |
    |        Check time() - `last_heartbeat`.                                 |
    |        If > 30s (Dead): Set `current_leader` = node_id, return TRUE     |
    |        If < 30s (Alive): return FALSE                                   |
    +-------------------------------------------------------------------------+
             |                                                     |
             | (Response: FALSE)                                   | (Response: TRUE)
             v                                                     v
      [ Block Execution ]                                   [ Execute Queue ]
```

### 4.2 Failover Mechanics
1. **Primary Operation:** The Firestick polls the Worker, asserts leadership, and executes jobs locally via ADB. The Mac, pinging the Worker, is rejected and gracefully sleeps.
2. **Mac Remote Offload / Fallback:** If the Firestick loses network connectivity, it fails to send its 30-second heartbeat. The CF Worker expires the lock. 
3. **Takeover:** The Mac's next `is_leader()` invocation successfully captures the lock. The Mac becomes the primary executor. Since the Mac is remote, it routes all its LeadFlow execution commands *through* the SSH Tunnel to the Firestick as described in Section 3.2. 
4. **Re-convergence:** If the tunnel itself is dead (Firestick offline completely), the Mac caches tasks locally and ceases remote actuation until the home network recovers, acting as an offline buffer queue.

---

## 5. Database Replication & Synchronization

To support seamless transitions from Local to Remote and back, LeadFlow state data (e.g., job queues, interaction logs) must be replicated securely.

### 5.1 Remote Sync Workflow
When the Mac transitions from "Home" to "Remote" (detected via subnet changes or Ping-to-Gateway failures):
1. The Mac halts local-network DB sync protocols.
2. It spins up a background process utilizing `rsync` or native SQLite replication techniques (e.g., Litestream/LiteFS) routed **through the SSH-over-CF Tunnel**.
3. **Data Flow:** `Mac Queue DB -> CF Proxy -> CF Edge -> Secure Tunnel -> Firestick Termux -> Firestick SQLite`
4. The database acts as the source-of-truth. Because the `is_leader()` logic ensures only *one* device attempts to execute state changes at any given time, database locking collisions over the tunnel are structurally eliminated.

---

## 6. Security Considerations & Posture

* **No Inbound Firewalls:** OpenWRT drops all public inbound requests. All traffic is established outbound via `cloudflared`.
* **Zero Trust Auth:** Attempting to reach the SSH proxy on the edge requires Cloudflare Access authentication (e.g., OTP via Email, GitHub OAuth, or Mutual TLS Client certificates on the Mac).
* **Isolation of Concerns:** The intact `is_leader()` function ensures that any disruption to the tunnel network solely triggers a clean failover, rather than concurrent job executions. Local Vivo network remains completely air-gapped from the Internet except via the Termux proxy.