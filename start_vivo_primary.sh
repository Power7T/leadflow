#!/bin/bash
# Start LeadFlow on Vivo phone as PRIMARY DM sender.
# Run this on Mac to push code + start server on Vivo via SSH.
set -e

VIVO_HOST="192.168.8.157"
VIVO_PORT="8022"
VIVO_USER="u0_a156"
VIVO_PASS="Qwert123"
VIVO_DIR="~/leadflow"

echo "[start_vivo_primary] Syncing code to Vivo..."
rsync -avz --exclude '.git' --exclude '__pycache__' --exclude 'archived_device_backups' --exclude 'leadflow.db*' --exclude '*.log*' --exclude 'node_modules*' --exclude 'venv*' --exclude '.venv*' --exclude '.git*' --exclude 'demos*' --exclude 'leadflow-demos*' \
  -e "sshpass -p $VIVO_PASS ssh -p $VIVO_PORT -o StrictHostKeyChecking=no" \
  /Users/chandan/leadflow/ ${VIVO_USER}@${VIVO_HOST}:${VIVO_DIR}/

echo "[start_vivo_primary] Starting LeadFlow server on Vivo as PRIMARY..."
sshpass -p "$VIVO_PASS" ssh -o StrictHostKeyChecking=no -p "$VIVO_PORT" "${VIVO_USER}@${VIVO_HOST}" << 'REMOTE'
source ~/leadflow/venv/bin/activate 2>/dev/null || true
cd ~/leadflow

# Set device role to primary so DM sender uses localhost ADB
export LEADFLOW_DEVICE_ROLE=primary

# Ensure .env has LEADFLOW_DEVICE_ROLE=primary (persist across restarts)
if grep -q "LEADFLOW_DEVICE_ROLE" .env 2>/dev/null; then
  sed -i "s/LEADFLOW_DEVICE_ROLE=.*/LEADFLOW_DEVICE_ROLE='primary'/" .env
else
  echo "LEADFLOW_DEVICE_ROLE='primary'" >> .env
fi

# Kill any existing server
pkill -f "python.*server.py" 2>/dev/null || true
sleep 1

# Start server in background using venv python (bare python may not be in PATH in non-login SSH)
nohup ~/leadflow/venv/bin/python server.py > server_run.log 2>&1 &
sleep 2
echo "Server PID: $(pgrep -f 'python.*server.py' | head -1)"
ps auxww | grep python | grep -v grep
REMOTE

echo "[start_vivo_primary] Done. Vivo is now running LeadFlow as PRIMARY DM sender."
