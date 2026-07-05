with open("/Users/chandan/leadflow/README.md", "r") as f:
    code = f.read()

import re

# Update GitHub Pages part
code = re.sub(
    r"- \*\*GitHub Pages Auto-Deployment:\*\* Deploys generated prospect demo sites to GitHub Pages via the GitHub Contents API and logs the live URL.",
    "- **Cloudflare Edge Rendering (Zero Latency):** Demos are rendered instantly on the Cloudflare Edge network. Data is synced to Cloudflare KV, meaning demos load globally in milliseconds with zero server load on the local machine.",
    code
)

# Insert HA & Telegram Bot info after the Demo Section
ha_section = """
### 4. Cloudflare Worker Telegram Bot & Mobile Outreach
- **IG DM & WhatsApp Modes:** Swipe through generated outreach directly from your phone on Telegram. Tap buttons to view demo, copy DM text, open WhatsApp, or mark as sent.
- **Auto-Sync & Tracking:** Click tracking (via NTFY push notifications) and `/replied` command tracking immediately sync to the Cloudflare KV store and propagate down to the local database.
- **Serverless Webhook:** The Telegram bot runs 100% on Cloudflare Workers, ensuring 99.99% uptime and zero local API polling overhead.

### 5. High-Availability (HA) Firestick + Mac Split-Brain
- **Offloaded Background Jobs:** Heavy scraping, AI generation, and scheduling run 24/7 on an Android Firestick via Termux to save Mac battery and resources.
- **Cloudflare KV Sync:** The Mac and Firestick never talk directly; they both sync their state, stats, and queues (like `ig_done_queue` and `wa_done_queue`) via Cloudflare KV, creating a resilient split-brain architecture.
"""

code = code.replace("### 4. Smart Multi-Model Copywriter", ha_section + "\n### 6. Smart Multi-Model Copywriter")
code = code.replace("### 5. Interactive Kanban Pipeline & CRM", "### 7. Interactive Kanban Pipeline & CRM")
code = code.replace("### 6. Campaign Analytics & A/B Testing", "### 8. Campaign Analytics & A/B Testing")
code = code.replace("### 7. Settings & Configuration", "### 9. Settings & Configuration")

# Update Tech Stack
code = code.replace("| Deployment | Cloudflare Tunnel (local), GitHub Pages (demos) |", "| Deployment | Cloudflare Workers (Bot & Demos), Cloudflare KV (State Sync) |")
code = code.replace("| Process Management | macOS LaunchAgent (`com.leadflow.app.plist`) |", "| Process Management | macOS LaunchAgent + Firestick Termux (24/7 Headless) |")
code = code.replace("| Email | Gmail SMTP + IMAP (App Password) |", "| Outreach | Gmail (SMTP/IMAP) + Telegram UI (IG DM / WA Mode) |")

with open("/Users/chandan/leadflow/README.md", "w") as f:
    f.write(code)
