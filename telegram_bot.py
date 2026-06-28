import os
import sys
import sqlite3
import re
import uuid
import logging
from telethon import TelegramClient, events, Button
from dotenv import load_dotenv

# Ensure we can import modules from leadflow folder
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from sender import send_email, parse_subject_body
from database import get_stats, update_business_status, mark_sent, get_conn
from deploy import demo_url_for

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/tmp/leadflow_telegram.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("LeadFlowTelegramBot")

load_dotenv()

API_ID = 24433480
API_HASH = "f0b50e8ba81ea284b4abb3211251a8db"
BOT_TOKEN = os.getenv("TELEGRAM_CONTROL_BOT_TOKEN")
USER_ID_STR = os.getenv("TELEGRAM_CONTROL_USER_ID")

if not BOT_TOKEN:
    logger.warning("TELEGRAM_CONTROL_BOT_TOKEN not found in .env. Bot standing by...")
    import time
    while True:
        time.sleep(3600)

try:
    USER_ID = int(USER_ID_STR) if USER_ID_STR else None
except ValueError:
    USER_ID = None

if not USER_ID:
    logger.warning("TELEGRAM_CONTROL_USER_ID not found or invalid in .env. Bot standing by...")
    import time
    while True:
        time.sleep(3600)

# Initialize the Bot Client using a clean session name
logger.info("Initializing LeadFlow Control Bot...")
bot = TelegramClient("leadflow_control_bot_session", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

current_drafts = []
current_index = 0

def get_pending_drafts():
    conn = get_conn()
    cursor = conn.cursor()
    query = """
        SELECT o.id as draft_id, o.business_id, o.channel, o.draft, o.subject_options,
               b.name as business_name, c.email as contact_email
        FROM outreach o
        JOIN businesses b ON o.business_id = b.id
        LEFT JOIN contacts c ON c.business_id = b.id
        WHERE o.status = 'draft'
          AND b.status IN ('new', 'approved')
        ORDER BY o.id ASC
        LIMIT 5
    """
    try:
        cursor.execute(query)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Error fetching drafts: {e}")
        return []
    finally:
        conn.close()

async def show_current_draft(event, edit=True):
    global current_drafts, current_index
    if not current_drafts:
        current_drafts = get_pending_drafts()
        current_index = 0
        
    if not current_drafts:
        no_drafts_text = "📝 *No pending drafts found in the database.*"
        buttons = [[Button.inline("🔙 Main Menu", b"menu")]]
        if edit:
            await event.edit(no_drafts_text, buttons=buttons, parse_mode="md")
        else:
            await event.respond(no_drafts_text, buttons=buttons, parse_mode="md")
        return
        
    if current_index >= len(current_drafts):
        current_drafts = get_pending_drafts()
        current_index = 0
        if not current_drafts:
            no_drafts_text = "📝 *No pending drafts found in the database.*"
            buttons = [[Button.inline("🔙 Main Menu", b"menu")]]
            if edit:
                await event.edit(no_drafts_text, buttons=buttons, parse_mode="md")
            else:
                await event.respond(no_drafts_text, buttons=buttons, parse_mode="md")
            return
            
    draft = current_drafts[current_index]
    bid = draft["business_id"]
    draft_id = draft["draft_id"]
    name = draft["business_name"]
    email = draft["contact_email"] or "No email found"
    channel = draft["channel"]
    raw_draft = draft["draft"] or ""
    
    subject = ""
    body = raw_draft
    if channel == "email":
        subject, body = parse_subject_body(raw_draft)
        
    demo_url = demo_url_for(bid, name)
    
    msg_text = (
        f"📝 *CAMPAIGN DRAFT REVIEW ({current_index + 1}/{len(current_drafts)})*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏢 *Target:*      `{name}` (ID: `{bid}`)\n"
        f"📡 *Channel:*     `{channel.upper()}`\n"
        f"📧 *Recipient:*   `{email}`\n"
        f"🔗 *Demo Link:*   {demo_url}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    
    if channel == "email":
        msg_text += f"📨 *Subject:* {subject}\n\n*Body:*\n{body}"
    else:
        msg_text += f"💬 *Message:*\n{body}"
        
    if len(msg_text) > 4000:
        msg_text = msg_text[:3900] + "\n\n...[Truncated due to Telegram limit]"
        
    buttons = [
        [
            Button.inline("✅ Send", f"send_{draft_id}"),
            Button.inline("❌ Skip", f"skip_{bid}"),
            Button.inline("⏭️ Next", b"next_draft")
        ],
        [Button.inline("🔙 Main Menu", b"menu")]
    ]
    
    if edit:
        await event.edit(msg_text, buttons=buttons, parse_mode="md")
    else:
        await event.respond(msg_text, buttons=buttons, parse_mode="md")

@bot.on(events.NewMessage)
async def debug_log_handler(event):
    logger.info(f"Incoming message from sender_id: {event.sender_id} | Text: {event.message.text}")

@bot.on(events.NewMessage(pattern='/start|/menu'))
async def send_menu(event):
    if event.sender_id != USER_ID:
        logger.warning(f"Unauthorized sender_id: {event.sender_id} (expected {USER_ID})")
        return
    
    welcome_text = (
        "⚡️ *LEADFLOW™ ADVANCED CONSOLE*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 *Status:* System Operational\n"
        "📡 *Relay Node:* Active\n\n"
        "Select a system option below:"
    )
    
    buttons = [
        [Button.inline("📊 Stats", b"stats"), Button.inline("🚀 Trigger Autopilot", b"trigger")],
        [Button.inline("📝 Pending Drafts", b"drafts"), Button.inline("⚙️ System Status", b"status")],
    ]
    
    await event.respond(welcome_text, buttons=buttons, parse_mode="md")

@bot.on(events.CallbackQuery)
async def callback_handler(event):
    global current_drafts, current_index
    if event.sender_id != USER_ID:
        logger.warning(f"Unauthorized CallbackQuery from sender_id: {event.sender_id}")
        return
        
    data = event.data
    logger.info(f"Callback Query received: {data.decode() if isinstance(data, bytes) else data}")
    
    if data == b"stats":
        stats = get_stats()
        stats_text = (
            "📊 *LEADFLOW LIVE METRICS CONSOLE*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📥 *New Backlog:*   `{stats.get('new', 0):,}` leads\n"
            f"✅ *Approved:*      `{stats.get('approved', 0):,}` leads\n"
            f"🚀 *Sent:*          `{stats.get('sent', 0):,}` emails\n"
            f"💬 *Replied:*       `{stats.get('replied', 0):,}` contacts\n"
            f"⏭️ *Skipped:*       `{stats.get('skipped', 0):,}` leads\n"
            f"💼 *Closed:*        `{stats.get('closed', 0):,}` deals\n"
            f"🚫 *Opted Out:*     `{stats.get('opted_out', 0):,}` leads\n\n"
            f"🤖 *Autopilot:*     `{'ENABLED' if stats.get('autopilot_active') else 'DISABLED'}`"
        )
        buttons = [[Button.inline("🔙 Main Menu", b"menu")]]
        await event.edit(stats_text, buttons=buttons, parse_mode="md")
        
    elif data == b"menu":
        welcome_text = (
            "⚡️ *LEADFLOW™ ADVANCED CONSOLE*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🟢 *Status:* System Operational\n"
            "📡 *Relay Node:* Active\n\n"
            "Select a system option below:"
        )
        buttons = [
            [Button.inline("📊 Stats", b"stats"), Button.inline("🚀 Trigger Autopilot", b"trigger")],
            [Button.inline("📝 Pending Drafts", b"drafts"), Button.inline("⚙️ System Status", b"status")],
        ]
        await event.edit(welcome_text, buttons=buttons, parse_mode="md")
        
    elif data == b"status":
        uptime_out = os.popen("uptime").read().strip()
        procs = os.popen("ps -ef | grep -E 'python3.12 -u' | grep -v grep").read().strip()
        
        status_text = (
            "⚙️ *SYSTEM PROCESS METRICS*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱ *Uptime:* `{uptime_out}`\n\n"
            f"📍 *Daemons Status:*\n"
            f"• API Gateway:    `{'ONLINE' if 'server.py' in procs else 'OFFLINE'}`\n"
            f"• Demo Engine:    `{'ONLINE' if 'demo_server.py' in procs else 'OFFLINE'}`\n"
            f"• Control Bot:    `{'ONLINE' if 'telegram_bot.py' in procs else 'OFFLINE'}`"
        )
            
        buttons = [[Button.inline("🔙 Main Menu", b"menu")]]
        await event.edit(status_text, buttons=buttons, parse_mode="md")
        
    elif data == b"trigger":
        trigger_text = (
            "🚀 *AUTOPILOT JOB SCHEDULER*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Select an action to launch manually in the background:"
        )
        buttons = [
            [Button.inline("📧 Send Leads Batch", b"trig_send"), Button.inline("🔍 Find Leads", b"trig_find")],
            [Button.inline("🔙 Main Menu", b"menu")]
        ]
        await event.edit(trigger_text, buttons=buttons, parse_mode="md")
        
    elif data in (b"trig_send", b"trig_find"):
        job = "send_leads" if data == b"trig_send" else "find_leads"
        import urllib.request
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:8765/autopilot/trigger/{job}",
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                status_code = resp.status
            if status_code == 200:
                result_text = f"✅ Successfully triggered autopilot job: `{job}`!"
            else:
                result_text = f"⚠️ Server returned status code {status_code} for `{job}`."
        except Exception as e:
            result_text = f"❌ Failed to connect to server: {e}"
            
        buttons = [[Button.inline("🔙 Main Menu", b"menu")]]
        await event.edit(result_text, buttons=buttons, parse_mode="md")
        
    elif data == b"drafts":
        current_drafts = get_pending_drafts()
        current_index = 0
        await show_current_draft(event)
        
    elif data.startswith(b"send_"):
        draft_id = int(data.decode().split("_")[1])
        draft_info = next((d for d in current_drafts if d["draft_id"] == draft_id), None)
        if draft_info:
            bid = draft_info["business_id"]
            to_email = draft_info["contact_email"]
            channel = draft_info["channel"]
            raw_draft = draft_info["draft"]
            name = draft_info["business_name"]
            
            if channel == "email" and to_email and raw_draft:
                try:
                    subject, body = parse_subject_body(raw_draft)
                    tracking_id = str(uuid.uuid4())
                    demo_url = demo_url_for(bid, name)
                    
                    send_email(to_email, subject, body, tracking_id, demo_url, business_id=bid)
                    mark_sent(bid, "email", is_autopilot=False, subject_used=subject, tracking_id=tracking_id)
                    update_business_status(bid, "sent")
                    await event.answer("✅ Sent email successfully!", alert=False)
                except Exception as e:
                    await event.answer(f"❌ Send failed: {e}", alert=True)
            else:
                mark_sent(bid, channel, is_autopilot=False)
                update_business_status(bid, "sent")
                await event.answer(f"✅ Marked {channel} as sent!", alert=False)
                
            current_drafts = [d for d in current_drafts if d["draft_id"] != draft_id]
            await show_current_draft(event)
            
    elif data.startswith(b"skip_"):
        bid = int(data.decode().split("_")[1])
        update_business_status(bid, "skipped")
        await event.answer("❌ Lead skipped", alert=False)
        
        current_drafts = [d for d in current_drafts if d["business_id"] != bid]
        await show_current_draft(event)
        
    elif data == b"next_draft":
        current_index += 1
        await show_current_draft(event)

@bot.on(events.NewMessage)
async def text_handler(event):
    if event.sender_id != USER_ID:
        return
        
    text = event.message.text
    if text.startswith("/search "):
        query_str = text.replace("/search ", "").strip()
        if not query_str:
            await event.respond("Please provide a query: `/search <business name>`")
            return
            
        conn = get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT id, name, category, website, status FROM businesses WHERE name LIKE ? LIMIT 5",
                (f"%{query_str}%",)
            )
            rows = cursor.fetchall()
            if not rows:
                await event.respond(f"🔍 No leads found matching `{query_str}`.")
                return
                
            res_text = f"🔍 *Search results for '{query_str}':*\n\n"
            for r in rows:
                res_text += (
                    f"• *{r['name']}* (ID: {r['id']})\n"
                    f"  Category: {r['category'] or 'N/A'}\n"
                    f"  Website: {r['website'] or 'N/A'}\n"
                    f"  Status: `{r['status']}`\n\n"
                )
            await event.respond(res_text, parse_mode="md")
        except Exception as e:
            await event.respond(f"❌ Search error: {e}")
        finally:
            conn.close()

logger.info("Bot is running. Listening for events...")
bot.run_until_disconnected()
