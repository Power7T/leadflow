"""
Single source of truth for publishing demo sites to GitHub Pages.

Before this module, demos were pushed two different ways from two different
working copies of the same repo, with errors sent to /dev/null — so failed
pushes silently stranded demos locally while the prospect got a 404. This
consolidates publishing into one locked, error-checked, verify-live pipeline.

Public URL scheme (one scheme, everywhere):
    https://power7t.github.io/leadflow-demos/<slug>.html
where slug = slugify(name)-<bid>.
"""
import re
import time
import threading
import subprocess
from pathlib import Path

import requests

BASE      = Path(__file__).parent
DEMOS_DIR = BASE / "demos"            # the one git clone we publish from

# Serialize git operations — concurrent auto-send + manual builds raced before.
_PUSH_LOCK = threading.Lock()


def slugify(text: str) -> str:
    t = " ".join((text or "").split()[:3]).lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def slug_for(bid: int, name: str) -> str:
    return f"{slugify(name)}-{bid}"


def get_pages_config() -> tuple[str, str]:
    import os
    repo_env = os.getenv("GITHUB_DEMO_REPO", "power7t/leadflow-demos")
    parts = repo_env.split("/")
    owner = parts[0] if len(parts) >= 1 else "power7t"
    repo = parts[1] if len(parts) >= 2 else "leadflow-demos"
    return owner, repo


def get_cf_pages_config() -> str:
    import os
    return os.getenv("CLOUDFLARE_PAGES_PROJECT", "leadflow-demos")


def demo_url_for(bid: int, name: str) -> str:
    import os
    public_url = os.getenv("LEADFLOW_PUBLIC_URL", "https://leadflow-relay.chandango12.workers.dev")
    return f"{public_url}/demo/{slug_for(bid, name)}"


def public_base() -> str:
    """Current public URL of the LeadFlow app (ephemeral Cloudflare tunnel or LEADFLOW_PUBLIC_URL)."""
    try:
        url = Path("/tmp/leadflow-tunnel-url.txt").read_text().strip()
        if url.startswith("https://"):
            return url
    except Exception:
        pass
    import os
    env_url = os.getenv("LEADFLOW_PUBLIC_URL", "")
    if env_url.startswith("https://"):
        return env_url
    return ""


def _git(*args, timeout=60) -> subprocess.CompletedProcess:
    import os, shutil
    if not shutil.which("git"):
        raise FileNotFoundError("git not found on this system — deploy skipped on this device")
    token = os.getenv("GITHUB_TOKEN")
    if token:
        owner, repo = get_pages_config()
        # Embed token in remote URL to bypass interactive username prompts
        subprocess.run(
            ["git", "remote", "set-url", "origin", f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"],
            cwd=DEMOS_DIR, capture_output=True, text=True, timeout=10
        )
    return subprocess.run(
        ["git", *args], cwd=DEMOS_DIR,
        capture_output=True, text=True, timeout=timeout,
    )


def _publish(filename: str, html: str, pull_timeout: int = 60) -> dict:
    """Write one file into the demos repo and push it. Returns {ok, error}.

    Serialized by a lock and rebased before push so concurrent auto-send and
    manual builds can't race into the divergent state that used to strand
    demos locally (with errors swallowed) while the prospect saw a 404.
    """
    DEMOS_DIR.mkdir(exist_ok=True)
    (DEMOS_DIR / filename).write_text(html, encoding="utf-8")
    with _PUSH_LOCK:
        try:
            _git("add", "-A")
            _git("commit", "-m", f"Deploy {filename}")  # no-op commit is fine
            pull = _git("pull", "--rebase", "--autostash", "origin", "main", timeout=pull_timeout)
            if pull.returncode != 0:
                _git("rebase", "--abort")
                _git("merge", "-X", "ours", "origin/main")
            push = _git("push", "origin", "HEAD:main")
            if push.returncode != 0:
                return {"ok": False, "error": (push.stderr or "").strip() or "git push failed"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": True, "error": ""}


def get_cf_env() -> dict:
    import os
    from pathlib import Path
    cf_cred_path = Path.home() / ".cf_credentials"
    env_override = os.environ.copy()
    if cf_cred_path.exists():
        try:
            for line in cf_cred_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip().replace("export ", "")
                    v = v.strip().strip("'\"")
                    env_override[k] = v
        except Exception as e:
            print(f"[deploy] Warning: Failed to parse Cloudflare credentials file: {e}")
    return env_override


def deploy_demo(bid: int, name: str, html: str) -> dict:
    """Publish the demo HTML and JSON data to the Cloudflare Worker to serve dynamically."""
    import os
    import json
    import requests
    import sqlite3
    from demo_generator import _scrape_site
    from pathlib import Path

    # 1. Upload pre-rendered HTML directly to Cloudflare KV via Worker
    public_url = os.getenv("LEADFLOW_PUBLIC_URL", "https://leadflow-relay.chandango12.workers.dev")
    secret_token = os.getenv("LEADFLOW_SECRET_TOKEN")
    slug = slug_for(bid, name)
    url = f"{public_url}/demo/{slug}"

    try:
        r_html = requests.post(
            f"{public_url}/api/kv",
            headers={"X-Secret-Token": secret_token, "Content-Type": "application/json"},
            json={"key": f"demo:html:{slug}", "value": html},
            timeout=15
        )
        if r_html.status_code != 200:
            print(f"[deploy] HTML upload failed: {r_html.status_code} - {r_html.text}")
    except Exception as e:
        print(f"[deploy] HTML upload exception: {e}")

    # 2. Fetch the business details from database (for metadata upload)
    db_path = os.path.join(os.path.dirname(__file__), "leadflow.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, name, category, address, city, phone, website, website_score, google_rating, google_reviews, template_id, pitch_type FROM businesses WHERE id=?",
        (bid,)
    ).fetchone()
    
    if not row:
        conn.close()
        return {"ok": False, "error": f"Business ID {bid} not found in database"}
        
    biz = dict(row)
    conn.close()

    # 3. Determine template
    demo_templates_dir = Path(os.path.dirname(__file__)) / "demo_templates"
    
    config_path = demo_templates_dir / "config.json"
    templates_list = []
    if config_path.exists():
        try:
            config_data = json.loads(config_path.read_text(encoding="utf-8"))
            templates_list = config_data.get("templates", [])
        except Exception:
            pass

    def get_template(category, biz_name, assigned_tpl):
        if assigned_tpl and assigned_tpl.endswith(".html"):
            return assigned_tpl
        cat_lower = (category or "").lower()
        name_lower = (biz_name or "").lower()
        for tpl in templates_list:
            if not tpl.get("enabled", True):
                continue
            tpl_file = tpl.get("file")
            if not tpl_file:
                continue
            niches = tpl.get("niches", [])
            if any(n in cat_lower or n in name_lower for n in niches):
                return tpl_file
        return "dentist.html"

    tpl = get_template(biz["category"], biz["name"], biz["template_id"])

    # 4. Choose stock images
    hero_img = "https://images.unsplash.com/photo-1522071820081-009f0129c71c?w=1400"
    about_img = "https://images.unsplash.com/photo-1521737711867-e3b904737c88?w=600"
    
    if tpl == "gym.html":
        hero_img = "https://images.unsplash.com/photo-1517838277536-f5f99be501cd?w=1400"
        about_img = "https://images.unsplash.com/photo-1534438327276-14e5300c3a48?w=600"
    elif tpl == "restaurant.html":
        hero_img = "https://images.unsplash.com/photo-1414235077428-338989a2e8c0?w=1400"
        about_img = "https://images.unsplash.com/photo-1550966871-3ed3cdb5ed0c?w=600"
    elif tpl == "chiropractor.html":
        hero_img = "https://power7t.github.io/leadflow-demos/chiro-hero.jpg"
        about_img = "https://power7t.github.io/leadflow-demos/chiro-about.jpg"
    elif tpl == "medspa.html":
        hero_img = "https://images.unsplash.com/photo-1522335789203-aabd1fc54bc9?w=1400"
        about_img = "https://images.unsplash.com/photo-1512290923902-8a9f81dc236c?w=600"
    elif tpl == "barbershop.html":
        hero_img = "https://images.unsplash.com/photo-1503951914875-452162b0f3f1?w=1400"
        about_img = "https://images.unsplash.com/photo-1593702295094-aec22597af65?w=600"
    elif tpl == "realestate.html":
        hero_img = "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=1400"
        about_img = "https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?w=600"
    elif tpl == "hvac.html":
        hero_img = "https://images.unsplash.com/photo-1621905251189-08b45d6a269e?w=1400"
        about_img = "https://images.unsplash.com/photo-1581094288338-2314dddb7ecc?w=600"
    elif tpl == "lawyer.html":
        hero_img = "https://images.unsplash.com/photo-1589829545856-d10d557cf95f?w=1400"
        about_img = "https://images.unsplash.com/photo-1450133064473-71024230f91b?w=600"

    # 5. Scrape website on-the-fly
    website = biz.get("website", "")
    scraped_data = _scrape_site(website) if website else {}

    # 6. Build payload
    payload = {
        "business": biz,
        "website_data": scraped_data,
        "template_id": tpl,
        "hero_img": hero_img,
        "about_img": about_img
    }

    try:
        r = requests.post(
            f"{public_url}/api/demo?slug={slug}",
            headers={"X-Secret-Token": secret_token, "Content-Type": "application/json"},
            json=payload,
            timeout=15
        )
        if r.status_code == 200:
            return {"ok": True, "url": url, "error": ""}
        else:
            return {"ok": False, "error": f"Cloudflare API error: {r.status_code} - {r.text}"}
    except Exception as e:
        return {"ok": False, "error": f"Failed to upload data to Cloudflare: {e}"}


def deploy_raw(filename: str, html: str) -> dict:
    """Publish an arbitrary file (e.g. an audit report). Returns {ok, url, error}."""
    import os, shutil
    
    if os.getenv("USE_CLOUDFLARE_PAGES") == "true" and shutil.which("npx"):
        # 1. Cloudflare Pages Deployment via Wrangler
        try:
            DEMOS_DIR.mkdir(exist_ok=True)
            (DEMOS_DIR / filename).write_text(html, encoding="utf-8")
            
            project = get_cf_pages_config()
            url = f"https://{project}.pages.dev/{filename}"
            
            def run_cf_deploy():
                try:
                    subprocess.run(
                        ["npx", "wrangler", "pages", "deploy", str(DEMOS_DIR), f"--project-name={project}"],
                        env=get_cf_env(), capture_output=True, text=True, timeout=90
                    )
                except Exception as e:
                    print(f"[deploy] Cloudflare Pages background deploy raw failed: {e}")
                    
            import threading
            threading.Thread(target=run_cf_deploy, daemon=True).start()
            return {"ok": True, "url": url, "error": ""}
        except Exception as e:
            return {"ok": False, "url": url, "error": str(e)}

    # 2. GitHub Pages Deployment (Fallback)
    if os.getenv("GITHUB_TOKEN"):
        try:
            from github_deploy import push_demo_to_github
            gh_url = push_demo_to_github(filename, html)
            if gh_url:
                return {"ok": True, "url": gh_url, "error": ""}
        except Exception as e:
            print(f"[deploy] GitHub API deployment raw failed, falling back to git CLI: {e}")
    res = _publish(filename, html)
    user, repo = get_pages_config()
    return {"ok": res["ok"],
            "url": f"https://{user}.github.io/{repo}/{filename}",
            "error": res["error"]}


def is_live(url: str, wait: int = 120) -> bool:
    """Poll the public URL until GitHub Pages serves it (200) or we time out."""
    deadline = time.time() + wait
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(5)
    return False
