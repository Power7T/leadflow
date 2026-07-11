import sqlite3

def clean():
    conn = sqlite3.connect("/Users/chandan/leadflow/leadflow.db")
    cursor = conn.cursor()
    
    # 1. Fetch all instagram outreach entries
    cursor.execute("SELECT id, business_id, status, draft FROM outreach WHERE channel='instagram'")
    rows = cursor.fetchall()
    
    # Group by business_id
    by_business = {}
    for row in rows:
        r_id, b_id, status, draft = row
        if b_id not in by_business:
            by_business[b_id] = []
        by_business[b_id].append({
            "id": r_id,
            "status": status,
            "draft": draft or ""
        })
        
    to_delete = []
    
    # Deduplicate each business_id
    for b_id, entries in by_business.items():
        if len(entries) <= 1:
            continue
            
        # Separate prompt-leaked ones from clean ones
        sent_entries = [e for e in entries if e["status"] == "sent"]
        if sent_entries:
            # keep the sent ones, delete the rest
            for e in entries:
                if e not in sent_entries:
                    to_delete.append(e["id"])
            continue

        clean_entries = []
        leaked_entries = []
        
        for entry in entries:
            draft = entry["draft"]
            if "The user wants" in draft or "Key constraints" in draft or "Business details:" in draft:
                leaked_entries.append(entry)
            else:
                clean_entries.append(entry)
                
        # Case 1: We have both clean and leaked ones
        if clean_entries and leaked_entries:
            # Keep the best clean one, delete the rest
            clean_entries.sort(key=lambda x: len(x["draft"]), reverse=True)
            for entry in clean_entries[1:]:
                to_delete.append(entry["id"])
            for entry in leaked_entries:
                to_delete.append(entry["id"])
                
        # Case 2: All are leaked or all are clean
        else:
            # Sort by draft length, keep the longest one
            entries.sort(key=lambda x: len(x["draft"]), reverse=True)
            for entry in entries[1:]:
                to_delete.append(entry["id"])
                
    # 2. Perform deletion
    if to_delete:
        placeholders = ",".join("?" for _ in to_delete)
        cursor.execute(f"DELETE FROM outreach WHERE id IN ({placeholders})", to_delete)
        conn.commit()
        print(f"Cleaned up {len(to_delete)} duplicate/prompt-leaked outreach entries.")
    else:
        print("No duplicates found to clean.")
        
    conn.close()

if __name__ == "__main__":
    clean()
