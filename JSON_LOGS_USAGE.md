# JSON Logs Browser - Usage Guide

## Overview
The enhanced web_machine_viewer now includes a comprehensive JSON log browser that supports:
1. **Real-time log streaming** (refreshes every 3 seconds)
2. **Time-based log search** (search by date/time range)
3. **Multi-directory support** (searches both legacy and current log locations)

---

## Features

### 📂 Load Available Logs
**Location:** Dashboard → "JSON Log Browser - Real-time & Time-based Search"

1. Click **"Load Available Logs"** button
2. Script scans both directories:
   - `/opt/go-ble-orchestrator/logs/json_logs`
   - `/opt/go-ble-orchestrator/json_logs` (legacy versions)
3. Display all `.log` files from both locations in a grid

---

### 🔴 Real-time Log Streaming
**Automatically displays last 100 lines, refreshing every 3 seconds**

#### How to use:
1. Click any log file button to start streaming
2. File name appears at top: `Real-time: <location>/<filename>`
3. Click **"⏸️ Stop Real-time"** to pause OR **"▶️ Start Real-time (3s)"** to resume
4. Status indicator:
   - 🟢 Green = actively streaming
   - 🔴 Red = stopped

#### What you see:
```
📊 Fetched 100 lines at 15:42:30

[01/04/2025 15:42:30] {"battery":66,"deviceType":"FrontierX2(V1)",...}
[01/04/2025 15:42:29] {"battery":67,"deviceType":"FrontierX2(V1)",...}
...
```

Each line shows:
- Timestamp (from `timestamp1` field converted to readable format)
- Full JSON record

---

### 🕐 Time-based Log Search
**Search for log entries within a specific date/time range**

#### Input Format:
```
From:  dd/mm/yyyy hh:mm:ss  (e.g., 01/04/2025 10:30:00)
To:    dd/mm/yyyy hh:mm:ss  (e.g., 01/04/2025 11:30:00)
```

#### Steps:
1. Select a log file from **"Select Log File"** dropdown
2. Enter **From** time in format: `dd/mm/yyyy hh:mm:ss`
3. Enter **To** time in format: `dd/mm/yyyy hh:mm:ss`
4. *Optional:* Use quick buttons instead:
   - **"Last 15 min"** - searches last 15 minutes
   - **"Last 1 hour"** - searches last 1 hour
   - **"Last 6 hours"** - searches last 6 hours
5. Click **"🔍 Search Logs"**
6. Results appear below

#### What happens:
- Script converts times to epoch seconds
- Backend searches JSON file for `timestamp1` within range
- Returns matching records (max 1000)
- Shows count: **(N records found)**

#### View Results:
- **Pretty-print JSON**: Check the box to format JSON nicely with indentation
- **Raw format**: Uncheck to see one JSON object per line

---

### ⏱️ Epoch Preview
As you enter times, the interface shows the converted epoch values:

```
📅 From: 01/04/2025 10:30:00
📅 To:   01/04/2025 11:30:00
─────────────────────────────────
Epoch range: 1775039400 → 1775043000 (seconds)
```

---

## Example Scenarios

### Scenario 1: Monitor Device in Real-time
1. Load logs → See available devices
2. Click `device-name_1.log`
3. Click **"▶️ Start Real-time (3s)"**
4. Watch log entries stream in automatically every 3 seconds
5. Stop when done

### Scenario 2: Find All ECG Data for a Time Window
1. Load logs → see all files
2. Select `FrontierX2_ECG.log` from dropdown
3. Enter:
   - From: `01/04/2025 14:00:00`
   - To: `01/04/2025 14:30:00`
4. Click **"🔍 Search Logs"**
5. Get all ECG records from 2:00 PM to 2:30 PM
6. Check "Pretty-print JSON" to view formatted

### Scenario 3: Last Hour of Activity
1. Load logs
2. Select log from dropdown
3. Click **"Last 1 hour"** button
4. Times auto-fill with: now - 1 hour to now
5. Click **"🔍 Search Logs"**
6. See all records from last 60 minutes

---

## Troubleshooting

### "SSH session not found" error
- You must be logged in to a machine first
- Go back to Machines page and login via SSH

### No logs found in directories
- Machine might be running older version
- Script searches both `/logs/json_logs` and `/json_logs` automatically
- Check that directories exist and contain `.log` files

### Search returns 0 records
- Check date/time format: must be `dd/mm/yyyy hh:mm:ss`
- Check time range is valid (From < To)
- The time range might be before any logs were created

### Real-time stream shows "Waiting to start"
- Click a log file button first to select it
- Then toggle real-time on

---

## Technical Details

### JSON Log Structure
```json
{
  "timestamp1": 1775050562,        // Epoch seconds (searched)
  "timestamp": 1775050562057,      // Epoch milliseconds
  "battery": 66,
  "deviceType": "FrontierX2(V1)",
  "heartrate": 77,
  "data": [...],
  "rhythmType": "NORMAL_SINUS_RHYTHM",
  ...
}
```

### Real-time Refresh
- Fetches last 100 lines from log file
- Polls every **3 seconds** automatically
- Shows fetch timestamp at top: `📊 Fetched N lines at HH:MM:SS`

### Time Range Search
- Backend converts `dd/mm/yyyy hh:mm:ss` to epoch seconds
- Uses grep/awk to find matching `timestamp1` values
- Matches any `timestamp1` where: `from_epoch ≤ timestamp1 ≤ to_epoch`
- Returns up to 1000 matching records

---

## Tips

1. **Pretty-print is slow for large results** - If searching returns 1000 records, pretty-printing takes time. Try shorter time ranges.

2. **Real-time can fill up** - After 30 minutes of real-time streaming, pre-100 lines visible. Restart for fresh view.

3. **Multiple devices** - If machine has many device log files, they'll all show up. Select the specific device you want.

4. **Time zones** - They're always in your **local time zone**. System converts to epoch using local timezone.

5. **Legacy versions** - Older orchestrator versions stored logs in `/json_logs`. Script checks both!
