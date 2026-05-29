import os
import json
import requests
from datetime import date, timedelta
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
import gspread

# ── credentials ───────────────────────────────────────────────────────────────

def youtube_credentials():
    secrets = json.loads(os.environ["YOUTUBE_CLIENT_SECRETS"])["installed"]
    return Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        client_id=secrets["client_id"],
        client_secret=secrets["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
    )

def sheets_client():
    sa = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT"])
    creds = service_account.Credentials.from_service_account_info(
        sa, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)

# ── date helpers ───────────────────────────────────────────────────────────────

def report_date():
    # YouTube Analytics has a ~3 day processing lag
    return date.today() - timedelta(days=3)

def current_week():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday

# ── sheets helpers ────────────────────────────────────────────────────────────

def get_or_create_sheet(spreadsheet, name, headers):
    try:
        ws = spreadsheet.worksheet(name)
        if not ws.row_values(1):
            ws.append_row(headers)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=name, rows=10000, cols=len(headers))
        ws.append_row(headers)
    return ws

def row_exists(ws, value, col=1):
    return str(value) in ws.col_values(col)

# ── YouTube ───────────────────────────────────────────────────────────────────

def fetch_yt_channel_metrics(creds, for_date):
    svc = build("youtubeAnalytics", "v2", credentials=creds)
    d = for_date.isoformat()
    resp = svc.reports().query(
        ids="channel==MINE",
        startDate=d,
        endDate=d,
        metrics="views,averageViewPercentage,subscribersGained,shares",
    ).execute()
    row = (resp.get("rows") or [[0] * 4])[0]
    return {
        "date": d,
        "views": int(row[0]),
        "avg_view_pct": round(float(row[1]), 2),
        "subscribers_gained": int(row[2]),
        "shares": int(row[3]),
    }

def _query_yt_videos(analytics, data_svc, start, end, content_filter=None):
    kwargs = dict(
        ids="channel==MINE",
        startDate=start.isoformat(),
        endDate=end.isoformat(),
        dimensions="video",
        metrics="views,averageViewPercentage",
        sort="-views",
        maxResults=25,
    )
    if content_filter:
        kwargs["filters"] = f"creatorContentType=={content_filter}"

    rows = analytics.reports().query(**kwargs).execute().get("rows") or []
    if not rows:
        return []

    video_ids = [r[0] for r in rows]
    snippets = {
        v["id"]: v["snippet"]
        for v in data_svc.videos().list(
            part="snippet", id=",".join(video_ids)
        ).execute().get("items", [])
    }

    return [
        {
            "video_id": row[0],
            "title": snippets.get(row[0], {}).get("title", row[0]),
            "thumbnail": snippets.get(row[0], {}).get("thumbnails", {}).get("high", {}).get("url", ""),
            "published_at": snippets.get(row[0], {}).get("publishedAt", "")[:10],
            "views": int(row[1]),
            "avg_view_pct": round(float(row[2]), 2),
        }
        for row in rows
    ]

def fetch_yt_video_metrics(creds, start, end):
    analytics = build("youtubeAnalytics", "v2", credentials=creds)
    data_svc = build("youtube", "v3", credentials=creds)
    videos = _query_yt_videos(analytics, data_svc, start, end, "videoOnDemand")
    shorts = _query_yt_videos(analytics, data_svc, start, end, "shorts")
    return {"videos": videos, "shorts": shorts}

# ── Megaphone ─────────────────────────────────────────────────────────────────

MEGAPHONE_BASE = "https://cms.megaphone.fm/api"

def meg_headers():
    return {"Authorization": f"Token token={os.environ['MEGAPHONE_API_KEY']}"}

def meg_get(path, params=None):
    resp = requests.get(f"{MEGAPHONE_BASE}{path}", headers=meg_headers(), params=params)
    resp.raise_for_status()
    return resp.json()

def fetch_megaphone_data(network_id, start, end):
    podcasts = meg_get(f"/networks/{network_id}/podcasts")
    results = []

    for podcast in podcasts:
        pid = podcast["id"]
        page = 1
        while True:
            episodes = meg_get(f"/podcasts/{pid}/episodes", params={"page": page, "per": 50})
            if not episodes:
                break
            for ep in episodes:
                try:
                    dl_data = meg_get(
                        f"/episodes/{ep['id']}/analytics/downloads",
                        params={"startDate": start.isoformat(), "endDate": end.isoformat()},
                    )
                    downloads = sum(d.get("downloads", 0) for d in dl_data.get("downloads", []))
                except Exception as e:
                    print(f"  Could not fetch downloads for episode {ep['id']}: {e}")
                    downloads = 0

                results.append({
                    "episode_id": ep["id"],
                    "podcast_title": podcast.get("title", ""),
                    "title": ep.get("title", ""),
                    "published_at": (ep.get("pubdate") or "")[:10],
                    "artwork_url": ep.get("imageFile") or podcast.get("imageFile", ""),
                    "downloads": downloads,
                })

            if len(episodes) < 50:
                break
            page += 1

    return results

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    creds = youtube_credentials()
    gc = sheets_client()
    sheet = gc.open_by_key(os.environ["GOOGLE_SHEET_ID"])
    network_id = os.environ.get("MEGAPHONE_NETWORK_ID", "")

    today = date.today()
    rd = report_date()
    week_start, week_end = current_week()

    # Daily YouTube channel metrics
    ws_yt = get_or_create_sheet(sheet, "YouTube_Metrics", [
        "date", "views", "avg_view_pct", "subscribers_gained", "shares",
    ])
    if not row_exists(ws_yt, rd.isoformat()):
        metrics = fetch_yt_channel_metrics(creds, rd)
        ws_yt.append_row(list(metrics.values()))
        print(f"YouTube channel metrics written for {rd}")
    else:
        print(f"YouTube channel metrics already exist for {rd}, skipping")

    # Weekly pulls run on Sundays
    if today.weekday() == 6:
        ws_yt_vid = get_or_create_sheet(sheet, "YouTube_Videos", [
            "week_start", "video_id", "title", "thumbnail",
            "published_at", "views", "avg_view_pct",
        ])
        ws_top = get_or_create_sheet(sheet, "Top_Performers", [
            "week_start", "platform", "content_id", "title",
            "thumbnail_url", "metric_value", "metric_name",
        ])

        # YouTube video breakdown
        if not row_exists(ws_yt_vid, week_start.isoformat()):
            result = fetch_yt_video_metrics(creds, week_start, week_end)
            videos = result["videos"]
            shorts = result["shorts"]
            all_content = videos + shorts
            for v in all_content:
                ws_yt_vid.append_row([week_start.isoformat()] + list(v.values()))
            print(f"YouTube video metrics written for week of {week_start} ({len(videos)} videos, {len(shorts)} shorts)")

            qualified_videos = [v for v in videos if v["views"] >= 200]
            if qualified_videos:
                top = max(qualified_videos, key=lambda x: x["views"])
                ws_top.append_row([
                    week_start.isoformat(), "YouTube Video",
                    top["video_id"], top["title"],
                    top["thumbnail"], top["views"], "views",
                ])
                print(f"Top YouTube video: {top['title']} ({top['views']} views)")

            qualified_shorts = [s for s in shorts if s["views"] >= 200]
            if qualified_shorts:
                top_short = max(qualified_shorts, key=lambda x: x["views"])
                ws_top.append_row([
                    week_start.isoformat(), "YouTube Short",
                    top_short["video_id"], top_short["title"],
                    top_short["thumbnail"], top_short["views"], "views",
                ])
                print(f"Top YouTube Short: {top_short['title']} ({top_short['views']} views)")

        # Megaphone episode breakdown (skipped if API key not configured)
        if os.environ.get("MEGAPHONE_API_KEY") and network_id:
            ws_meg = get_or_create_sheet(sheet, "Megaphone_Episodes", [
                "week_start", "episode_id", "podcast_title", "episode_title",
                "published_at", "artwork_url", "downloads",
            ])
            if not row_exists(ws_meg, week_start.isoformat()):
                episodes = fetch_megaphone_data(network_id, week_start, week_end)
                for ep in episodes:
                    ws_meg.append_row([week_start.isoformat()] + list(ep.values()))
                print(f"Megaphone data written for week of {week_start} ({len(episodes)} episodes)")

                if episodes:
                    top_ep = max(episodes, key=lambda x: x["downloads"])
                    ws_top.append_row([
                        week_start.isoformat(), "Megaphone",
                        top_ep["episode_id"], top_ep["title"],
                        top_ep["artwork_url"], top_ep["downloads"], "downloads",
                    ])
                    print(f"Top Megaphone episode: {top_ep['title']} ({top_ep['downloads']} downloads)")
        else:
            print("Megaphone credentials not configured — skipping.")

    print("ETL complete.")

if __name__ == "__main__":
    main()
