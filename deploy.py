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
PAGES_USER = "power7t"                 # GitHub Pages account (case-insensitive)
PAGES_REPO = "leadflow-demos"

# Serialize git operations — concurrent auto-send + manual builds raced before.
_PUSH_LOCK = threading.Lock()


def slugify(text: str) -> str:
    t = " ".join((text or "").split()[:3]).lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def slug_for(bid: int, name: str) -> str:
    return f"{slugify(name)}-{bid}"


def demo_url_for(bid: int, name: str) -> str:
    return f"https://{PAGES_USER}.github.io/{PAGES_REPO}/{slug_for(bid, name)}.html"


def public_base() -> str:
    """Current public URL of the LeadFlow app (ephemeral Cloudflare tunnel)."""
    try:
        url = Path("/tmp/leadflow-tunnel-url.txt").read_text().strip()
        if url.startswith("https://"):
            return url
    except Exception:
        pass
    return ""


def _git(*args, timeout=60) -> subprocess.CompletedProcess:
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


def deploy_demo(bid: int, name: str, html: str) -> dict:
    """Write, commit and push one demo. Returns {ok, url, error}.

    ok=True only means the push to GitHub succeeded — call is_live() if you need
    to confirm Pages has actually published it (e.g. before emailing the link).
    """
    url = demo_url_for(bid, name)
    import os
    if os.getenv("GITHUB_TOKEN"):
        try:
            from github_deploy import push_demo_to_github
            filename = f"{slug_for(bid, name)}.html"
            gh_url = push_demo_to_github(filename, html)
            if gh_url:
                return {"ok": True, "url": gh_url, "error": ""}
        except Exception as e:
            print(f"[deploy] GitHub API deployment failed, falling back to git CLI: {e}")
    res = _publish(f"{slug_for(bid, name)}.html", html)
    return {"ok": res["ok"], "url": url, "error": res["error"]}


def deploy_raw(filename: str, html: str) -> dict:
    """Publish an arbitrary file (e.g. an audit report). Returns {ok, url, error}."""
    import os
    if os.getenv("GITHUB_TOKEN"):
        try:
            from github_deploy import push_demo_to_github
            gh_url = push_demo_to_github(filename, html)
            if gh_url:
                return {"ok": True, "url": gh_url, "error": ""}
        except Exception as e:
            print(f"[deploy] GitHub API deployment raw failed, falling back to git CLI: {e}")
    res = _publish(filename, html)
    return {"ok": res["ok"],
            "url": f"https://{PAGES_USER}.github.io/{PAGES_REPO}/{filename}",
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
