import json
import warnings
import time
from datetime import date, timedelta
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.oauth2 import service_account
import gspread

warnings.filterwarnings("ignore")

SA_FILE = Path(__file__).parent / "service_account.json"
SECRET_FILE = Path(__file__).parent / "client_secret.json"
TOKEN_FILE = Path(__file__).parent / ".refresh_token"
CONFIG_FILE = Path(__file__).parent / "config.txt"
CHUNK_DAYS = 180  # pull 180 days at a time to stay well within API limits

def youtube_credentials():
    secrets = json.loads(SECRET_FILE.read_text())["installed"]
    return Credentials(
        token=None,
        refresh_token=TOKEN_FILE.read_text().strip(),
        client_id=secrets["client_id"],
        client_secret=secrets["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
    )

def sheets_client():
    creds = service_account.Credentials.from_service_account_file(
        str(SA_FILE), scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)

def get_channel_start_date(creds):
    yt = build("youtube", "v3", credentials=creds)
    resp = yt.channels().list(part="snippet", mine=True).execute()
    published = resp["items"][0]["snippet"]["publishedAt"][:10]
    print(f"Channel created: {published}")
    return date.fromisoformat(published)

def fetch_chunk(analytics, start, end):
    resp = analytics.reports().query(
        ids="channel==MINE",
        startDate=start.isoformat(),
        endDate=end.isoformat(),
        dimensions="day",
        metrics="views,averageViewPercentage,subscribersGained,shares",
        sort="day",
    ).execute()
    return resp.get("rows") or []

def main():
    creds = youtube_credentials()
    analytics = build("youtubeAnalytics", "v2", credentials=creds)
    gc = sheets_client()
    sheet = gc.open_by_key(CONFIG_FILE.read_text().strip())

    # Get or create sheet
    try:
        ws = sheet.worksheet("YouTube_Metrics")
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title="YouTube_Metrics", rows=10000, cols=6)
        ws.append_row(["date", "views", "avg_view_pct", "subscribers_gained", "shares"])

    # Find dates already in the sheet
    existing_dates = set(ws.col_values(1)[1:])  # skip header
    print(f"Dates already in sheet: {len(existing_dates)}")

    start_date = get_channel_start_date(creds)
    end_date = date.today() - timedelta(days=3)  # 3-day lag

    all_rows = []
    chunk_start = start_date

    while chunk_start <= end_date:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS - 1), end_date)
        print(f"Fetching {chunk_start} → {chunk_end} ...", end=" ", flush=True)

        rows = fetch_chunk(analytics, chunk_start, chunk_end)
        new_rows = [r for r in rows if r[0] not in existing_dates]
        all_rows.extend(new_rows)
        print(f"{len(rows)} days returned, {len(new_rows)} new")

        chunk_start = chunk_end + timedelta(days=1)
        time.sleep(0.5)  # be polite to the API

    if all_rows:
        formatted = [
            [r[0], int(r[1]), round(float(r[2]), 2), int(r[3]), int(r[4])]
            for r in all_rows
        ]
        # Sort by date before writing
        formatted.sort(key=lambda x: x[0])
        ws.append_rows(formatted, value_input_option="RAW")
        print(f"\nWritten {len(formatted)} rows to YouTube_Metrics")
    else:
        print("\nNo new rows to write — sheet is already up to date")

    print("Backfill complete.")

if __name__ == "__main__":
    main()
