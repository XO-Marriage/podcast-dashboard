import io
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2 import service_account
import gspread
from datetime import date, timedelta
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether,
)
from reportlab.platypus.flowables import Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Naked Marriage Podcast Dashboard",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Styles ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  section[data-testid="stSidebar"] { display: none; }
  /* Remove Streamlit's default top padding so header sits flush */
  .block-container { padding-top: 0.5rem !important; padding-bottom: 2rem; }
  header[data-testid="stHeader"] { display: none; }
  .section-header {
    font-size: 1.1rem; font-weight: 600; color: #9ba3b2;
    text-transform: uppercase; letter-spacing: 0.08em;
    margin-top: 2rem; margin-bottom: 0.5rem;
    border-bottom: 1px solid #2a2d3e; padding-bottom: 0.4rem;
  }
  .kpi-card {
    background: #1e2130; border-radius: 10px;
    padding: 1.2rem 1.5rem; text-align: center;
  }
  .kpi-value { font-size: 2rem; font-weight: 700; color: #ffffff; line-height: 1.1; }
  .kpi-label { font-size: 0.8rem; color: #9ba3b2; margin-top: 0.3rem; }
  .kpi-delta { font-size: 0.85rem; margin-top: 0.25rem; }
  .delta-up   { color: #2ecc71; }
  .delta-down { color: #e74c3c; }
  .platform-badge {
    display: inline-block; border-radius: 4px;
    padding: 2px 8px; font-size: 0.75rem; font-weight: 600;
  }
  .badge-yt-video  { background:#c0392b; color:#fff; }
  .badge-yt-short  { background:#e67e22; color:#fff; }
  .badge-megaphone { background:#27ae60; color:#fff; }
</style>
""", unsafe_allow_html=True)

# ── Data loading ──────────────────────────────────────────────────────────────
_SA_FILE  = Path(__file__).parent / "service_account.json"
_SHEET_ID = Path(__file__).parent / "config.txt"

def _get_sheet():
    """Returns an open gspread spreadsheet, preferring st.secrets over local files."""
    try:
        # Streamlit Community Cloud: credentials stored in st.secrets
        sa_info  = dict(st.secrets["gcp_service_account"])
        sheet_id = st.secrets["google_sheet_id"]
        creds = service_account.Credentials.from_service_account_info(
            sa_info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
        )
    except Exception:
        # Local development: read from files next to this script
        creds    = service_account.Credentials.from_service_account_file(
            str(_SA_FILE), scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
        )
        sheet_id = _SHEET_ID.read_text().strip()
    gc = gspread.authorize(creds)
    return gc.open_by_key(sheet_id)

@st.cache_data(ttl=1800, show_spinner="Loading data…")
def load_data():
    sheet = _get_sheet()

    # YouTube daily metrics
    yt = pd.DataFrame(sheet.worksheet("YouTube_Metrics").get_all_records())
    yt["date"] = pd.to_datetime(yt["date"], errors="coerce")
    for c in ["views", "subscribers_gained", "shares"]:
        yt[c] = pd.to_numeric(yt[c], errors="coerce").fillna(0).astype(int)
    yt["avg_view_pct"] = pd.to_numeric(yt["avg_view_pct"], errors="coerce").fillna(0)
    yt = yt.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    # Weekly top performers
    top = pd.DataFrame(sheet.worksheet("Top_Performers").get_all_records())
    top["week_start"]    = pd.to_datetime(top["week_start"], errors="coerce")
    top["metric_value"]  = pd.to_numeric(top["metric_value"], errors="coerce").fillna(0).astype(int)
    top = top.dropna(subset=["week_start"]).sort_values("week_start", ascending=False).reset_index(drop=True)

    # Megaphone episodes
    meg = pd.DataFrame(sheet.worksheet("Megaphone_Episodes").get_all_records())
    meg["published_at"] = pd.to_datetime(meg["published_at"], errors="coerce")
    for c in ["downloads", "first_24h", "first_7d", "to_date"]:
        if c in meg.columns:
            meg[c] = pd.to_numeric(meg[c], errors="coerce").fillna(0).astype(int)
    meg = meg.dropna(subset=["published_at"]).sort_values("downloads", ascending=False).reset_index(drop=True)

    # Per-video weekly metrics (for cumulative top performer calculation)
    vid = pd.DataFrame(sheet.worksheet("YouTube_Videos").get_all_records())
    vid["week_start"] = pd.to_datetime(vid["week_start"], errors="coerce")
    vid["views"] = pd.to_numeric(vid["views"], errors="coerce").fillna(0).astype(int)
    vid["avg_view_pct"] = pd.to_numeric(vid["avg_view_pct"], errors="coerce").fillna(0)
    vid = vid.dropna(subset=["week_start"]).reset_index(drop=True)

    return yt, top, meg, vid

yt_df, top_df, meg_df, vid_df = load_data()

# ── Header & date picker ──────────────────────────────────────────────────────
st.markdown("## 🎙️ Naked Marriage Podcast Dashboard")

col_range, col_spacer = st.columns([2, 5])
with col_range:
    preset = st.selectbox(
        "Date range",
        ["Last 7 days", "Last 28 days", "Last 90 days", "Last 365 days", "All time", "Custom"],
        index=1,
        label_visibility="collapsed",
    )
    today = date.today()
    if preset == "Last 7 days":
        start_date, end_date = today - timedelta(days=7), today
    elif preset == "Last 28 days":
        start_date, end_date = today - timedelta(days=28), today
    elif preset == "Last 90 days":
        start_date, end_date = today - timedelta(days=90), today
    elif preset == "Last 365 days":
        start_date, end_date = today - timedelta(days=365), today
    elif preset == "All time":
        start_date = yt_df["date"].min().date() if not yt_df.empty else date(2020, 1, 1)
        end_date   = today
    else:
        custom = st.date_input("Pick range", value=(today - timedelta(days=28), today))
        start_date, end_date = (custom if len(custom) == 2 else (custom[0], today))

# Convert to timestamps for filtering
ts_start = pd.Timestamp(start_date)
ts_end   = pd.Timestamp(end_date)

# ── Filter data ───────────────────────────────────────────────────────────────
yt_f   = yt_df[(yt_df["date"] >= ts_start) & (yt_df["date"] <= ts_end)]
top_f  = top_df[(top_df["week_start"] >= ts_start) & (top_df["week_start"] <= ts_end)]
meg_f  = meg_df[
    (meg_df["published_at"] >= ts_start) & (meg_df["published_at"] <= ts_end)
] if preset != "All time" else meg_df

# Previous period for deltas
period_days = (ts_end - ts_start).days or 1
ts_prev_end   = ts_start - timedelta(days=1)
ts_prev_start = ts_prev_end - timedelta(days=period_days)
yt_prev = yt_df[(yt_df["date"] >= ts_prev_start) & (yt_df["date"] <= ts_prev_end)]

def delta_html(curr, prev):
    if prev == 0:
        return ""
    pct = ((curr - prev) / prev) * 100
    cls = "delta-up" if pct >= 0 else "delta-down"
    arrow = "▲" if pct >= 0 else "▼"
    return f'<div class="kpi-delta {cls}">{arrow} {abs(pct):.1f}% vs prev period</div>'

def fmt(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)

# ── YouTube KPIs ──────────────────────────────────────────────────────────────
st.markdown('<div class="section-header">YouTube Performance</div>', unsafe_allow_html=True)

kpis = [
    ("views",              "Views",               "int"),
    ("subscribers_gained", "Subscribers Gained",  "int"),
    ("avg_view_pct",       "Avg % Viewed",         "pct"),
    ("shares",             "Shares",              "int"),
]

cols = st.columns(4)
for col, (field, label, kind) in zip(cols, kpis):
    curr = yt_f[field].sum() if kind == "int" else yt_f[field].mean()
    prev = yt_prev[field].sum() if kind == "int" else yt_prev[field].mean()
    val_str = f"{curr:.1f}%" if kind == "pct" else fmt(int(curr))
    with col:
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-value">{val_str}</div>'
            f'<div class="kpi-label">{label}</div>'
            f'{delta_html(curr, prev)}'
            f'</div>',
            unsafe_allow_html=True,
        )

# ── Views over time chart ─────────────────────────────────────────────────────
st.markdown('<div class="section-header">Views Over Time</div>', unsafe_allow_html=True)

if yt_f.empty:
    st.info("No YouTube data for this date range.")
else:
    fig = px.area(
        yt_f, x="date", y="views",
        color_discrete_sequence=["#e74c3c"],
    )
    fig.update_traces(line_width=1.5, fillcolor="rgba(231,76,60,0.15)")
    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        height=220,
        xaxis_title=None, yaxis_title=None,
        plot_bgcolor="#1e2130", paper_bgcolor="#1e2130",
        font=dict(color="#9ba3b2"),
        xaxis=dict(showgrid=False, color="#9ba3b2"),
        yaxis=dict(showgrid=True, gridcolor="#2a2d3e", color="#9ba3b2"),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)

# ── Top Performers ────────────────────────────────────────────────────────────
st.markdown('<div class="section-header">Top Performers</div>', unsafe_allow_html=True)

BADGE = {
    "YouTube Video":  ("badge-yt-video",  "YT Video"),
    "YouTube Short":  ("badge-yt-short",  "YT Short"),
    "Megaphone":      ("badge-megaphone", "Megaphone"),
}

if top_f.empty:
    next_sunday = today + timedelta(days=(6 - today.weekday()))
    st.info(f"No complete weeks fall in this date range yet. Top performer data updates every Sunday. Next update: {next_sunday.strftime('%b %d')}.")

# Always derive Megaphone top performer directly from meg_df by published_at
meg_top_source = meg_f if not meg_f.empty else meg_df
meg_top_source = meg_top_source.drop_duplicates(subset=["episode_title", "podcast_title"], keep="first")
meg_top_ep = meg_top_source.nlargest(1, "downloads")

# Build combined best list: top YouTube Video + top YouTube Short aggregated
# from YouTube_Videos (cumulative views in selected range), plus top Megaphone episode.

# Platform lookup: video_id → "YouTube Video" or "YouTube Short" from historical data
platform_lookup = (
    top_df[top_df["platform"].isin(["YouTube Video", "YouTube Short"])]
    .drop_duplicates(subset=["content_id"])
    .set_index("content_id")["platform"]
    .to_dict()
)

vid_f = vid_df[(vid_df["week_start"] >= ts_start) & (vid_df["week_start"] <= ts_end)]

if not vid_f.empty:
    vid_agg = (
        vid_f.groupby("video_id")
        .agg(
            title=("title", "first"),
            thumbnail_url=("thumbnail", "first"),
            metric_value=("views", "sum"),
        )
        .reset_index()
    )
    vid_agg["platform"]    = vid_agg["video_id"].map(platform_lookup).fillna("YouTube Video")
    vid_agg["metric_name"] = "views"
    vid_agg["week_start"]  = ts_start
    vid_agg["date_label"]  = (
        f"{start_date.strftime('%b %-d')} – {end_date.strftime('%b %-d, %Y')}"
    )
    yt_best = (
        vid_agg
        .sort_values("metric_value", ascending=False)
        .drop_duplicates("platform")
    )
else:
    # Fall back to weekly snapshots when YouTube_Videos has no data for this range
    yt_best = (
        top_f[top_f["platform"].isin(["YouTube Video", "YouTube Short"])]
        .sort_values("metric_value", ascending=False)
        .drop_duplicates("platform")
    )
    if not yt_best.empty:
        yt_best = yt_best.copy()
        yt_best["date_label"] = yt_best["week_start"].apply(
            lambda d: f"Week of {d.strftime('%b %-d, %Y')}" if pd.notna(d) else ""
        )

meg_rows = []
if not meg_top_ep.empty:
    row = meg_top_ep.iloc[0]
    pub = row.get("published_at", pd.NaT)
    meg_rows.append({
        "platform":      "Megaphone",
        "title":         row.get("episode_title", ""),
        "thumbnail_url": "",
        "metric_value":  row["downloads"],
        "metric_name":   "downloads",
        "week_start":    pub,
        "date_label":    f"Published {pub.strftime('%b %-d, %Y')}" if pd.notna(pub) else "",
    })

meg_top_df = pd.DataFrame(meg_rows)
best = pd.concat([yt_best, meg_top_df], ignore_index=True) if not meg_top_df.empty else yt_best

if best.empty:
    st.info("No top performer data yet. Run the ETL on a Sunday to populate weekly results.")
else:
    # Show as cards
    card_cols = st.columns(3)
    for i, (_, row) in enumerate(best.iterrows()):
        cls, badge_label = BADGE.get(row["platform"], ("badge-megaphone", row["platform"]))
        metric_label = "views" if "YouTube" in row["platform"] else "downloads"
        with card_cols[i % 3]:
            title      = (row["title"][:72] + "…") if len(row["title"]) > 72 else row["title"]
            date_label = row.get("date_label") or (
                f"Week of {row['week_start'].strftime('%b %-d, %Y')}"
                if pd.notna(row.get("week_start")) else ""
            )
            # Show thumbnail via st.image for proper sizing, then overlay text
            if row.get("thumbnail_url"):
                st.image(row["thumbnail_url"], use_container_width=True)
            else:
                # Megaphone placeholder — matches hqdefault 4:3 ratio via padding-bottom hack
                st.markdown("""
                <div style="width:100%;position:relative;overflow:hidden;border-radius:10px 10px 0 0;">
                  <div style="padding-bottom:75%;"></div>
                  <div style="position:absolute;top:0;left:0;right:0;bottom:0;
                       background:linear-gradient(135deg,#1a3a2a 0%,#27ae60 100%);
                       display:flex;align-items:center;justify-content:center;">
                    <svg xmlns="http://www.w3.org/2000/svg" width="72" height="72" viewBox="0 0 24 24"
                         fill="none" stroke="rgba(255,255,255,0.85)" stroke-width="1.5"
                         stroke-linecap="round" stroke-linejoin="round">
                      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                      <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                      <line x1="12" y1="19" x2="12" y2="23"/>
                      <line x1="8" y1="23" x2="16" y2="23"/>
                    </svg>
                  </div>
                </div>
                """, unsafe_allow_html=True)
            has_thumb = bool(row.get("thumbnail_url"))
            top_radius = "10px 10px" if has_thumb else "0 0"
            st.markdown(
                f'<div style="background:#1e2130;border-radius:{top_radius} 10px 10px;padding:10px 14px 14px;">'
                f'<span class="platform-badge {cls}">{badge_label}</span>'
                f'<div style="font-size:0.88rem;color:#fff;margin-top:6px;line-height:1.4;">{title}</div>'
                f'<div style="font-size:1.5rem;font-weight:700;color:#fff;margin-top:8px;">'
                f'{fmt(row["metric_value"])} '
                f'<span style="font-size:0.75rem;color:#9ba3b2;">{metric_label}</span></div>'
                f'<div style="font-size:0.73rem;color:#9ba3b2;margin-top:2px;">{date_label}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.markdown("<div style='margin-bottom:1rem'></div>", unsafe_allow_html=True)

    # Full history table (collapsible)
    with st.expander("View full top performers history"):
        display = top_f[["week_start", "platform", "title", "metric_value", "metric_name"]].copy()
        display["week_start"] = display["week_start"].dt.strftime("%Y-%m-%d")
        display.columns = ["Week", "Platform", "Title", "Value", "Metric"]
        display = display.sort_values("Week", ascending=False).reset_index(drop=True)
        st.dataframe(display, use_container_width=True, hide_index=True)

# ── Megaphone Performance ─────────────────────────────────────────────────────
st.markdown('<div class="section-header">Megaphone Episodes</div>', unsafe_allow_html=True)

meg_show = meg_f if not meg_f.empty else meg_df

if meg_show.empty:
    st.info("No Megaphone data for this range. Upload a CSV using upload_megaphone.py.")
else:
    # Deduplicate: keep highest-download row per episode title
    meg_deduped = (
        meg_show
        .sort_values("downloads", ascending=False)
        .drop_duplicates(subset=["episode_title", "podcast_title"], keep="first")
        .nlargest(50, "downloads")
    )
    display_meg = meg_deduped[["episode_title", "podcast_title", "published_at", "downloads", "first_24h", "first_7d"]].copy()
    display_meg["published_at"] = display_meg["published_at"].dt.strftime("%Y-%m-%d")
    display_meg.columns = ["Episode", "Podcast", "Published", "Downloads", "First 24h", "First 7 Days"]
    st.dataframe(display_meg, use_container_width=True, hide_index=True, height=400)

# ── PDF Export ───────────────────────────────────────────────────────────────

def generate_pdf(yt_data, top_data, meg_data, best_data, label, views_total,
                 subs_total, avg_pct, shares_total, yt_prev_data, period_days_val):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=0.6*inch, rightMargin=0.6*inch,
        topMargin=0.6*inch, bottomMargin=0.6*inch,
    )

    # ── colour palette ────────────────────────────────────────────────────────
    BG       = colors.HexColor("#1e2130")
    ACCENT   = colors.HexColor("#e74c3c")
    GREEN    = colors.HexColor("#27ae60")
    ORANGE   = colors.HexColor("#e67e22")
    MUTED    = colors.HexColor("#9ba3b2")
    WHITE    = colors.white
    DARK     = colors.HexColor("#12141f")
    RULE     = colors.HexColor("#2a2d3e")

    # ── styles ────────────────────────────────────────────────────────────────
    base = getSampleStyleSheet()
    title_style   = ParagraphStyle("title",   fontSize=20, textColor=WHITE,
                                   fontName="Helvetica-Bold", spaceAfter=2)
    sub_style     = ParagraphStyle("sub",     fontSize=9,  textColor=MUTED,
                                   fontName="Helvetica",    spaceAfter=0)
    section_style = ParagraphStyle("section", fontSize=9,  textColor=MUTED,
                                   fontName="Helvetica-Bold", spaceBefore=14,
                                   spaceAfter=4, letterSpacing=1.5)
    cell_style    = ParagraphStyle("cell",    fontSize=8,  textColor=WHITE,
                                   fontName="Helvetica",    leading=11)
    small_style   = ParagraphStyle("small",   fontSize=7,  textColor=MUTED,
                                   fontName="Helvetica")

    def section(text):
        return [
            Paragraph(text.upper(), section_style),
            HRFlowable(width="100%", thickness=0.5, color=RULE, spaceAfter=6),
        ]

    def delta_str(curr, prev):
        if prev == 0:
            return ""
        pct = ((curr - prev) / prev) * 100
        arrow = "▲" if pct >= 0 else "▼"
        return f"{arrow} {abs(pct):.1f}%"

    def fmt_n(n):
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n/1_000:.1f}K"
        return str(int(n))

    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(Paragraph("🎙 Naked Marriage Podcast Dashboard", title_style))
    story.append(Paragraph(f"Report period: {label}  ·  Generated {date.today().strftime('%B %-d, %Y')}", sub_style))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1, color=ACCENT, spaceAfter=10))

    # ── YouTube KPIs ──────────────────────────────────────────────────────────
    story += section("YouTube Performance")

    prev_views = yt_prev_data["views"].sum() if not yt_prev_data.empty else 0
    prev_subs  = yt_prev_data["subscribers_gained"].sum() if not yt_prev_data.empty else 0
    prev_pct   = yt_prev_data["avg_view_pct"].mean() if not yt_prev_data.empty else 0
    prev_sh    = yt_prev_data["shares"].sum() if not yt_prev_data.empty else 0

    kpi_data = [
        [
            Paragraph(f'<font size="18"><b>{fmt_n(views_total)}</b></font>', ParagraphStyle("v", textColor=WHITE, fontName="Helvetica-Bold", fontSize=18, alignment=TA_CENTER)),
            Paragraph(f'<font size="18"><b>{fmt_n(subs_total)}</b></font>',  ParagraphStyle("v", textColor=WHITE, fontName="Helvetica-Bold", fontSize=18, alignment=TA_CENTER)),
            Paragraph(f'<font size="18"><b>{avg_pct:.1f}%</b></font>',        ParagraphStyle("v", textColor=WHITE, fontName="Helvetica-Bold", fontSize=18, alignment=TA_CENTER)),
            Paragraph(f'<font size="18"><b>{fmt_n(shares_total)}</b></font>', ParagraphStyle("v", textColor=WHITE, fontName="Helvetica-Bold", fontSize=18, alignment=TA_CENTER)),
        ],
        [
            Paragraph("Views",              ParagraphStyle("l", textColor=MUTED, fontName="Helvetica", fontSize=8, alignment=TA_CENTER)),
            Paragraph("Subscribers Gained", ParagraphStyle("l", textColor=MUTED, fontName="Helvetica", fontSize=8, alignment=TA_CENTER)),
            Paragraph("Avg % Viewed",       ParagraphStyle("l", textColor=MUTED, fontName="Helvetica", fontSize=8, alignment=TA_CENTER)),
            Paragraph("Shares",             ParagraphStyle("l", textColor=MUTED, fontName="Helvetica", fontSize=8, alignment=TA_CENTER)),
        ],
        [
            Paragraph(delta_str(views_total, prev_views), ParagraphStyle("d", textColor=GREEN if views_total >= prev_views else ACCENT, fontName="Helvetica", fontSize=8, alignment=TA_CENTER)),
            Paragraph(delta_str(subs_total,  prev_subs),  ParagraphStyle("d", textColor=GREEN if subs_total  >= prev_subs  else ACCENT, fontName="Helvetica", fontSize=8, alignment=TA_CENTER)),
            Paragraph(delta_str(avg_pct,     prev_pct),   ParagraphStyle("d", textColor=GREEN if avg_pct     >= prev_pct   else ACCENT, fontName="Helvetica", fontSize=8, alignment=TA_CENTER)),
            Paragraph(delta_str(shares_total,prev_sh),    ParagraphStyle("d", textColor=GREEN if shares_total>= prev_sh    else ACCENT, fontName="Helvetica", fontSize=8, alignment=TA_CENTER)),
        ],
    ]

    W = 7.3 * inch
    kpi_table = Table(kpi_data, colWidths=[W/4]*4, rowHeights=[28, 14, 14])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND",  (0,0), (-1,-1), BG),
        ("ROUNDEDCORNERS", [6]),
        ("ALIGN",       (0,0), (-1,-1), "CENTER"),
        ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
        ("LINEAFTER",   (0,0), (2,-1),  0.5, RULE),
        ("TOPPADDING",  (0,0), (-1,0),  10),
        ("BOTTOMPADDING",(0,-1),(-1,-1),8),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 10))

    # ── Views over time chart ─────────────────────────────────────────────────
    if not yt_data.empty:
        story += section("Views Over Time")
        fig = px.area(yt_data, x="date", y="views", color_discrete_sequence=["#e74c3c"])
        fig.update_traces(line_width=1.5, fillcolor="rgba(231,76,60,0.15)")
        fig.update_layout(
            margin=dict(l=30, r=10, t=10, b=30), height=200, width=720,
            xaxis_title=None, yaxis_title=None,
            plot_bgcolor="#1e2130", paper_bgcolor="#1e2130",
            font=dict(color="#9ba3b2"),
            xaxis=dict(showgrid=False, color="#9ba3b2"),
            yaxis=dict(showgrid=True, gridcolor="#2a2d3e", color="#9ba3b2"),
        )
        chart_buf = io.BytesIO(fig.to_image(format="png", scale=2))
        story.append(RLImage(chart_buf, width=W, height=2*inch))
        story.append(Spacer(1, 6))

    # ── Top Performers ────────────────────────────────────────────────────────
    if not best_data.empty:
        story += section("Top Performers")
        platform_colors = {
            "YouTube Video": ACCENT,
            "YouTube Short": ORANGE,
            "Megaphone":     GREEN,
        }
        for _, row in best_data.iterrows():
            plat   = row.get("platform", "")
            title  = row.get("title", "")[:90]
            metric = int(row.get("metric_value", 0))
            dlabel = row.get("date_label", "") or ""
            mname  = "views" if "YouTube" in plat else "downloads"
            pcol   = platform_colors.get(plat, MUTED)

            row_data = [[
                Paragraph(f'<font color="{pcol.hexval() if hasattr(pcol,"hexval") else "#ffffff"}"><b>[{plat}]</b></font>  {title}', cell_style),
                Paragraph(f'<b>{fmt_n(metric)}</b> {mname}', ParagraphStyle("rv", textColor=WHITE, fontName="Helvetica-Bold", fontSize=9, alignment=TA_RIGHT)),
            ]]
            sub_row = [[
                Paragraph(dlabel, small_style),
                Paragraph("", small_style),
            ]]
            t = Table(row_data + sub_row, colWidths=[W*0.75, W*0.25])
            t.setStyle(TableStyle([
                ("BACKGROUND",    (0,0), (-1,-1), BG),
                ("TOPPADDING",    (0,0), (-1,-1), 5),
                ("BOTTOMPADDING", (0,-1),(-1,-1), 6),
                ("LEFTPADDING",   (0,0), (-1,-1), 8),
                ("RIGHTPADDING",  (0,0), (-1,-1), 8),
                ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ]))
            story.append(KeepTogether([t, Spacer(1, 4)]))

    # ── Megaphone Episodes ────────────────────────────────────────────────────
    if not meg_data.empty:
        story += section("Top Megaphone Episodes")
        meg_display = (
            meg_data
            .sort_values("downloads", ascending=False)
            .drop_duplicates(subset=["episode_title", "podcast_title"], keep="first")
            .head(20)
        )
        header = [
            Paragraph("<b>Episode</b>",     ParagraphStyle("th", textColor=MUTED, fontName="Helvetica-Bold", fontSize=7)),
            Paragraph("<b>Published</b>",   ParagraphStyle("th", textColor=MUTED, fontName="Helvetica-Bold", fontSize=7)),
            Paragraph("<b>Downloads</b>",   ParagraphStyle("th", textColor=MUTED, fontName="Helvetica-Bold", fontSize=7, alignment=TA_RIGHT)),
            Paragraph("<b>First 24h</b>",   ParagraphStyle("th", textColor=MUTED, fontName="Helvetica-Bold", fontSize=7, alignment=TA_RIGHT)),
            Paragraph("<b>First 7 Days</b>",ParagraphStyle("th", textColor=MUTED, fontName="Helvetica-Bold", fontSize=7, alignment=TA_RIGHT)),
        ]
        rows = [header]
        for _, r in meg_display.iterrows():
            pub = r["published_at"]
            pub_str = pub.strftime("%-m/%-d/%Y") if pd.notna(pub) else ""
            ep_title = str(r.get("episode_title",""))[:60]
            rows.append([
                Paragraph(ep_title, ParagraphStyle("tc", textColor=WHITE, fontName="Helvetica", fontSize=7, leading=9)),
                Paragraph(pub_str,  ParagraphStyle("tc", textColor=WHITE, fontName="Helvetica", fontSize=7)),
                Paragraph(fmt_n(int(r.get("downloads",0))),  ParagraphStyle("tc", textColor=WHITE, fontName="Helvetica", fontSize=7, alignment=TA_RIGHT)),
                Paragraph(fmt_n(int(r.get("first_24h",0))),  ParagraphStyle("tc", textColor=WHITE, fontName="Helvetica", fontSize=7, alignment=TA_RIGHT)),
                Paragraph(fmt_n(int(r.get("first_7d",0))),   ParagraphStyle("tc", textColor=WHITE, fontName="Helvetica", fontSize=7, alignment=TA_RIGHT)),
            ])
        meg_table = Table(rows, colWidths=[W*0.44, W*0.13, W*0.14, W*0.14, W*0.15])
        meg_table.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0),  colors.HexColor("#12141f")),
            ("BACKGROUND",    (0,1), (-1,-1), BG),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [BG, colors.HexColor("#252940")]),
            ("LINEBELOW",     (0,0), (-1,0),  0.5, RULE),
            ("TOPPADDING",    (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ("LEFTPADDING",   (0,0), (-1,-1), 6),
            ("RIGHTPADDING",  (0,0), (-1,-1), 6),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ]))
        story.append(meg_table)

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.5, color=RULE))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Naked Marriage · xomarriage-podcast.streamlit.app · YouTube data has a 3-day processing lag",
        ParagraphStyle("foot", textColor=MUTED, fontName="Helvetica", fontSize=7, alignment=TA_CENTER),
    ))

    doc.build(story)
    buf.seek(0)
    return buf


# ── PDF download button ───────────────────────────────────────────────────────
st.markdown('<div class="section-header">Export</div>', unsafe_allow_html=True)

if st.button("⬇ Download PDF Report"):
    with st.spinner("Building PDF…"):
        pdf_buf = generate_pdf(
            yt_data=yt_f,
            top_data=top_f,
            meg_data=meg_f if not meg_f.empty else meg_df,
            best_data=best if not best.empty else pd.DataFrame(),
            label=f"{start_date.strftime('%b %-d')} – {end_date.strftime('%b %-d, %Y')}",
            views_total=int(yt_f["views"].sum()),
            subs_total=int(yt_f["subscribers_gained"].sum()),
            avg_pct=float(yt_f["avg_view_pct"].mean()) if not yt_f.empty else 0.0,
            shares_total=int(yt_f["shares"].sum()),
            yt_prev_data=yt_prev,
            period_days_val=period_days,
        )
    filename = f"podcast_report_{start_date}_{end_date}.pdf"
    st.download_button(
        label="📄 Click to save PDF",
        data=pdf_buf,
        file_name=filename,
        mime="application/pdf",
    )

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    f"Data refreshes every 30 min · YouTube data has a 3-day processing lag · "
    f"Last loaded: {pd.Timestamp.now().strftime('%b %d, %Y %I:%M %p')}"
)
