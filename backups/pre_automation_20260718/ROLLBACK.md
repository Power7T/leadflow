# Instagram Automation — Backup & Rollback Guide

## Backup Location

```
/Users/chandan/leadflow/backups/pre_automation_20260718/
```

### Files Backed Up

| File | Description |
|------|-------------|
| `instagram_sender.py` | Original ADB controller (DM-only, no follow pairing) |
| `vivo_ig_ui_sender.py` | Original Vivo-specific UI sender |
| `unfollow_ghosts.py` | Original ghost unfollow (broken "Follows you" badge check) |
| `.env` | Original environment variables (INSTAGRAM_USERNAME was blank) |
| `leadflow_backup.db` | Full database snapshot before schema migrations |

### New Files Added (not in backup — delete to rollback)

| File | Purpose |
|------|---------|
| `ig_rate_db.py` | Database layer + migrations (ig_rate_state table, ig_follow_log table, new columns) |
| `ig_rate_limiter.py` | State machine: WARMING_UP → NORMAL → COOLING_DOWN → FROZEN |
| `ig_session_runner.py` | Follow+DM paired session with Message button pre-check |
| `ig_ghost_cleanup.py` | Corrected ghost cleanup using followers list search for "chandan.sol" |

---

## How to Rollback

### Full Rollback (revert everything)

```bash
cd /Users/chandan/leadflow

# 1. Restore original files
cp backups/pre_automation_20260718/instagram_sender.py .
cp backups/pre_automation_20260718/vivo_ig_ui_sender.py .
cp backups/pre_automation_20260718/unfollow_ghosts.py .
cp backups/pre_automation_20260718/.env .

# 2. Restore original database (drops new tables + columns)
cp backups/pre_automation_20260718/leadflow_backup.db leadflow.db

# 3. Remove new files
rm -f ig_rate_db.py ig_rate_limiter.py ig_session_runner.py ig_ghost_cleanup.py
```

### Partial Rollback (keep new files, revert DB only)

```bash
cd /Users/chandan/leadflow
cp backups/pre_automation_20260718/leadflow_backup.db leadflow.db
# Then re-run migrations:
python3 ig_rate_db.py
```

### Rollback single file

```bash
cp backups/pre_automation_20260718/<filename> /Users/chandan/leadflow/
```

---

## What Changed

### Database Schema Changes

**New tables:**
- `ig_rate_state` — Persists rate limiter state machine (state, block_count, cooldown times)
- `ig_follow_log` — Audit trail of every follow/DM/unfollow/skip action

**New columns on `businesses`:**
- `ig_followed_at` (TEXT) — Timestamp when we followed them
- `ig_follows_us_back` (INTEGER) — 1=yes, 0=no, NULL=unchecked
- `ig_followback_checked` (TEXT) — Last time we checked their followers list

### .env Changes
- `INSTAGRAM_USERNAME=chandan.sol` (was blank)

### Behavior Changes

| Before | After |
|--------|-------|
| DM-only, no follow tracking | Follow+DM paired (always follow first, then DM) |
| No Message button check | Pre-checks "Message" button; skips if absent |
| "Follows you" badge check (broken) | Opens followers list, searches for "chandan.sol" |
| No rate limiting state machine | WARMING_UP → NORMAL → COOLING_DOWN → FROZEN |
| Manual daily limit in ig_settings | Autonomous budget based on state + block detection |
| `unfollow_ghosts.py` direct edits | New `ig_ghost_cleanup.py` (old file left untouched) |

---

## Safety Notes

- The **old `unfollow_ghosts.py` is NOT modified** — it still works but uses the broken "Follows you" check
- The **old `instagram_sender.py` is NOT modified** — existing DM flows still work
- New system runs via `ig_session_runner.py` (completely independent entry point)
- All new code checks for action blocks via XML parsing and self-heals pacing
- The Vivo phone is currently in **action block state** — wait for block to expire before testing

---

## Verified Output (post-migration)

```
$ python3 ig_rate_db.py
Rate state: WARMING_UP, block_count=0, warmup_day=1
Today's pairs: 0
Pending ghosts (7+ days): 135
DM candidates (next 5): fabodefitness, comotion_fit, funfitwichita, schuster_athletics, benders_hsv

$ python3 ig_session_runner.py --status
State: WARMING_UP | Budget: 5 pairs/day | Remaining: 5 | Can act: True

$ python3 ig_ghost_cleanup.py --stats
Total pending (7+ days, not unfollowed): 135
├─ Unchecked (never verified): 135
├─ Confirmed ghosts: 0
└─ Confirmed followers: 0
Oldest unresolved follow: 2026-07-04
```

---

## Quick Reference: Running the New System

```bash
cd /Users/chandan/leadflow

# Check status
python3 ig_session_runner.py --status

# Run follow+DM session (dry run first!)
python3 ig_session_runner.py --dry-run
python3 ig_session_runner.py

# Run ghost cleanup (dry run first!)
python3 ig_ghost_cleanup.py --dry-run
python3 ig_ghost_cleanup.py

# Check ghost stats
python3 ig_ghost_cleanup.py --stats

# Check rate limiter state
python3 ig_rate_limiter.py
```

---

*Backup created: 2026-07-18*
*Backup by: Claude Code automation build*
