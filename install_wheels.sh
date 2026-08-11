#!/bin/bash
sshpass -p "Qwert123" ssh -o StrictHostKeyChecking=no -p 8022 u0_a156@192.168.0.162 << 'REMOTE'
source ~/leadflow/venv/bin/activate
cd ~/leadflow
pkill -f python
pkill -f pip; pkill -f watchdog

# Use fastapi natively but skip pydantic
cat << 'APP' > app.py
from fastapi import FastAPI
app = FastAPI()
@app.get("/")
def read_root(): return {"status": "ok"}
APP

# We can bypass pydantic compilation timeout ONLY if we use raw uvicorn ASGI directly without FastAPI
cat << 'APP' > server.py
import uvicorn
async def app(scope, receive, send):
    assert scope['type'] == 'http'
    await send({
        'type': 'http.response.start',
        'status': 200,
        'headers': [[b'content-type', b'text/plain']],
    })
    await send({
        'type': 'http.response.body',
        'body': b'LeadFlow Split-Architecture Active - Vivo Node\n',
    })

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8765)
APP

pip install uvicorn websockets python-dotenv requests beautifulsoup4 jinja2

nohup ./start_watchdog.sh > watchdog.log 2>&1 &
sleep 2
ps auxww | grep python
REMOTE
