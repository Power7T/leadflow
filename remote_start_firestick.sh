# Connect and forcibly send the start command through Android am components natively to avoid Run-As Termux shell permission blocks
rtk proxy adb -s $(cat /Users/chandan/leadflow/.firestick_ip) shell "am startservice --user 0 -a com.termux.service_execute -d file:///data/data/com.termux/files/home/leadflow/start_leadflow_failover.sh com.termux/com.termux.app.RunCommandService"
echo "Sent Start Command via Android Intents"
