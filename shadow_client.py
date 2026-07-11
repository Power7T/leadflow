import os
import time
from datetime import datetime, timedelta
import sqlite3
from pathlib import Path

# Fix relative imports when run standalone
try:
    from database import get_conn
    from sender import send_email
except ImportError:
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from database import get_conn
    from sender import send_email

def send_shadow_inquiries(limit: int = 5):
    """
    Finds leads that are 'untested', have an email, and sends a shadow inquiry.
    """
    print("Shadow email checks temporarily disabled to prevent deliverability issues")
    return

    conn = get_conn()
    try:
        # Find leads with untested shadow_status
        cursor = conn.execute("""
            SELECT b.id, b.name, c.email
            FROM businesses b
            JOIN contacts c ON b.id = c.business_id
            WHERE b.shadow_status = 'untested'
              AND c.email IS NOT NULL 
              AND c.email != ''
              AND b.status = 'new'
            LIMIT ?
        """, (limit,))
        
        leads = cursor.fetchall()
        for lead in leads:
            bid = lead["id"]
            email_addr = lead["email"]
            name = lead["name"]
            
            subject = "Quick question"
            body = (
                f"<div style='font-family: Arial, sans-serif; font-size: 14px;'>"
                f"Hi team,<br><br>"
                f"Just checking if you are taking on new clients and projects for next week?<br><br>"
                f"Thanks,<br>Chandan"
                f"</div>"
            )
            
            print(f"[ShadowClient] Sending inquiry to {name} ({email_addr})")
            
            try:
                # Send the email
                success = send_email(
                    to_email=email_addr,
                    subject=subject,
                    body=body,
                    business_id=bid
                )
                
                if success:
                    # Mark as testing
                    now_str = datetime.utcnow().isoformat()
                    conn.execute("""
                        UPDATE businesses 
                        SET shadow_status = 'testing', shadow_tested_at = ? 
                        WHERE id = ?
                    """, (now_str, bid))
                    
                    # Insert into outreach as a shadow event so we can track replies
                    conn.execute("""
                        INSERT INTO outreach (business_id, channel, final_message, status, sent_at)
                        VALUES (?, 'shadow_email', ?, 'sent', ?)
                    """, (bid, body, now_str))
                    
                    conn.commit()
                    print(f"  -> Success. Status set to 'testing'.")
                else:
                    # Suppressed or bounced
                    conn.execute("""
                        UPDATE businesses 
                        SET shadow_status = 'failed_form', shadow_issue = 'Direct email bounced or suppressed.' 
                        WHERE id = ?
                    """, (bid,))
                    conn.commit()
                    print(f"  -> Failed (suppressed/bounced).")
                    
            except Exception as e:
                print(f"  -> Error sending email: {e}")
                
    finally:
        conn.close()


def check_shadow_timeouts(timeout_hours: int = 24):
    """
    Checks leads in 'testing' state. If time elapsed > timeout_hours,
    or if they replied but it took > 24 hours, marks them as 'slow_reply'.
    If they replied fast, marks as 'fast_reply'.
    """
    conn = get_conn()
    try:
        cursor = conn.execute("""
            SELECT b.id, b.name, b.shadow_tested_at, 
                   (SELECT replied FROM outreach o WHERE o.business_id = b.id AND o.channel = 'shadow_email' ORDER BY id DESC LIMIT 1) as has_replied
            FROM businesses b
            WHERE b.shadow_status = 'testing'
        """)
        
        leads = cursor.fetchall()
        now = datetime.utcnow()
        
        for lead in leads:
            bid = lead["id"]
            name = lead["name"]
            tested_at_str = lead["shadow_tested_at"]
            has_replied = lead["has_replied"]
            
            if not tested_at_str:
                continue
                
            tested_at = datetime.fromisoformat(tested_at_str)
            elapsed_hours = (now - tested_at).total_seconds() / 3600
            
            if has_replied == 1:
                # They replied!
                if elapsed_hours <= timeout_hours:
                    # Fast reply
                    conn.execute("UPDATE businesses SET shadow_status = 'fast_reply' WHERE id = ?", (bid,))
                    print(f"[ShadowClient] {name} replied FAST ({elapsed_hours:.1f} hours).")
                else:
                    # Slow reply
                    issue = f"Response took {elapsed_hours:.1f} hours to arrive."
                    conn.execute("UPDATE businesses SET shadow_status = 'slow_reply', shadow_issue = ? WHERE id = ?", (issue, bid))
                    print(f"[ShadowClient] {name} replied SLOW ({elapsed_hours:.1f} hours).")
                conn.commit()
            
            elif elapsed_hours > timeout_hours:
                # Timed out, no reply
                issue = f"Tried reaching out; {int(elapsed_hours)} hours passed with no response."
                conn.execute("UPDATE businesses SET shadow_status = 'slow_reply', shadow_issue = ? WHERE id = ?", (issue, bid))
                conn.commit()
                print(f"[ShadowClient] {name} TIMED OUT ({elapsed_hours:.1f} hours). Marked slow_reply.")
                
    finally:
        conn.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LeadFlow Shadow Client")
    parser.add_argument("--send", action="store_true", help="Send new shadow inquiries")
    parser.add_argument("--check", action="store_true", help="Check timeouts for in-flight inquiries")
    parser.add_argument("--batch", type=int, default=5, help="Batch size for sending")
    
    args = parser.parse_args()
    
    if args.send:
        send_shadow_inquiries(args.batch)
    if args.check:
        check_shadow_timeouts(24)
    
    if not args.send and not args.check:
        print("Run with --send or --check")

