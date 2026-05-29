import csv
import re
import os
import sys
import json
from pathlib import Path
from google.oauth2 import service_account
import gspread

UPLOADS_DIR = Path(__file__).parent / "uploads"
SA_FILE = Path(__file__).parent / "service_account.json"

def get_sheets_client():
    if SA_FILE.exists():
        creds = service_account.Credentials.from_service_account_file(
            str(SA_FILE), scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
    else:
        sa = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT"])
        creds = service_account.Credentials.from_service_account_info(
            sa, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
    return gspread.authorize(creds)

def get_sheet_id():
    config_file = Path(__file__).parent / "config.txt"
    if config_file.exists():
        return config_file.read_text().strip()
    return os.environ.get("GOOGLE_SHEET_ID", "")

def parse_dates(filename):
    match = re.search(r'(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})', filename)
    return (match.group(1), match.group(2)) if match else (None, None)

def safe_int(val):
    if val in ('N/A', '', None):
        return 0
    try:
        return int(str(val).replace(',', ''))
    except Exception:
        return 0

def get_or_create_sheet(spreadsheet, name, headers):
    try:
        ws = spreadsheet.worksheet(name)
        if not ws.row_values(1):
            ws.append_row(headers)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=name, rows=10000, cols=len(headers))
        ws.append_row(headers)
    return ws

def main():
    UPLOADS_DIR.mkdir(exist_ok=True)
    csvs = sorted(UPLOADS_DIR.glob("*.csv"), key=os.path.getmtime, reverse=True)
    if not csvs:
        print(f"No CSV found in {UPLOADS_DIR}")
        print("Export the episode report from Megaphone and drop it in that folder.")
        sys.exit(1)

    csv_path = csvs[0]
    print(f"Processing: {csv_path.name}")

    week_start, week_end = parse_dates(csv_path.name)
    if not week_start:
        week_start = input("Enter week start date (YYYY-MM-DD): ").strip()
        week_end = input("Enter week end date (YYYY-MM-DD): ").strip()
    print(f"Period: {week_start} to {week_end}")

    episodes = []
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            episodes.append({
                "episode_title": row.get("EPISODE", "").strip(),
                "podcast_title": row.get("PODCAST", "").strip(),
                "downloads":     safe_int(row.get("DOWNLOADS")),
                "published_at":  row.get("PUBLISHED", "").strip(),
                "first_24h":     safe_int(row.get("FIRST 24 HOURS")),
                "first_7d":      safe_int(row.get("FIRST 7 DAYS")),
                "to_date":       safe_int(row.get("TO DATE")),
            })
    print(f"Found {len(episodes)} episodes")

    sheet_id = get_sheet_id()
    if not sheet_id:
        print("Sheet ID not found. Add it to config.txt or set GOOGLE_SHEET_ID env var.")
        sys.exit(1)

    gc = get_sheets_client()
    spreadsheet = gc.open_by_key(sheet_id)

    # ── Megaphone_Episodes ────────────────────────────────────────────────────
    ws_meg = get_or_create_sheet(spreadsheet, "Megaphone_Episodes", [
        "week_start", "week_end", "episode_title", "podcast_title",
        "downloads", "published_at", "first_24h", "first_7d", "to_date",
    ])

    if week_start in ws_meg.col_values(1):
        print(f"Data for {week_start} already in sheet — skipping episode rows.")
    else:
        rows = [
            [week_start, week_end,
             ep["episode_title"], ep["podcast_title"],
             ep["downloads"], ep["published_at"],
             ep["first_24h"], ep["first_7d"], ep["to_date"]]
            for ep in episodes
        ]
        ws_meg.append_rows(rows, value_input_option="RAW")
        print(f"Written {len(rows)} episode rows")

    # ── Top_Performers ────────────────────────────────────────────────────────
    ws_top = get_or_create_sheet(spreadsheet, "Top_Performers", [
        "week_start", "platform", "content_id", "title",
        "thumbnail_url", "metric_value", "metric_name",
    ])

    top_weeks  = ws_top.col_values(1)
    top_platfs = ws_top.col_values(2)
    already = any(
        top_weeks[i] == week_start and top_platfs[i] == "Megaphone"
        for i in range(1, len(top_weeks))
    )

    if already:
        print(f"Top performer for Megaphone/{week_start} already recorded.")
    else:
        with_downloads = [ep for ep in episodes if ep["downloads"] > 0]
        if with_downloads:
            top = max(with_downloads, key=lambda x: x["downloads"])
            ws_top.append_row([
                week_start, "Megaphone", "",
                top["episode_title"], "",
                top["downloads"], "downloads",
            ])
            print(f"Top episode: {top['episode_title']} ({top['downloads']} downloads)")

    print("Done.")

if __name__ == "__main__":
    main()
