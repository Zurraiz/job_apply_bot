"""
Google Sheets Setup Helper
Run this once to verify your Google Sheets connection works.

HOW TO GET A SERVICE ACCOUNT JSON:
1. Go to https://console.cloud.google.com
2. Create a new project (or use existing)
3. Enable "Google Sheets API" and "Google Drive API"
4. Go to IAM & Admin > Service Accounts > Create Service Account
5. Download the JSON key file
6. Save it as config/google_service_account.json
7. Open your Google Sheet and share it with the service account email
   (found inside the JSON as "client_email")
"""

import json, sys
from pathlib import Path


def setup_sheets():
    cfg_path = Path("config/config.json")
    if not cfg_path.exists():
        print("ERROR: config/config.json not found.")
        sys.exit(1)

    with open(cfg_path) as f:
        cfg = json.load(f)

    sa_path = cfg.get("google_service_account_path", "config/google_service_account.json")
    sheet_name = cfg.get("google_sheet_name", "Job Applications Bot")

    if not Path(sa_path).exists():
        print(f"ERROR: Service account file not found at {sa_path}")
        print("Follow the instructions in this file to create one.")
        sys.exit(1)

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(sa_path, scopes=scopes)
        gc = gspread.authorize(creds)

        # Try to open the sheet
        try:
            sh = gc.open(sheet_name)
            print(f"SUCCESS: Connected to existing sheet '{sheet_name}'")
        except gspread.SpreadsheetNotFound:
            # Create it
            sh = gc.create(sheet_name)
            print(f"Created new sheet: '{sheet_name}'")
            sh.share(None, perm_type="anyone", role="writer")  # optional: make public

        ws = sh.sheet1
        # Write headers
        if not ws.row_values(1):
            ws.append_row([
                "Date Applied", "Job Title", "Company", "Location",
                "Source", "Match Score", "Match Reason", "Status",
                "Salary", "URL",
            ])
            print("Header row written to sheet.")

        print(f"\nSheet URL: https://docs.google.com/spreadsheets/d/{sh.id}")
        print("\nSetup complete! Google Sheets is ready.")

    except ImportError:
        print("ERROR: gspread not installed. Run: pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    setup_sheets()
