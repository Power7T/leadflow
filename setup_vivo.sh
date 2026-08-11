echo "Creating leadflow directory on Vivo..."
sshpass -p "Qwert123" ssh -p 8022 192.168.0.162 "mkdir -p ~/leadflow && mkdir -p ~/.ssh"

echo "Syncing code repository to Vivo..."
rsync -avz --exclude '.git' --exclude '__pycache__' --exclude 'archived_device_backups' -e "sshpass -p Qwert123 ssh -p 8022" /Users/chandan/leadflow/ 192.168.0.162:~/leadflow/
