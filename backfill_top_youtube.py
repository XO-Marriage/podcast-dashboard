import json
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

def current_week():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday

def main():
    creds = youtube_credentials()
    analytics = build("youtubeAnalytics", "v2", credentials=creds)
    data_svc  = build("youtube", "v3", credentials=creds)
    gc = sheets_client()
    sheet = gc.open_by_key(CONFIG_FILE.read_text().strip())

    week_start, week_end = current_week()
    # Cap end at 3 days ago due to API lag
    week_end = min(week_end, date.today() - timedelta(days=3))
    print(f"Fetching top YouTube video for week of {week_start} (data through {week_end})")

    def top_for_type(content_filter, label):
        resp = analytics.reports().query(
            ids="channel==MINE",
            startDate=week_start.isoformat(),
            endDate=week_end.isoformat(),
            dimensions="video",
            metrics="views,averageViewPercentage",
            filters=f"creatorContentType=={content_filter}",
            sort="-views",
            maxResults=1,
        ).execute()
        rows = resp.get("rows") or []
        if not rows:
            return None
        vid_id = rows[0][0]
        views  = int(rows[0][1])
        items  = data_svc.videos().list(part="snippet", id=vid_id).execute().get("items", [])
        if not items:
            return None
        snip = items[0]["snippet"]
        print(f"Top {label}: {snip['title']} ({views} views)")
        return {
            "platform": f"YouTube {label}",
            "video_id": vid_id,
            "title": snip["title"],
            "thumbnail": snip["thumbnails"].get("high", {}).get("url", ""),
            "views": views,
        }

    top_video = top_for_type("videoOnDemand", "Video")
    top_short = top_for_type("shorts", "Short")

    try:
        ws_top = sheet.worksheet("Top_Performers")
    except gspread.WorksheetNotFound:
        ws_top = sheet.add_worksheet(title="Top_Performers", rows=1000, cols=7)
        ws_top.append_row(["week_start", "platform", "content_id", "title",
                           "thumbnail_url", "metric_value", "metric_name"])

    top_weeks  = ws_top.col_values(1)
    top_platfs = ws_top.col_values(2)

    for entry in [top_video, top_short]:
        if not entry:
            continue
        already = any(
            top_weeks[i] == week_start.isoformat() and top_platfs[i] == entry["platform"]
            for i in range(1, len(top_weeks))
        )
        if already:
            print(f"{entry['platform']} top performer already recorded.")
        else:
            ws_top.append_row([
                week_start.isoformat(), entry["platform"],
                entry["video_id"], entry["title"],
                entry["thumbnail"], entry["views"], "views",
            ])
            print(f"Written {entry['platform']} to Top_Performers.")

if __name__ == "__main__":
    main()
