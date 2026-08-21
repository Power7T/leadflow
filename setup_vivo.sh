#!/bin/bash
# Dynamic Vivo Sync Script

if [ -f "$HOME/.vivo_ip" ]; then
    VIVO_IP=$(cat "$HOME/.vivo_ip" | tr -d '[:space:]' | cut -d':' -f1)
elif [ -f "/Users/chandan/leadflow/.vivo_ip" ]; then
    VIVO_IP=$(cat "/Users/chandan/leadflow/.vivo_ip" | tr -d '[:space:]' | cut -d':' -f1)
else
    VIVO_IP="192.168.8.157"
fi

echo "Connecting & Syncing code to Vivo Phone at $VIVO_IP..."

# Verify SSH port 8022 is open on that IP
sshpass -p "Qwert123" ssh -p 8022 -o StrictHostKeyChecking=no -o ConnectTimeout=10 u0_a156@$VIVO_IP "mkdir -p ~/leadflow && mkdir -p ~/.ssh"

rsync -avz --exclude '.git' --exclude '__pycache__' --exclude 'archived_device_backups' --exclude '*.db' --exclude '*.db-shm' --exclude '*.db-wal' -e "sshpass -p Qwert123 ssh -p 8022 -o StrictHostKeyChecking=no" /Users/chandan/leadflow/ u0_a156@$VIVO_IP:~/leadflow/

echo "Sync complete!"
