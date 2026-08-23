#!/usr/bin/env bash
set -euo pipefail

# Trigger high-speed DB sync from Vivo to Mac after IG DM session
VIVO_IP=$(cat /Users/chandan/.vivo_ip 2>/dev/null || echo "192.168.8.157:5555")
VIVO_IP_ONLY=$(echo "$VIVO_IP" | cut -d':' -f1)

echo "[$(date)] Pulling live DB snapshot from Vivo ($VIVO_IP_ONLY)..."
sshpass -p Qwert123 rsync -avz -e "ssh -p 8022 -o StrictHostKeyChecking=no -o ConnectTimeout=5" \
  u0_a156@${VIVO_IP_ONLY}:~/leadflow/leadflow.db /Users/chandan/leadflow/leadflow.db.vivo_snap || true

if [ -f "/Users/chandan/leadflow/leadflow.db.vivo_snap" ]; then
    echo "[$(date)] Merging sent messages into Mac DB..."
    python3 -c "
import sqlite3
mac_conn = sqlite3.connect('/Users/chandan/leadflow/leadflow.db', timeout=30.0)
mac_conn.execute('PRAGMA journal_mode=WAL;')
mac_conn.execute('ATTACH DATABASE \'/Users/chandan/leadflow/leadflow.db.vivo_snap\' AS vivo;')
mac_conn.execute('''
    UPDATE outreach
    SET status = v.status,
        sent_at = v.sent_at,
        message_id = v.message_id
    FROM vivo.outreach v
    WHERE outreach.id = v.id AND v.status = 'sent' AND outreach.status != 'sent';
''')
mac_conn.commit()
mac_conn.close()
"
    echo "[$(date)] DB merge completed successfully."
fi
