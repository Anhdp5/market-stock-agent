# ZaloPay Stock Intelligence Agent — Setup Guide

## What This Does

Every trading day at **08:00 AM Vietnam time**, the agent automatically:
1. Pulls HOSE market data (volume, transactions, buy/sell) from CafeF via `vnstock`
2. Reads your Outlook emails from `metabase@mail.dnse.com.vn` (DNSE Metabase reports)
3. Extracts all 5 ZLP metrics from email attachments or HTML tables
4. Stores everything in a local SQLite database
5. Runs consulting-style analytics (DoD, WoW, 7-day trend, benchmarking)
6. Generates a formatted HTML executive report
7. Emails the report to `anhdp5@vng.com.vn`

---

## Step 1 — Install Dependencies

Double-click `setup.bat`, or run manually:

```bash
pip install -r requirements.txt
pip install vnstock3
```

---

## Step 2 — Configure Credentials

Copy `.env.template` to `.env` and fill in:

```env
# Azure AD app (for reading your Outlook mailbox)
AZURE_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_SECRET=your-client-secret

# VNG/Office 365 SMTP (for sending the daily report)
SMTP_USER=anhdp5@vng.com.vn
SMTP_PASSWORD=your-email-password-or-app-password
```

### How to get Azure AD credentials

1. Go to [portal.azure.com](https://portal.azure.com) → **Azure Active Directory** → **App registrations** → **New registration**
2. Name it `ZaloPay Intelligence Agent`, click Register
3. Note the **Application (client) ID** and **Directory (tenant) ID**
4. Go to **Certificates & secrets** → **New client secret** → copy the value
5. Go to **API permissions** → **Add a permission** → **Microsoft Graph** → **Application permissions**
6. Add: `Mail.Read`, `Mail.Send` (if using Graph to send) → **Grant admin consent**

### SMTP notes

- For Office 365: host is `smtp.office365.com`, port `587`
- If VNG uses a custom mail server, update `SMTP_HOST` and `SMTP_PORT` in `.env`
- If your account requires an **App Password** (MFA enabled), generate one at [myaccount.microsoft.com](https://myaccount.microsoft.com)

---

## Step 3 — Test the Pipeline

```bash
# Dry run — runs full pipeline, saves report, NO email sent
python main.py --test

# Check the saved report
open reports/report_YYYY-MM-DD.html
```

If the test succeeds, you'll see:
```
PIPELINE COMPLETE — 2026-06-13
Report saved to: reports/report_2026-06-13.html
```

---

## Step 4 — Send a Real Report

```bash
python main.py --once
```

This runs the full pipeline and sends the email immediately.

---

## Step 5 — Start the Daily Scheduler

```bash
python main.py
```

This starts a background process that runs at **08:00 AM** every trading day.

### Run as a Windows background service (recommended)

Create a Windows Task Scheduler entry:

1. Open **Task Scheduler** → **Create Basic Task**
2. Name: `ZaloPay Intelligence Agent`
3. Trigger: **Daily** at `07:55 AM`
4. Action: **Start a program**
   - Program: `python`
   - Arguments: `main.py --once`
   - Start in: `C:\Users\VNG\Claude\Projects\Market-stock-agent`
5. Check **Run whether user is logged on or not**

This way Windows handles the scheduling and the script just runs once per day.

---

## Project Structure

```
Market-stock-agent/
├── main.py                          # Entry point
├── config.py                        # Central config (reads .env)
├── requirements.txt
├── setup.bat
├── .env.template                    # Copy to .env and fill in
│
├── collector/
│   ├── market_scraper/
│   │   └── cafef_scraper.py         # HOSE market data (vnstock + CafeF)
│   └── email_ingestion/
│       ├── graph_client.py          # Microsoft Graph API client
│       └── email_parser.py          # Extract ZLP metrics from emails
│
├── data_processor/
│   ├── normalizer.py                # Merge to unified daily table
│   └── db_manager.py                # SQLite read/write
│
├── analytics_engine/
│   ├── calculator.py                # DoD / WoW / 7d avg / trend
│   └── benchmarker.py              # Market vs ZaloPay gap analysis
│
├── insight_generator/
│   └── insights.py                  # Consulting-style insights + actions
│
├── report_writer/
│   └── report_builder.py           # HTML + plain-text report
│
├── scheduler/
│   ├── mailer.py                    # SMTP email sender
│   └── main_scheduler.py           # Full pipeline orchestrator
│
├── data/
│   └── market_intelligence.db      # SQLite database (auto-created)
├── reports/                         # Saved HTML reports (auto-created)
└── logs/
    └── agent.log                    # Pipeline logs (auto-created)
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `vnstock3 not installed` | Run `pip install vnstock3` |
| `Azure credentials missing` | Check `.env` has all three `AZURE_*` keys |
| `SMTP authentication failed` | Use an App Password if MFA is enabled |
| `No data extracted from email` | Check email subject matches the configured patterns in `config.py` |
| `Empty DataFrame` after analytics | Confirm emails from `metabase@mail.dnse.com.vn` exist in the last 35 days |
| Graph API `403 Forbidden` | Ensure `Mail.Read` permission has **admin consent** granted in Azure portal |

---

## Email Metrics Mapping

| Email Subject (contains) | Internal Key | Description |
|---|---|---|
| "Số tài khoản mở thành công" | `ZLPNewAccount` | New accounts opened (success) |
| "Số lệnh khớp qua kênh Zalo" | `ZLPTradingTransaction` | Matched orders via ZaloPay |
| "GTGD qua kênh Zalo" | `ZLPTradingVolume` | Trading value via ZaloPay |
| "Số KH active theo tháng" | `ZLPActiveUsers` | Monthly active users |
| "Số lượng lệnh khớp theo các nhóm GTGD" | `ZLPTransactionbyusersegment` | Orders by GTGD segment |
