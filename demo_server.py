#!/usr/bin/env python3.12
"""
Standalone demo site server — port 8766.
Serves only demo HTML files from the demos/ directory.
Gets its own Cloudflare tunnel so the URL shared with prospects
has zero connection to the main LeadFlow dashboard.
"""
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

BASE      = Path(__file__).parent
DEMOS_DIR = BASE / "demos"
DEMOS_DIR.mkdir(exist_ok=True)

app = FastAPI()


@app.get("/")
def index():
    files = sorted(DEMOS_DIR.glob("*.html"))
    links = "".join(f'<li><a href="/demo/{f.stem}">{f.stem}</a></li>' for f in files)
    return HTMLResponse(f"<html><body><ul>{links}</ul></body></html>")


@app.get("/demo/{bid}")
def serve_demo(bid: int):
    path = DEMOS_DIR / f"{bid}.html"
    if not path.exists():
        # Try to regenerate from DB
        try:
            import sys
            sys.path.insert(0, str(BASE))
            from database import get_conn
            from demo_generator import generate_demo_html
            conn = get_conn()
            row = conn.execute("""
                SELECT b.*, c.email, c.instagram FROM businesses b
                LEFT JOIN contacts c ON c.business_id = b.id
                WHERE b.id=?
            """, (bid,)).fetchone()
            conn.close()
            if row:
                html = generate_demo_html(dict(row))
                path.write_text(html, encoding="utf-8")
                return HTMLResponse(html)
        except Exception:
            pass
        return HTMLResponse("<h1>Demo not found</h1>", status_code=404)
    return HTMLResponse(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    uvicorn.run("demo_server:app", host="127.0.0.1", port=8766, reload=False)
