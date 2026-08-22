#!/bin/bash
sshpass -p "Qwert123" ssh -o StrictHostKeyChecking=no -p 8022 u0_a156@192.168.8.157 << 'REMOTE'
source ~/leadflow/venv/bin/activate
cd ~/leadflow
nohup python server.py > server_run.log 2>&1 &
sleep 2
ps auxww | grep python
REMOTE
