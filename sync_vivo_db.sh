#!/usr/bin/env bash
# Trigger high-speed DB sync from Vivo to Mac after IG DM session
VIVO_IP=$(cat /Users/chandan/.vivo_ip 2>/dev/null || echo "192.168.8.157:5555")
VIVO_IP_ONLY=$(echo "$VIVO_IP" | cut -d':' -f1)

echo "[$(date)] Pulling live DB snapshot from Vivo ($VIVO_IP_ONLY)..."
rsync -avz -e "sshpass -p Qwert123 ssh -p 8022 -o StrictHostKeyChecking=no" \
  u0_a156@${VIVO_IP_ONLY}:~/leadflow/leadflow.db /Users/chandan/leadflow/leadflow.db.vivo_snap

if [ -f "/Users/chandan/leadflow/leadflow.db.vivo_snap" ]; then
    echo "[$(date)] Successfully pulled Vivo DB snapshot."
fi
