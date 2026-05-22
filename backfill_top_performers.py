import json
import time
import warnings
from datetime import date, timedelta
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.oauth2 import service_account
import gspread

warnings.filterwarnings("ignore")

SA_FILE     = Path(__file__).parent / "service_account.json"
SECRET_FILE = Path(__file__).parent / "client_secret.json"
TOKEN_FILE  = Path(__file__).parent / ".refresh_token"
CONFIG_FILE = Path(__file__).parent / "config.txt"

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

def week_range(week_start):
    return week_start, week_start + timedelta(days=6)

def all_mondays(from_date, to_date):
    # Start on the Monday of from_date's week
    monday = from_date - timedelta(days=from_date.weekday())
    while monday <= to_date:
        yield monday
        monday += timedelta(days=7)

def top_for_type(analytics, data_svc, start, end, content_filter):
    try:
        resp = analytics.reports().query(
            ids="channel==MINE",
            startDate=start.isoformat(),
            endDate=end.isoformat(),
            dimensions="video",
            metrics="views",
            filters=f"creatorContentType=={content_filter}",
            sort="-views",
            maxResults=1,
        ).execute()
    except Exception:
        return None

    rows = resp.get("rows") or []
    if not rows or int(rows[0][1]) == 0:
        return None

    vid_id = rows[0][0]
    views  = int(rows[0][1])

    try:
        items = data_svc.videos().list(part="snippet", id=vid_id).execute().get("items", [])
    except Exception:
        return None

    if not items:
        return None

    snip = items[0]["snippet"]
    return {
        "video_id":  vid_id,
        "title":     snip.get("title", vid_id),
        "thumbnail": snip.get("thumbnails", {}).get("high", {}).get("url", ""),
        "views":     views,
    }

def main():
    creds    = youtube_credentials()
    analytics = build("youtubeAnalytics", "v2", credentials=creds)
    data_svc  = build("youtube", "v3", credentials=creds)
    gc        = sheets_client()
    sheet     = gc.open_by_key(CONFIG_FILE.read_text().strip())

    # Load existing entries to avoid duplicates
    try:
        ws_top = sheet.worksheet("Top_Performers")
    except gspread.WorksheetNotFound:
        ws_top = sheet.add_worksheet(title="Top_Performers", rows=5000, cols=7)
        ws_top.append_row(["week_start", "platform", "content_id", "title",
                           "thumbnail_url", "metric_value", "metric_name"])

    existing_rows = ws_top.get_all_values()[1:]  # skip header
    already_done  = {(r[0], r[1]) for r in existing_rows}
    print(f"Existing entries: {len(already_done)}")

    # Date range: channel start → last fully processed week
    channel_start = date(2020, 7, 28)
    last_full_end = date.today() - timedelta(days=date.today().weekday() + 1)  # last Sunday
    cutoff        = date.today() - timedelta(days=3)  # API lag
    last_full_end = min(last_full_end, cutoff)

    mondays = list(all_mondays(channel_start, last_full_end))
    print(f"Weeks to process: {len(mondays)} ({mondays[0]} → {mondays[-1]})")

    new_rows = []
    for i, monday in enumerate(mondays):
        _, sunday = week_range(monday)
        sunday = min(sunday, cutoff)
        if sunday < monday:
            continue

        week_str = monday.isoformat()
        needs_video = (week_str, "YouTube Video") not in already_done
        needs_short = (week_str, "YouTube Short") not in already_done

        if not needs_video and not needs_short:
            continue

        if i % 20 == 0:
            print(f"  Processing week {i+1}/{len(mondays)}: {week_str}")

        if needs_video:
            top = top_for_type(analytics, data_svc, monday, sunday, "videoOnDemand")
            if top:
                new_rows.append([week_str, "YouTube Video", top["video_id"],
                                  top["title"], top["thumbnail"], top["views"], "views"])
            time.sleep(0.3)

        if needs_short:
            top = top_for_type(analytics, data_svc, monday, sunday, "shorts")
            if top:
                new_rows.append([week_str, "YouTube Short", top["video_id"],
                                  top["title"], top["thumbnail"], top["views"], "views"])
            time.sleep(0.3)

    if new_rows:
        # Sort by week_start before writing
        new_rows.sort(key=lambda r: r[0])
        print(f"\nWriting {len(new_rows)} rows to Top_Performers...")
        # Write in batches of 50 to avoid timeout
        for i in range(0, len(new_rows), 50):
            ws_top.append_rows(new_rows[i:i+50], value_input_option="RAW")
            time.sleep(1)
        print("Done.")
    else:
        print("Nothing new to write.")

if __name__ == "__main__":
    main()
