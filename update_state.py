import re

with open("state.md", "r") as f:
    text = f.read()

# Update pending items for Firestick
text = text.replace("1. **Restart server.py** on Firestick: `pkill -f server.py` in Termux (watchdog auto-restarts)", 
                    "1. ~~**Restart server.py** on Firestick: `pkill -f server.py` in Termux (watchdog auto-restarts)~~ (DONE)")

text = text.replace("2. **Run Firestick DB fix**: `python3 /data/data/com.termux/files/home/leadflow/firestick_db_fix.py`",
                    "2. ~~**Run Firestick DB fix**: `python3 /data/data/com.termux/files/home/leadflow/firestick_db_fix.py`~~ (DONE)")

with open("state.md", "w") as f:
    f.write(text)
