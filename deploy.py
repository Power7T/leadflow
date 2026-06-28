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
    import os, shutil
    if os.getenv("USE_CLOUDFLARE_PAGES") == "true" and shutil.which("npx"):
        project = get_cf_pages_config()
        return f"https://{project}.pages.dev/{slug_for(bid, name)}.html"
    user, repo = get_pages_config()
    return f"https://{user}.github.io/{repo}/{slug_for(bid, name)}.html"


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


def _publish(filename: str, html: str) -> dict:
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
            pull = _git("pull", "--rebase", "--autostash", "origin", "main")
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
    """Write and publish one demo. Returns {ok, url, error}."""
    import os, shutil
    filename = f"{slug_for(bid, name)}.html"
    
    # Try Cloudflare Pages first if configured AND wrangler/npx is available
    if os.getenv("USE_CLOUDFLARE_PAGES") == "true" and shutil.which("npx"):
        url = demo_url_for(bid, name)
        try:
            # Write file locally to demos directory
            DEMOS_DIR.mkdir(exist_ok=True)
            (DEMOS_DIR / filename).write_text(html, encoding="utf-8")
            
            project = get_cf_pages_config()
            
            def run_cf_deploy():
                try:
                    subprocess.run(
                        ["npx", "wrangler", "pages", "deploy", str(DEMOS_DIR), f"--project-name={project}"],
                        env=get_cf_env(), capture_output=True, text=True, timeout=90
                    )
                except Exception as e:
                    print(f"[deploy] Cloudflare Pages background deploy failed: {e}")
                    
            import threading
            threading.Thread(target=run_cf_deploy, daemon=True).start()
            return {"ok": True, "url": url, "error": ""}
        except Exception as e:
            print(f"[deploy] Cloudflare Pages setup error, attempting fallback: {e}")

    # Fallback/Default: GitHub Pages Deployment via API (works on Firestick without node/git CLI)
    if os.getenv("GITHUB_TOKEN"):
        try:
            from github_deploy import push_demo_to_github
            gh_url = push_demo_to_github(filename, html)
            if gh_url:
                return {"ok": True, "url": gh_url, "error": ""}
        except Exception as e:
            print(f"[deploy] GitHub API deployment failed, falling back to git CLI: {e}")
            
    # Fallback to local git CLI if GITHUB_TOKEN API call fails or is unconfigured
    url = demo_url_for(bid, name)
    res = _publish(filename, html)
    return {"ok": res["ok"], "url": url, "error": res["error"]}


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
