# ESPN College Football Data Pipeline

Scripts for extracting college football team, roster, and logo data from ESPN’s CORE API.

Builds clean, structured datasets suitable for sports analytics, modeling, and database construction.

---

## Scripts

### espn_cfb_rosters.py

Downloads team and player roster data for a given season.

Example:

```bash
python espn_cfb_rosters.py --season 2025 --out ./out
