import os
import json
import sqlite3
import shutil
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

BASE = Path(__file__).parent.resolve()
DB_PATH = BASE / "leadflow.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_stats():
    conn = get_conn()
    stats = {}
    for status in ("new", "approved", "sent", "replied", "skipped", "closed", "opted_out"):
        row = conn.execute("SELECT COUNT(*) as c FROM businesses WHERE status=? AND (source IS NULL OR (source NOT IN ('facebook_miami', 'instagram_reach', 'test_leads')))", (status,)).fetchone()
        stats[status] = row["c"]
    row_miami = conn.execute("SELECT COUNT(*) as c FROM businesses WHERE source='facebook_miami' AND status='new'").fetchone()
    stats["miami_new"] = row_miami["c"]
    row_ig = conn.execute("SELECT COUNT(*) as c FROM businesses WHERE source='instagram_reach' AND status='new'").fetchone()
    stats["instagram_reach_new"] = row_ig["c"]
    row_test = conn.execute("SELECT COUNT(*) as c FROM businesses WHERE source='test_leads' AND status='new'").fetchone()
    stats["test_leads_new"] = row_test["c"]
    cfg_row = conn.execute("SELECT enabled FROM scheduler_config LIMIT 1").fetchone()
    stats["autopilot_active"] = bool(cfg_row["enabled"]) if cfg_row else False
    conn.close()
    return stats

class MockRequest:
    class QueryParams:
        def get(self, key, default=None):
            return default
    query_params = QueryParams()
    url = "http://localhost:8765"

mock_request = MockRequest()

def ctx(page: str, **extra):
    return {"request": mock_request, "page": page, "stats": get_stats(), **extra}

def run_replication():
    print("[Replicator] Loading Jinja2 templates...")
    env = Environment(loader=FileSystemLoader(str(BASE / "templates")))
    
    # Support slug_for filter/global from server
    from server import slug_for
    env.globals['slug_for'] = slug_for
    
    pages_to_render = {}
    
    # 1. RENDER INDEX (HOME)
    print("[Replicator] Rendering dashboard home...")
    conn = get_conn()
    sent_rows = conn.execute("""
        SELECT b.id, b.name, b.category, b.website, b.demo_tunnel_url,
               c.email, o.channel, o.sent_at, o.opened, o.clicked, o.replied
        FROM outreach o
        JOIN businesses b ON b.id = o.business_id
        LEFT JOIN contacts c ON c.business_id = b.id
        WHERE o.status = 'sent' AND o.channel = 'email'
        ORDER BY o.sent_at DESC LIMIT 15
    """).fetchall()
    recent_sent = [dict(r) for r in sent_rows]
    
    found_rows = conn.execute("""
        SELECT b.id, b.name, b.category, b.website, b.lead_score, b.found_at, b.status,
               c.email, c.instagram
        FROM businesses b
        LEFT JOIN contacts c ON c.business_id = b.id
        WHERE b.status IN ('new', 'approved')
        ORDER BY b.found_at DESC LIMIT 15
    """).fetchall()
    recent_found = [dict(r) for r in found_rows]
    
    stats_data = {
        "total_scraped": conn.execute("SELECT COUNT(*) FROM businesses").fetchone()[0],
        "total_sent": conn.execute("SELECT COUNT(*) FROM outreach WHERE status='sent' AND channel='email'").fetchone()[0],
        "total_followups": conn.execute("SELECT COUNT(*) FROM follow_ups WHERE status='sent' AND channel='email'").fetchone()[0],
        "total_replied": conn.execute("SELECT COUNT(*) FROM outreach WHERE replied=1").fetchone()[0],
        "total_opened": conn.execute("SELECT COUNT(*) FROM outreach WHERE opened=1").fetchone()[0],
        "total_clicked": conn.execute("SELECT COUNT(*) FROM outreach WHERE clicked=1").fetchone()[0],
    }
    
    pending_init_rows = conn.execute("""
        SELECT b.name, c.email, b.assigned_sender_email, o.scheduled_at
        FROM businesses b
        JOIN contacts c ON c.business_id = b.id
        JOIN outreach o ON o.business_id = b.id
        WHERE o.status = 'draft' AND o.channel = 'email' AND o.scheduled_at IS NOT NULL
        ORDER BY o.scheduled_at ASC
        LIMIT 5
    """).fetchall()
    pending_init_rows = [dict(r) for r in pending_init_rows]
    
    if len(pending_init_rows) < 5:
        backfill_limit = 5 - len(pending_init_rows)
        backfill_rows = conn.execute("""
            SELECT b.name, c.email, b.assigned_sender_email, 'Pending AI drafting' as scheduled_at
            FROM businesses b
            LEFT JOIN contacts c ON c.business_id = b.id
            WHERE b.status IN ('new', 'approved') AND b.lead_score >= 25 AND c.email IS NOT NULL AND c.email != ''
            AND b.id NOT IN (SELECT business_id FROM outreach WHERE status = 'draft')
            ORDER BY b.lead_score DESC
            LIMIT ?
        """, (backfill_limit,)).fetchall()
        pending_init_rows.extend([dict(r) for r in backfill_rows])
        
    pending_initials = pending_init_rows
    
    pending_fup_rows = conn.execute("""
        SELECT b.name, c.email, b.assigned_sender_email, f.scheduled_for
        FROM follow_ups f
        JOIN businesses b ON b.id = f.business_id
        LEFT JOIN contacts c ON c.business_id = b.id
        WHERE f.status = 'pending' AND b.status = 'sent' AND c.email IS NOT NULL
        ORDER BY f.scheduled_for ASC LIMIT 5
    """).fetchall()
    pending_followups = []
    for r in pending_fup_rows:
        d = dict(r)
        if d["scheduled_for"]:
            d["scheduled_for"] = d["scheduled_for"].replace("T", " ").split(".")[0]
        pending_followups.append(d)
        
    stuck_approved_count = conn.execute("SELECT COUNT(*) FROM businesses b LEFT JOIN contacts c ON c.business_id=b.id WHERE b.status='approved' AND (c.email IS NULL OR c.email='')").fetchone()[0]
    total_pending_followups = conn.execute("SELECT COUNT(*) FROM follow_ups WHERE status='pending'").fetchone()[0]
    conn.close()
    
    from database import get_emails_sent_today
    sent_today = get_emails_sent_today()
    
    from server import _get_scheduler_cfg
    cfg = _get_scheduler_cfg()
    
    tpl_index = env.get_template("index.html")
    pages_to_render["dashboard_index.html"] = tpl_index.render(
        ctx("home",
            cfg=cfg,
            sent_today=sent_today,
            recent_sent=recent_sent,
            recent_found=recent_found,
            stats_data=stats_data,
            pending_initials=pending_initials,
            pending_followups=pending_followups,
            stuck_approved_count=stuck_approved_count,
            total_pending_followups=total_pending_followups
        )
    )
    
    # 2. RENDER LEADS
    print("[Replicator] Rendering active leads...")
    from database import get_all_active_leads, get_all_leads_for_kanban, get_analytics
    leads = get_all_active_leads()
    for l in leads:
        try:
            l["interactions"] = json.loads(l.get("interactions_json") or "[]")
        except:
            l["interactions"] = []
            
    tpl_leads = env.get_template("leads.html")
    pages_to_render["dashboard_leads.html"] = tpl_leads.render(ctx("leads", leads=leads))
    
    # 3. RENDER SAAS LEADS
    saas_leads = [l for l in leads if l.get("pitch_type") in ("leadflow_saas", "both")]
    tpl_saas = env.get_template("saas_leads.html")
    pages_to_render["dashboard_saas.html"] = tpl_saas.render(ctx("saas_leads", leads=saas_leads))
    
    # 4. RENDER INSTAGRAM REACH
    ig_leads = [l for l in leads if l.get("source") == "instagram_reach"]
    tpl_ig = env.get_template("instagram_reach.html")
    pages_to_render["dashboard_ig.html"] = tpl_ig.render(ctx("instagram_reach", leads=ig_leads))
    
    # 5. RENDER TEST LEADS
    test_leads = [l for l in leads if l.get("source") == "test_leads"]
    tpl_test = env.get_template("test_leads.html")
    pages_to_render["dashboard_test.html"] = tpl_test.render(ctx("test_leads", leads=test_leads))
    
    # 6. RENDER KANBAN
    print("[Replicator] Rendering pipeline...")
    all_leads = get_all_leads_for_kanban()
    by_status = {}
    for lead in all_leads:
        s = lead["status"]
        if s == "sent":
            if lead.get("demo_viewed") or lead.get("email_clicked"):
                s = "demo_viewed"
            elif lead.get("email_opened"):
                s = "opened"
        elif s == "closed":
            s = "converted"
        by_status.setdefault(s, []).append(lead)
        
    tpl_kanban = env.get_template("kanban.html")
    pages_to_render["dashboard_kanban.html"] = tpl_kanban.render(ctx("kanban", leads_by_status=by_status))
    
    # 7. RENDER ANALYTICS
    print("[Replicator] Rendering analytics...")
    a = get_analytics()
    tpl_analytics = env.get_template("analytics.html")
    pages_to_render["dashboard_analytics.html"] = tpl_analytics.render(ctx("analytics", a=a))
    
    # 8. RENDER TEMPLATES
    tpl_templates = env.get_template("templates.html")
    pages_to_render["dashboard_templates.html"] = tpl_templates.render(ctx("templates"))
    
    # 9. RENDER DEMOS
    print("[Replicator] Rendering demos list...")
    conn = get_conn()
    demo_rows = conn.execute("""
        SELECT b.id, b.name, b.city, b.country, b.category, b.website, b.lead_score, b.demo_tunnel_url, b.template_id
        FROM businesses b
        WHERE b.status NOT IN ('skipped', 'opted_out')
        ORDER BY b.lead_score DESC, b.found_at DESC
    """).fetchall()
    conn.close()
    
    from server import DEMOS_DIR, _get_demo_base_url
    businesses = []
    for r in demo_rows:
        b = dict(r)
        b["has_demo"] = ((DEMOS_DIR / f"{slug_for(b['id'], b.get('name',''))}.html").exists()
                         or (DEMOS_DIR / f"{b['id']}.html").exists())
        businesses.append(b)
        
    tpl_demos = env.get_template("demos.html")
    pages_to_render["dashboard_demos.html"] = tpl_demos.render(
        ctx("demos", businesses=businesses, demo_base=_get_demo_base_url(), avail_templates=[])
    )
    
    # 10. RENDER FIND
    tpl_find = env.get_template("find.html")
    pages_to_render["dashboard_find.html"] = tpl_find.render(ctx("find", sched=cfg))
    
    # 11. RENDER SETTINGS
    from dotenv import dotenv_values
    env_vals = dotenv_values(".env")
    
    # Mask all secrets so they are not exposed in the public static copy on GitHub / Cloudflare Pages
    masked_env = {}
    for k, v in env_vals.items():
        if not v:
            masked_env[k] = ""
            continue
        # Mask sensitive keys
        if any(sec in k for sec in ["KEY", "PASSWORD", "TOKEN", "SID", "AUTH", "SECRET"]):
            if len(v) > 8:
                masked_env[k] = v[:4] + "..." + v[-4:]
            else:
                masked_env[k] = "********"
        elif k == "SENDER_EMAIL":
            # Mask emails slightly
            emails = [e.strip() for e in v.split(",") if e.strip()]
            masked_emails = []
            for email in emails:
                if "@" in email:
                    name, domain = email.split("@", 1)
                    masked_emails.append(name[:2] + "..." + "@" + domain)
                else:
                    masked_emails.append("...")
            masked_env[k] = ", ".join(masked_emails)
        else:
            masked_env[k] = v
            
    tpl_settings = env.get_template("settings.html")
    pages_to_render["dashboard_settings.html"] = tpl_settings.render(ctx("settings", env=masked_env))
    
    # 12. RENDER SENT OUTREACH LOGS
    print("[Replicator] Rendering sent logs...")
    conn = get_conn()
    sent_leads_rows = conn.execute("""
        SELECT b.id, b.name, b.category, b.website, b.demo_tunnel_url,
               c.email, o.channel, o.sent_at, o.opened, o.clicked, o.replied
        FROM outreach o
        JOIN businesses b ON b.id = o.business_id
        LEFT JOIN contacts c ON c.business_id = b.id
        WHERE o.status = 'sent' AND o.channel = 'email'
        ORDER BY o.sent_at DESC
    """).fetchall()
    conn.close()
    sent_leads = [dict(r) for r in sent_leads_rows]
    tpl_sent = env.get_template("sent.html")
    pages_to_render["dashboard_sent.html"] = tpl_sent.render(ctx("sent", leads=sent_leads))
    
    # 13. RENDER FOLLOWUPS
    print("[Replicator] Rendering followups...")
    from database import get_all_follow_ups
    fus = get_all_follow_ups()
    tpl_fus = env.get_template("followups.html")
    pages_to_render["dashboard_followups.html"] = tpl_fus.render(ctx("followups", followups=fus))

    # --- INJECT PASSCODE WALL & REWRITE LINKS ---
    print("[Replicator] Transforming page links and injecting passcode security...")
    login_head = """
    <!-- PASSCODE SECURITY WALL -->
    <style>
      #lf-login-overlay {
        position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
        background: #0b0c10; color: #c5c6c7; z-index: 999999;
        display: flex; align-items: center; justify-content: center;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      }
      .lf-login-card {
        background: #151a22; padding: 36px; border-radius: 12px;
        box-shadow: 0 12px 40px rgba(0,0,0,0.65); width: 340px;
        border: 1px solid #00c896; text-align: center;
      }
      .lf-login-card h2 { margin: 0 0 10px 0; color: #fff; font-size: 22px; font-weight: 600; }
      .lf-login-card p { margin: 0 0 24px 0; color: #8a99ad; font-size: 13px; }
      .lf-login-input {
        width: 100%; padding: 12px 16px; margin: 8px 0; border-radius: 8px;
        border: 1px solid #2d3848; background: #0b0c10; color: #fff;
        box-sizing: border-box; font-size: 14px; outline: none; transition: border-color 0.2s;
      }
      .lf-login-input:focus { border-color: #00c896; }
      .lf-login-btn {
        width: 100%; padding: 12px; border-radius: 8px; border: none;
        background: #00c896; color: #0b0c10; font-weight: bold; cursor: pointer;
        font-size: 15px; margin-top: 14px; transition: opacity 0.2s;
      }
      .lf-login-btn:hover { opacity: 0.9; }
      .lf-error { color: #ff4a4a; font-size: 13px; text-align: center; margin-top: 12px; display: none; font-weight: 500; }
    </style>
    <script>
      (function() {
        var u = localStorage.getItem("lf_user");
        var p = localStorage.getItem("lf_pass");
        if (u === "chandan" && p === "Supergo12@") {
          document.addEventListener("DOMContentLoaded", function() {
            var overlay = document.getElementById("lf-login-overlay");
            if (overlay) overlay.style.display = "none";
          });
        }
      })();
      function lfLogin() {
        var u = document.getElementById("lf-user").value;
        var p = document.getElementById("lf-pass").value;
        if (u === "chandan" && p === "Supergo12@") {
          localStorage.setItem("lf_user", u);
          localStorage.setItem("lf_pass", p);
          document.getElementById("lf-login-overlay").style.display = "none";
        } else {
          document.getElementById("lf-error-msg").style.display = "block";
        }
      }
    </script>
    """
    
    login_body = """
    <div id="lf-login-overlay">
      <div class="lf-login-card">
        <h2>🔒 LeadFlow Command Center</h2>
        <p>Enter your authorization credentials to continue</p>
        <input type="text" id="lf-user" class="lf-login-input" placeholder="Username" autocomplete="off" />
        <input type="password" id="lf-pass" class="lf-login-input" placeholder="Password" />
        <button onclick="lfLogin()" class="lf-login-btn">Sign In</button>
        <div id="lf-error-msg" class="lf-error">Invalid credentials. Access Denied.</div>
      </div>
    </div>
    """
    
    for filename, html in pages_to_render.items():
        # Inject login CSS and JS scripts in head
        html = html.replace("<head>", f"<head>\n{login_head}", 1)
        # Inject login form overlay right after body starts
        html = html.replace("<body>", f"<body>\n{login_body}", 1)
        # Rewrite style.css link
        html = html.replace('href="/static/style.css"', 'href="./style.css"')
        
        # Rewrite sidebar/nav links
        html = html.replace('href="/"', 'href="./dashboard_index.html"')
        html = html.replace('href="/find"', 'href="./dashboard_find.html"')
        html = html.replace('href="/leads"', 'href="./dashboard_leads.html"')
        html = html.replace('href="/saas-leads"', 'href="./dashboard_saas.html"')
        html = html.replace('href="/instagram-reach"', 'href="./dashboard_ig.html"')
        html = html.replace('href="/test-leads"', 'href="./dashboard_test.html"')
        html = html.replace('href="/kanban"', 'href="./dashboard_kanban.html"')
        html = html.replace('href="/followups"', 'href="./dashboard_followups.html"')
        html = html.replace('href="/sent"', 'href="./dashboard_sent.html"')
        html = html.replace('href="/templates"', 'href="./dashboard_templates.html"')
        html = html.replace('href="/demos"', 'href="./dashboard_demos.html"')
        html = html.replace('href="/analytics"', 'href="./dashboard_analytics.html"')
        html = html.replace('href="/settings"', 'href="./dashboard_settings.html"')
        
        # Stop stats polling errors on static copy
        html = html.replace("setInterval(pollStats, 5000);", "")
        
        pages_to_render[filename] = html
        
    # Write files locally to demos/ directory (shared with demo_server)
    demos_dir = BASE / "demos"
    demos_dir.mkdir(exist_ok=True)
    
    style_content = (BASE / "static" / "style.css").read_text(encoding="utf-8")
    (demos_dir / "style.css").write_text(style_content, encoding="utf-8")
    
    for filename, html in pages_to_render.items():
        (demos_dir / filename).write_text(html, encoding="utf-8")
    
    # Redirect root index.html → dashboard home
    (demos_dir / "index.html").write_text(
        '<meta http-equiv="refresh" content="0; url=./dashboard_index.html">',
        encoding="utf-8"
    )
    
    # --- DEPLOY: Cloudflare Pages (primary) or GitHub Pages (fallback) ---
    import shutil as _shutil
    import subprocess as _subprocess
    
    npx_path = _shutil.which("npx")
    cf_project = os.getenv("CF_PAGES_PROJECT", os.getenv("CLOUDFLARE_PAGES_PROJECT", "leadflow-demos"))
    use_cf = os.getenv("USE_CLOUDFLARE_PAGES", "true").lower() in ("true", "1", "yes")
    
    deployed_cf = False
    if use_cf and npx_path:
        print(f"[Replicator] Deploying to Cloudflare Pages project '{cf_project}' via Wrangler...")
        try:
            from pathlib import Path
            real_home = str(Path.home())
            wrangler_env = os.environ.copy()
            wrangler_env["HOME"] = real_home
            wrangler_env["WRANGLER_HOME"] = f"{real_home}/.wrangler"
            res = _subprocess.run(
                [npx_path, "wrangler", "pages", "deploy", str(demos_dir),
                 f"--project-name={cf_project}", "--commit-dirty=true"],
                capture_output=True, text=True, timeout=120, cwd=str(BASE),
                env=wrangler_env
            )
            output = (res.stdout + res.stderr)[-1200:]
            if res.returncode == 0:
                print(f"[Replicator] ✅ Live on Cloudflare Pages: https://{cf_project}.pages.dev/dashboard_index.html")
                deployed_cf = True
            else:
                print(f"[Replicator] ⚠️  Wrangler deploy failed (rc={res.returncode}):\n{output}")
        except Exception as _e:
            print(f"[Replicator] Wrangler error: {_e}")
    
    if not deployed_cf:
        # GitHub Pages fallback (Firestick / wrangler unavailable)
        print("[Replicator] Uploading to GitHub Pages (fallback)...")
        from github_deploy import push_demo_to_github
        push_demo_to_github("style.css", style_content)
        for filename, html in pages_to_render.items():
            url = push_demo_to_github(filename, html)
            if url:
                print(f"[Replicator] Uploaded: {filename} -> {url}")
    
    print("[Replicator] Dashboard replica successfully deployed!")

if __name__ == "__main__":
    run_replication()
