# 1. Force stop Termux to clear zombie RAM via pure ADB shell
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "am force-stop com.termux"
sleep 4

# 2. Wake Termux
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "am start -n com.termux/com.termux.app.TermuxActivity"
sleep 6

# 3. Use ADB input text to directly emulate physical keypresses for Android's sandbox
# Start Stealdeals Bot
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input text 'cd'" && rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input keyevent 66"
sleep 1
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input text 'cd%sbot'" && rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input keyevent 66"
sleep 1
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input text 'bash%sstart_bot.sh'" && rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input keyevent 66"
sleep 5

# Start Leadflow
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input text 'cd'" && rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input keyevent 66"
sleep 1
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input text 'cd%sleadflow'" && rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input keyevent 66"
sleep 1
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input text 'bash%sstart_leadflow_failover.sh'" && rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input keyevent 66"
sleep 5

# Check status natively
echo "Checking if tmux sessions deployed properly:"
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "run-as com.termux /data/data/com.termux/files/usr/bin/tmux ls"
