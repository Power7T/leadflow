#!/bin/bash
# 1. Start SSH in Termux on the Firestick
FIRESTICK_IP=$(cat ~/.firestick_ip)
adb -s $FIRESTICK_IP shell "run-as com.termux /data/data/com.termux/files/usr/bin/bash -c \"apt update && apt install openssh -y && ssh-keygen -A && sshd\""

# 2. Add your Mac key for passwordless entry
MAC_KEY=$(cat ~/.ssh/id_rsa.pub 2>/dev/null || cat ~/.ssh/id_ed25519.pub)
if [ -z "$MAC_KEY" ]; then
    ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
    MAC_KEY=$(cat ~/.ssh/id_ed25519.pub)
fi
adb -s $FIRESTICK_IP shell "run-as com.termux /data/data/com.termux/files/usr/bin/bash -c \"mkdir -p ~/.ssh && echo '$MAC_KEY' > ~/.ssh/authorized_keys\""
adb -s $FIRESTICK_IP shell "run-as com.termux /data/data/com.termux/files/usr/bin/bash -c \"chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys\""
