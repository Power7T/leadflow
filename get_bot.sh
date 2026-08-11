#!/system/bin/sh
cat /data/data/com.termux/files/home/bot/start_bot.sh
echo "--- bot_integration.py ---"
cat /data/data/com.termux/files/home/bot/bot_integration.py 2>/dev/null || echo "NOT FOUND"
