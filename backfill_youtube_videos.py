"""Backfill YouTube_Videos sheet with per-video weekly data."""
import json, time, warnings
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
WEEKS_BACK  = 16  # ~4 months

def youtube_creds():
    s = json.loads(SECRET_FILE.read_text())["installed"]
    return Credentials(token=None, refresh_token=TOKEN_FILE.read_text().strip(),
                       client_id=s["client_id"], client_secret=s["client_secret"],
                       token_uri="https://oauth2.googleapis.com/token")

def sheets_client():
    creds = service_account.Credentials.from_service_account_file(
        str(SA_FILE), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return gspread.authorize(creds)

def all_mondays(weeks_back):
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    for _ in range(weeks_back):
        monday -= timedelta(days=7)
        yield monday

def fetch_top_videos(analytics, data_svc, week_start, week_end):
    try:
        resp = analytics.reports().query(
            ids="channel==MINE",
            startDate=week_start.isoformat(),
            endDate=week_end.isoformat(),
            dimensions="video",
            metrics="views,averageViewPercentage",
            sort="-views", maxResults=25,
        ).execute()
    except Exception as e:
        print(f"  API error: {e}")
        return []
    rows = resp.get("rows") or []
    if not rows:
        return []
    ids = [r[0] for r in rows]
    try:
        vids = data_svc.videos().list(part="snippet", id=",".join(ids)).execute()
        snippets = {v["id"]: v["snippet"] for v in vids.get("items", [])}
    except Exception:
        snippets = {}
    result = []
    for row in rows:
        vid_id = row[0]
        s = snippets.get(vid_id, {})
        result.append({
            "week_start":   week_start.isoformat(),
            "video_id":     vid_id,
            "title":        s.get("title", vid_id),
            "thumbnail":    s.get("thumbnails", {}).get("high", {}).get("url", ""),
            "published_at": s.get("publishedAt", "")[:10],
            "views":        int(row[1]),
            "avg_view_pct": round(float(row[2]), 2),
        })
    return result

def main():
    creds     = youtube_creds()
    analytics = build("youtubeAnalytics", "v2", credentials=creds)
    data_svc  = build("youtube", "v3", credentials=creds)
    gc        = sheets_client()
    sheet     = gc.open_by_key(CONFIG_FILE.read_text().strip())
    cutoff    = date.today() - timedelta(days=3)

    try:
        ws = sheet.worksheet("YouTube_Videos")
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title="YouTube_Videos", rows=10000, cols=7)
        ws.append_row(["week_start","video_id","title","thumbnail","published_at","views","avg_view_pct"])

    existing = set(ws.col_values(1)[1:])
    print(f"Existing week entries: {len(set(existing))}")

    mondays = list(all_mondays(WEEKS_BACK))
    print(f"Weeks to process: {len(mondays)}")

    new_rows = []
    for i, monday in enumerate(mondays):
        sunday = min(monday + timedelta(days=6), cutoff)
        if sunday < monday:
            continue
        if monday.isoformat() in existing:
            print(f"  [{i+1}/{len(mondays)}] {monday} — already exists, skipping")
            continue
        print(f"  [{i+1}/{len(mondays)}] {monday} → {sunday} ...", end=" ", flush=True)
        videos = fetch_top_videos(analytics, data_svc, monday, sunday)
        new_rows.extend([[v["week_start"],v["video_id"],v["title"],v["thumbnail"],
                          v["published_at"],v["views"],v["avg_view_pct"]] for v in videos])
        print(f"{len(videos)} videos")
        time.sleep(0.5)

    if new_rows:
        print(f"\nWriting {len(new_rows)} rows...")
        for i in range(0, len(new_rows), 100):
            ws.append_rows(new_rows[i:i+100], value_input_option="RAW")
            time.sleep(0.5)
        print("Done.")
    else:
        print("Nothing new to write.")

if __name__ == "__main__":
    main()
