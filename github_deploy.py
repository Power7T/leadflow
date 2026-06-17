import os
import base64
import json
import urllib.request

GITHUB_TOKEN = os.getenv('GITHUB_TOKEN', '')
GITHUB_REPO = os.getenv('GITHUB_DEMO_REPO', 'power7t/leadflow-demos')
GITHUB_BRANCH = 'main'

def push_demo_to_github(filename: str, html_content: str) -> str:
    """Push a demo HTML file to GitHub Pages. Returns public URL or empty string."""
    if not GITHUB_TOKEN:
        print("[github_deploy] No GITHUB_TOKEN set. Skipping GitHub deploy.")
        return ''
    try:
        # GitHub Contents API
        api_url = f'https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}'
        content_b64 = base64.b64encode(html_content.encode('utf-8')).decode('utf-8')
        
        # Check if file exists (to get sha for update)
        sha = None
        try:
            req = urllib.request.Request(
                api_url, 
                headers={
                    'Authorization': f'token {GITHUB_TOKEN}', 
                    'Accept': 'application/vnd.github.v3+json',
                    'User-Agent': 'LeadFlow-Deploy-Agent'
                }
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                existing = json.loads(r.read().decode('utf-8'))
                sha = existing.get('sha')
        except Exception as e:
            # File probably doesn't exist yet, which is fine
            pass
        
        payload = {
            'message': f'Deploy demo: {filename}', 
            'content': content_b64, 
            'branch': GITHUB_BRANCH
        }
        if sha:
            payload['sha'] = sha
        
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            api_url, 
            data=data, 
            method='PUT',
            headers={
                'Authorization': f'token {GITHUB_TOKEN}', 
                'Content-Type': 'application/json', 
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'LeadFlow-Deploy-Agent'
            }
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read().decode('utf-8'))
        
        repo_name = GITHUB_REPO.split('/')[-1]
        owner = GITHUB_REPO.split('/')[0]
        public_url = f'https://{owner}.github.io/{repo_name}/{filename}'
        print(f"[github_deploy] Successfully deployed {filename} to GitHub: {public_url}")
        return public_url
    except Exception as e:
        print(f'[github_deploy] Failed to push to GitHub: {e}')
        return ''
