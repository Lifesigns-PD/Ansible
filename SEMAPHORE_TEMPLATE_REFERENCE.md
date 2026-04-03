# Semaphore Template Quick Reference Card

## 📋 Template List

### 1. Orchestrator-Dashboard
| Property | Value |
|----------|-------|
| **Playbook** | `playbooks/Dashboard-Orchestrator.yml` |
| **Inventory** | All (dynamic - auto-discovered) |
| **Time** | 2-3 minutes |
| **Purpose** | Complete system discovery & summary |
| **Best for** | Daily health checks, new setup |

**Output includes:**
- All Tailnet devices (online/offline)
- Log file count & locations
- Service status (Orchestrator, Ansible, etc.)
- Network ports
- Complete JSON report

**How to run:**
```
1. Templates → Orchestrator-Dashboard
2. Click "Run Template"
3. Check output (scroll down)
```

---

### 2. Monitor-Machine-Health
| Property | Value |
|----------|-------|
| **Playbook** | `playbooks/Monitor-Health.yml` |
| **Inventory** | Select at launch |
| **Time** | 1-2 minutes per host |
| **Purpose** | Real-time metrics & health check |
| **Best for** | Performance monitoring, troubleshooting |

**Output includes:**
- CPU: cores, model, load, top processes
- Memory: usage, swap, top processes
- Disk: usage per mount, warnings
- Network: interfaces, Tailscale status
- Services: ports, status, running services
- Health: SSH errors, system errors, warnings
- Complete JSON health report

**How to run:**
```
1. Templates → Monitor-Machine-Health
2. Click "Run Template"
3. Options:
   - Run on "all" hosts
   - Or specify hostname(s)
4. Check output
```

**Variable Format:**
```yaml
target_hosts: "all"           # all machines
target_hosts: "machine1"      # single machine
target_hosts: "m1,m2,m3"      # multiple
```

---

### 3. View-JSON-Logs
| Property | Value |
|----------|-------|
| **Playbook** | `playbooks/LogViewer-JSON.yml` (Play 1) |
| **Inventory** | Select at launch |
| **Time** | 1-2 minutes |
| **Purpose** | Search logs by date/time range |
| **Best for** | Finding specific events, debugging |

**Output includes:**
- Log file info (size, line count)
- All entries in time range
- JSON-formatted results
- Export to `/tmp/log_search_results_*.json`

**How to run:**
```
1. Templates → View-JSON-Logs
2. Click "Run Template"
3. Enter variables:
   log_file: "app.log"
   start_date: "2024-04-01"
   start_time: "14:30:00"
   end_date: "2024-04-03"
   end_time: "18:00:00"
4. Check results
```

**Variable Format:**
```yaml
log_file: "app.log"          # filename
start_date: "2024-04-01"     # YYYY-MM-DD
start_time: "14:30:00"       # HH:MM:SS (24hr)
end_date: "2024-04-01"
end_time: "15:00:00"
```

---

### 4. Stream-Log-File
| Property | Value |
|----------|-------|
| **Playbook** | `playbooks/LogViewer-JSON.yml` (Play 2) |
| **Inventory** | Select at launch |
| **Time** | 30 seconds |
| **Purpose** | View recent log entries |
| **Best for** | Quick status check, live monitoring |

**Output includes:**
- Last N lines of specified log
- Plain text format
- Text file export to `/tmp/log_stream_*.txt`

**How to run:**
```
1. Templates → Stream-Log-File
2. Click "Run Template"
3. Enter variables:
   log_file_name: "app.log"
   tail_lines: 50
4. View output immediately
```

**Variable Format:**
```yaml
log_file_name: "app.log"     # filename to tail
tail_lines: 50               # number of lines (default: 50)
```

**Common log files:**
```
app.log                      # Application log
orchestrator.log             # Orchestrator service
syslog                      # System log
/var/log/auth.log           # SSH/Auth log
```

---

## 🔧 Common Use Cases

### Daily System Check
1. Run: **Orchestrator-Dashboard**
2. Check: Device count, service status
3. Time: 2-3 min

### Monitor Single Machine
1. Run: **Monitor-Machine-Health**
2. Set target_hosts to specific hostname
3. Check: CPU, memory, disk
4. Time: 1-2 min

### Find Error in Logs
1. Run: **View-JSON-Logs**
2. Set: date range of incident
3. Enter: "app.log" as log_file
4. Check: results
5. Time: 1-2 min

### Quick Status Update
1. Run: **Stream-Log-File**
2. Set: log_file_name to "app.log"
3. Check: last 100 lines
4. Time: 30 sec

### Schedule Daily Discovery
1. Templates → **Orchestrator-Dashboard**
2. Edit → Webhook → Copy URL
3. Setup cron:
   ```bash
   0 9 * * * curl -X POST "...webhook-url..." 
   ```
4. Runs at 9 AM daily

---

## 🎯 Variable Quick Reference

### Date/Time Format
```
Date:  YYYY-MM-DD   (e.g., 2024-04-01)
Time:  HH:MM:SS     (e.g., 14:30:00, 24-hour format)
```

### Host Selection
```
all              → Run on all discovered hosts
hostname         → Single host by name
host1,host2      → Multiple hosts (comma-separated)
online           → Only online hosts (if supported)
offline          → Only offline hosts (if supported)
```

### Log Files
```
app.log              → Default application log
orchestrator.log     → Orchestrator service
syslog              → System messages
/var/log/auth.log   → SSH/authentication
```

### Paths Checked Automatically
```
/opt/go-ble-orchestrator/logs/          ← Current standard
/opt/go-ble-orchestrator/                ← Legacy standard
/opt/go-ble-orchestrator/logs/json_logs/ ← Current JSON
/opt/go-ble-orchestrator/json_logs/      ← Legacy JSON
```

---

## 🔍 Output Files

All templates save results locally:

```
Dashboard:
  → /tmp/orchestrator_dashboard_{{hostname}}.json
  → /tmp/orchestrator_dashboard_summary.json

Monitor:
  → /tmp/health_report_{{hostname}}.json

Logs:
  → /tmp/log_search_results_{{hostname}}_{{filename}}.json
  → /tmp/log_stream_{{hostname}}_{{filename}}.txt
```

Download from Semaphore task output or SSH to server:
```bash
# View results
cat /tmp/orchestrator_dashboard_summary.json

# Copy to local machine
scp user@server:/tmp/health_report_*.json .
```

---

## ⚙️ Advanced Options

### Run with Extra Variables
```
Extra Variables (JSON):
{
  "custom_log_dir": "/custom/path",
  "ansible_user": "admin",
  "tail_lines": 200
}
```

### Run on Specific Group
If inventory has groups (online/offline):
```
--limit online      # Only online hosts
--limit offline     # Only offline hosts
--limit "machine1"  # Single machine
```

### Dry Run (Check)
```
ansible-playbook ... --check   # Don't make changes
```

### Verbose Output
```
ansible-playbook ... -vvv   # Show detailed output
```

---

## 📚 Integration with Semaphore

### View Task History
```
Project → Tasks → Select task
Scroll to see:
- Start time, end time, duration
- User who ran it
- Status (success/failed)
- Complete output
- Errors/warnings
```

### Export Results
```
Task detail → Options menu → Export
- Export output as text
- Download JSON archive
- Share via webhook
```

### Webhook Integration
```
Get webhook URL:
  Template → Edit → Webhook → Copy

Trigger from:
  - CI/CD pipeline
  - Monitoring alert
  - Cron job
  - Custom script
```

---

## 🚨 Troubleshooting Quick Guide

### Template Won't Run
```
❌ "No hosts matched"
→ Check inventory is "Tailscale-Devices"
→ Verify API credentials are valid
→ Run dashboard first to discover hosts

❌ "SSH Connection refused"
→ Check Linux-SSH-Credentials
→ Verify target host is online
→ Test: ssh ubuntu@<ip>

❌ "File not found"
→ Logs auto-check 4 locations
→ View playbook output for details
→ SSH to target and verify path
```

### Slow Template Execution
```
⏱️ Taking too long?
→ Run "Stream-Log-File" instead (faster)
→ Use smaller date range in log search
→ Check target host network connectivity
→ SSH from Semaphore server:
   ssh ubuntu@<target-ip>
```

### Results Not Saved
```
📁 Can't find output files?
→ Check /tmp/ directory on Semaphore host
→ May need higher permissions
→ Download from task output instead
→ Export from Semaphore UI
```

---

## 💡 Pro Tips

1. **Save searches** - Note successful date ranges
2. **Favorite templates** - Mark most-used in Semaphore
3. **Set alerts** - Use Semaphore webhooks for failures
4. **Archive results** - Download weekly for compliance
5. **Automate daily** - Setup webhook for dashboard discovery
6. **Monitor trends** - Compare health reports over time
7. **Document** - Note hostnames and log file locations

---

## 📞 When to Use What

| Situation | Use This |
|-----------|----------|
| Daily check-in | Orchestrator-Dashboard |
| High CPU alert | Monitor-Machine-Health |
| Need error logs | View-JSON-Logs (time range) |
| Quick status | Stream-Log-File |
| New setup | Orchestrator-Dashboard |
| Performance issue | Monitor-Machine-Health |
| Debug specific event | View-JSON-Logs |
| Compliance audit | Orchestrator-Dashboard |
| Live monitoring | Stream-Log-File (repeat) |
| Trend analysis | Monitor-Machine-Health (daily) |

---

**Last Updated**: 2024-04-03  
**Version**: 1.0  
**Compatibility**: Semaphore 2.8+, Ansible 2.9+
