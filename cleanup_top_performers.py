import warnings
from pathlib import Path
from google.oauth2 import service_account
import gspread

warnings.filterwarnings("ignore")

SA_FILE     = Path(__file__).parent / "service_account.json"
CONFIG_FILE = Path(__file__).parent / "config.txt"

def sheets_client():
    creds = service_account.Credentials.from_service_account_file(
        str(SA_FILE), scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)

def main():
    gc    = sheets_client()
    sheet = gc.open_by_key(CONFIG_FILE.read_text().strip())
    ws    = sheet.worksheet("Top_Performers")

    rows = ws.get_all_values()
    header = rows[0]
    data   = rows[1:]

    print(f"Total rows (excluding header): {len(data)}")

    # Keep row if: it's a Megaphone entry, OR metric_value >= 200
    # Columns: week_start(0), platform(1), content_id(2), title(3),
    #          thumbnail_url(4), metric_value(5), metric_name(6)
    keep = []
    removed = 0
    for row in data:
        platform = row[1] if len(row) > 1 else ""
        try:
            metric_val = int(row[5]) if len(row) > 5 and row[5] else 0
        except ValueError:
            metric_val = 0

        if platform == "Megaphone" or metric_val >= 200:
            keep.append(row)
        else:
            removed += 1

    print(f"Rows to keep: {len(keep)}")
    print(f"Rows to remove: {removed}")

    # Rewrite sheet: clear data rows, then write back keepers
    # Delete from bottom up to preserve row indices, but it's easier to clear + rewrite
    ws.clear()
    ws.append_row(header)
    if keep:
        ws.append_rows(keep, value_input_option="RAW")
    print("Sheet rewritten. Done.")

if __name__ == "__main__":
    main()
