rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input keyevent 4" # Back button to clear focus
sleep 1
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input text 'tmux%snew-session%s-d%s-s%sleadflow_primary'"
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input keyevent 66"
sleep 1
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input text 'tmux%ssend-keys%s-t%sleadflow_primary%s\"cd ~/leadflow && python3 server.py\"%sC-m'"
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input keyevent 66"
