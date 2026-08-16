import sqlite3
import os
try:
    db_path = '/data/data/com.termux/files/home/leadflow/leadflow.db'
    if not os.path.exists(db_path):
        db_path = '/data/data/com.termux/files/home/leadflow.db'
    conn = sqlite3.connect(db_path)
    count = conn.execute('SELECT COUNT(1) FROM ig_follow_log').fetchone()[0]
    dms = conn.execute('SELECT COUNT(1) FROM ig_follow_log WHERE action="dm"').fetchone()[0]
    follows = conn.execute('SELECT COUNT(1) FROM ig_follow_log WHERE action="follow"').fetchone()[0]
    unfollows = conn.execute('SELECT COUNT(1) FROM ig_follow_log WHERE action="unfollow"').fetchone()[0]
    msg = f"total_logs:{count} dms:{dms} follows:{follows} unfollows:{unfollows}"
except Exception as e:
    msg = f"error:{str(e)}"
open('/data/data/com.termux/files/home/count_report.txt', 'w').write(msg)
open('/sdcard/count_report.txt', 'w').write(msg)
