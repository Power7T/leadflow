# Firestick (Device 1: Gateway / Old Primary)
The Firestick originally acted as the primary bot and database host, suffering from OOMs. After the split, it acts purely as a gateway.

## Key Files:
- `termux_cf_setup.sh`, `start_watchdog.sh`
- `stealdeals_userbot.py` (simulated via telegram_farm backup if available)
- `check_fs.py`, `device_health_firestick.py`
- `cloudflared` (Binary references)
