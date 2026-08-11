#!/bin/bash
sshpass -p "Qwert123" ssh -o StrictHostKeyChecking=no -p 8022 u0_a156@192.168.0.162 << 'REMOTE'
source ~/leadflow/venv/bin/activate
pip install setuptools_rust cryptography
pip install jiter
REMOTE
