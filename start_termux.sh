rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "am start -n com.termux/com.termux.app.TermuxActivity"
sleep 2
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input text 'cd%sleadflow%s&&%spython3%sserver.py'"
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "input keyevent 66"
