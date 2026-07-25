echo "Typing Telegram bot start commands..."
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input text 'cd'"
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input keyevent 66"
sleep 1
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input text 'cd%sbot'"
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input keyevent 66"
sleep 1
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input text 'bash%sstart_bot.sh'"
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input keyevent 66"
sleep 5

echo "Typing Leadflow start commands..."
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input text 'cd'"
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input keyevent 66"
sleep 1
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input text 'cd%sleadflow'"
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input keyevent 66"
sleep 1
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input text 'bash%sstart_leadflow_failover.sh'"
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input keyevent 66"
sleep 4

echo "Checking the active tmux sessions directly from Termux bin..."
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "run-as com.termux sh -c '/data/data/com.termux/files/usr/bin/tmux ls'"
