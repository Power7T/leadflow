# LeadFlow Code Distribution & Segregation

This document outlines the strict segregation of code, repositories, and responsibilities across the three physical nodes in the LeadFlow ecosystem as of the Split-Node Architecture (v1.1.0).

## 1. NODE 1: Amazon Firestick (192.168.0.113)
**Role:** ZTNA Gateway, Reverse Proxy, and Low I/O Chatbot Host.
**Environment:** Termux on Android.

**Actively Deployed Code (Required on Firestick):**
- `cloudflared` daemon binaries (for ZTNA tunnel).
- `haproxy` config or TCP forwarding scripts to route port 8765/8766 to the Vivo Phone.
- `resolve_devices.py` (for subnet discovery).
- `start_watchdog.sh` (lightweight ingress health checks).
- `telegram_bot.py` / `tg_lead_bot.py` / `stealdeals_userbot.py` (and related `.session` / `.sqlite` files). 

**Code to be ignored/deleted on Firestick:** 
- `server.py`, `scheduler.py`, `ai_writer.py`, `leadflow.db`, `instagram_sender.py` (Must not run to prevent OOM/CPU saturation).

---

## 2. NODE 2: Vivo Phone (192.168.0.162)
**Role:** Primary Database, Compute Node (AI & Web Server), and UI Automation Engine.
**Environment:** Termux + Native Android environment (adb localhost).

**Actively Deployed Code (Required on Vivo):**
- `leadflow.db` (The single, primary SQLite database).
- `server.py` (FastAPI backend and UI routes).
- `scheduler.py` (Task execution and cron queues).
- `ai_writer.py` (Heavy Gemini/OpenAI prompt generation & parsing).
- `instagram_sender.py` / `whatsapp_sender.py` (Configured to use `adb shell` on `localhost` rather than Wi-Fi ADB to prevent drops).
- `imap_sync.py` (IMAP inbox parsing).
- Frontend HTML/CSS assets (`templates/`, `static/`).

**Code to be ignored/deleted on Vivo:**
- Cloudflared binaries (It does not expose to the internet directly; ingress comes from the Firestick).

---

## 3. NODE 3: Native Mac (Backup & Development)
**Role:** Active-Active Failover replica and primary development environment.
**Environment:** macOS.

**Actively Deployed Code (Required on Mac):**
- THE ENTIRE REPOSITORY. The true "Source of Truth".
- `.env` files with `LEADFLOW_DEVICE_ROLE='backup'`.
- All `database.py`, `server.py`, `scheduler.py` scripts configured to boot in Standby mode.
- `cloudflared` (Secondary worker proxy for KV failover).

### Core Principle: Single Git Repository
Although the code execution is segregated physically, **the entire codebase remains in a single `leadflow` Git Repository.** 
The files pushed to Firestick and Vivo are identical to the Mac (deployed via `rsync` or `git pull`), but the execution profile is dictated by the environment variables and the specific start scripts used to boot the node.
- Firestick boots: Bots + Proxy.
- Vivo boots: Server + Scripts.
- Mac boots: Backup listeners.
