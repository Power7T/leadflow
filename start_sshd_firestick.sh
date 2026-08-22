# Execute command inside Termux environment to start SSH server
adb -s 192.168.8.246:5555 shell "am broadcast -a com.termux.RUN_COMMAND \
--es com.termux.RUN_COMMAND.PATH '/data/data/com.termux/files/usr/bin/sshd' \
--es com.termux.RUN_COMMAND.WORKDIR '/data/data/com.termux/files/home' \
--ez com.termux.RUN_COMMAND.BACKGROUND true"
