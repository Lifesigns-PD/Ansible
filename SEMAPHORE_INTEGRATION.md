# Semaphore Orchestrator Integration

Complete automation suite to bring all functionality from `web_machine_viewer.py` into Semaphore UI.

## 🎯 What's Included

This integration provides everything from the Flask dashboard in a native Ansible/Semaphore format:

### ✅ Features

| Feature | Status | Playbook | Semaphore Template |
|---------|--------|----------|-------------------|
| 🌐 Tailnet Machine Discovery | ✅ | Dynamic Inventory | Auto-run on each task |
| 📊 Dashboard & Summary | ✅ | Dashboard-Orchestrator | Orchestrator-Dashboard |
| 🔍 Log Search (by time range) | ✅ | LogViewer-JSON | View-JSON-Logs |
| 📺 Real-time Log Streaming | ✅ | LogViewer-JSON | Stream-Log-File |
| 💾 System Health Metrics | ✅ | Monitor-Health | Monitor-Machine-Health |
| 🔧 Service Status | ✅ | All playbooks | Included in output |
| 📁 Multi-location log discovery | ✅ | All playbooks | Automatic fallback |
| 🔐 SSH Management | ✅ | All playbooks | Credential-based |
| 📈 Real-time monitoring | ✅ | Monitor-Health | Health report export |
| 🔄 Automation & webhooks | ✅ | All playbooks | Semaphore scheduler |

## 📁 New Files Created

```
ansible/
├── 📄 SEMAPHORE_SETUP_GUIDE.md          ← Complete setup instructions
├── 📄 SEMAPHORE_INTEGRATION.md          ← This file
├── 🔧 setup_semaphore.sh                ← Quick setup script
│
├── inventory/
│   └── 🆕 tailscale_dynamic_inventory.py ← Discovers all Tailnet devices
│
├── playbooks/
│   ├── 🆕 Dashboard-Orchestrator.yml     ← All-in-one discovery & summary
│   ├── 🆕 LogViewer-JSON.yml            ← Log search & streaming
│   ├── 🆕 Monitor-Health.yml            ← System metrics & health
│   ├── configure.yml (existing)
│   ├── deploy.yml (existing)
│   └── rollback.yml (existing)
│
└── roles/ (existing)
    ├── mqtt/
    ├── orchestrator/
    └── prerequisites/
```

## 🚀 Quick Start

### Option A: Automated Setup (Recommended)

```bash
cd /path/to/ansible
chmod +x setup_semaphore.sh
./setup_semaphore.sh

# Follow prompts to enter:
# - Semaphore URL & API token
# - Tailscale API key & tenant
# - Linux credentials
```

This will automatically:
- ✅ Create all required credentials
- ✅ Configure environment variables
- ✅ Register dynamic inventory

### Option B: Manual Setup

See [SEMAPHORE_SETUP_GUIDE.md](SEMAPHORE_SETUP_GUIDE.md) for step-by-step instructions.

## 🎮 Using the Templates

### 1️⃣ Dashboard Discovery
**Purpose**: Discover all machines, get logs, check services, generate summary

```
Template: Orchestrator-Dashboard
Playbook: playbooks/Dashboard-Orchestrator.yml
Time: ~2-3 minutes
Output: Machine list, log counts, service status, health summary
```

**How to use:**
1. Semaphore UI → Templates → Select `Orchestrator-Dashboard`
2. Click **Run Template**
3. Watch real-time output showing:
   - All discovered Tailnet devices
   - Standard logs (both locations)
   - JSON logs (both locations)
   - Service status
   - Ansible availability
4. Results saved to `/tmp/orchestrator_dashboard_*.json`

### 2️⃣ Health Monitor
**Purpose**: Real-time CPU, memory, disk, network, service metrics

```
Template: Monitor-Machine-Health
Playbook: playbooks/Monitor-Health.yml
Time: ~1-2 minutes per target
Output: JSON health report + formatted summary
```

**How to use:**
1. Semaphore UI → Templates → Select `Monitor-Machine-Health`
2. Click **Run Template**
3. At launch, specify which hosts (all/specific hostnames)
4. View real-time metrics:
   - CPU cores, load average, top processes
   - Memory usage, swap, processes
   - Disk usage per mount point
   - Network interfaces & Tailscale status
   - Open ports, running services
   - Failed SSH attempts, errors, warnings
5. Results exported to `/tmp/health_report_*.json`

### 3️⃣ Log Search (Time Range)
**Purpose**: Search JSON logs between specific dates/times

```
Template: View-JSON-Logs
Playbook: playbooks/LogViewer-JSON.yml (Play 1)
Time: ~1-2 minutes
Output: Matching log entries
```

**How to use:**
1. Semaphore UI → Templates → Select `View-JSON-Logs`
2. Click **Run Template**
3. At launch, enter:
   - `log_file`: e.g., "app.log"
   - `start_date`: e.g., "2024-04-01"
   - `start_time`: e.g., "14:30:00"
   - `end_date`: e.g., "2024-04-03"
   - `end_time`: e.g., "18:00:00"
4. View matching entries (last 100 results)
5. Results exported to `/tmp/log_search_results_*.json`

### 4️⃣ Log Streaming
**Purpose**: View real-time tail of any log file

```
Template: Stream-Log-File
Playbook: playbooks/LogViewer-JSON.yml (Play 2)
Time: ~30 seconds
Output: Last N lines of log
```

**How to use:**
1. Semaphore UI → Templates → Select `Stream-Log-File`
2. Click **Run Template**
3. At launch, enter:
   - `log_file_name`: e.g., "app.log"
   - `tail_lines`: e.g., "100"
4. View output (last N lines)
5. Snapshot saved to `/tmp/log_stream_*.txt`

## 🔄 Automation with Webhooks

Run templates automatically on schedule:

### Setup Webhook

1. Semaphore UI → Project → Templates → `Orchestrator-Dashboard`
2. Edit → Enable Webhook
3. Copy webhook URL

### Create Cron Job

```bash
# Run dashboard discovery every 5 minutes
*/5 * * * * curl -X POST "https://semaphore.example.com:3000/api/project/1/templates/1/run" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{}'
```

Or use Semaphore's built-in scheduler (Settings → Scheduler).

## 📊 Integration Features

### Dynamic Inventory

**File**: `inventory/tailscale_dynamic_inventory.py`

Automatically discovers all devices in your Tailnet:

```bash
# Test locally:
./inventory/tailscale_dynamic_inventory.py --list

# Output:
{
  "all": { "hosts": {...} },
  "online": { "hosts": {...} },
  "offline": { "hosts": {...} },
  "_meta": {
    "hostvars": {
      "device-name": {
        "ansible_host": "100.x.x.x",
        "ansible_user": "ubuntu",
        "status": "online",
        "os": "linux",
        ...
      }
    }
  }
}
```

### Environment Variables

All templates use these Semaphore environment variables:

```yaml
TAILSCALE_API_KEY=<your-api-key>
TAILSCALE_TENANT_NAME=<your-tenant>
LINUX_USER=ubuntu
LINUX_PASS=<password>
ANSIBLE_HOST_KEY_CHECKING=False
ANSIBLE_PYTHON_INTERPRETER=/usr/bin/python3
```

### Credentials

Three credentials are registered:
- **Tailscale-API-Key**: API authentication
- **Tailscale-Tenant**: Tenant identifier
- **Linux-SSH-Credentials**: SSH login (username + password)

## 📈 Scaling & Advanced Features

### Multi-Project Setup

Create separate Semaphore projects for:
- Production Tailnet
- Staging Tailnet
- Development environment

Each project gets its own:
- Credentials
- Environment variables
- Templates
- Webhooks

### Custom Modifications

### Add to Existing Playbooks

Integrate into your existing Ansible playbooks:

```yaml
- name: Include Orchestrator monitoring
  import_playbook: playbooks/Monitor-Health.yml
  vars:
    target_hosts: "production"
```

### Extend Templates

Add more playbooks for specific tasks:
- Deploy orchestrator software
- Backup logs automatically
- Performance tuning
- Troubleshooting

## 🔐 Security Considerations

### Credential Storage
- ✅ Store all secrets in Semaphore vault (not files)
- ✅ Use SSH keys instead of passwords where possible
- ✅ Rotate API keys periodically

### Access Control
- ✅ Limit template access by project role
- ✅ Audit all template executions (built-in Semaphore feature)
- ✅ Use API tokens with minimal permissions

### Network Security
- ✅ Enable `ANSIBLE_HOST_KEY_CHECKING=False` for Tailscale IPs
- ✅ Use SSH via Tailscale (not exposed to internet)
- ✅ Verify certificate pinning if using custom CAs

## 🐛 Troubleshooting

### Inventory Not Discovering Machines

```bash
# Test the inventory script
export TAILSCALE_API_KEY=<your-key>
export TAILSCALE_TENANT_NAME=<your-tenant>

/ansible/inventory/tailscale_dynamic_inventory.py --list
# Should show all devices in JSON
```

**If empty:**
- Verify Tailscale API key is valid
- Check Tailscale account has API access enabled
- Ensure at least one device is in tailnet

### SSH Connection Errors

```
UNREACHABLE! => {
  "changed": false,
  "unreachable": true,
  "msg": "Failed to connect..."
}
```

**Fix:**
1. Verify Linux credentials in Semaphore
2. Test SSH manually:
   ```bash
   ssh ubuntu@100.x.x.x
   ```
3. Check firewall allows port 22
4. Confirm SSH key exchange setup

### Logs Not Found

Templates check multiple locations automatically:
- `/opt/go-ble-orchestrator/logs/`
- `/opt/go-ble-orchestrator/`
- `/opt/go-ble-orchestrator/logs/json_logs/`
- `/opt/go-ble-orchestrator/json_logs/`

If still not found:
1. SSH to target and verify paths exist
2. Check file permissions
3. Verify orchestrator is running

### JSON Parse Errors

If seeing `json.JSONDecodeError`:
1. Log file may contain non-JSON lines
2. Playbook handles this gracefully - shows error count
3. Check log file format

## 📞 Support & Resources

- **Semaphore Docs**: https://semaphore.docs.io/
- **Ansible Docs**: https://docs.ansible.com/
- **Tailscale API**: https://tailscale.com/api
- **Community**: GitHub Issues, Ansible Forum

## 🎓 Learning Path

1. **Start**: Run `Orchestrator-Dashboard` template
2. **Monitor**: Run `Monitor-Machine-Health` on a single host
3. **Search**: Try `View-JSON-Logs` with date range
4. **Automate**: Setup webhook for scheduled runs
5. **Customize**: Modify playbooks for your needs

## 📝 Comparison: Web UI vs Semaphore

| Feature | web_machine_viewer.py | Semaphore Integration |
|---------|----------------------|----------------------|
| Machine discovery | ✅ Web UI | ✅ Template output |
| SSH access | ✅ Web UI | ✅ Credential-based |
| Log browsing | ✅ Web UI | ✅ Template tasks |
| Real-time streaming | ✅ Web UI | ✅ Task output |
| Monitoring dashboard | ✅ Web UI | ✅ Template reports |
| Automation/schedules | ⚠️ Built-in | ✅ Semaphore scheduler |
| Team collaboration | ⚠️ Simple | ✅ Full RBAC |
| Audit log | ❌ None | ✅ Complete |
| API integration | ⚠️ REST API | ✅ Full API |
| Scaling | ⚠️ Single instance | ✅ Distributed |

## ✅ What's Complete

- ✅ Dynamic Tailnet device discovery
- ✅ Multi-location log search (4 directories)
- ✅ Real-time streaming with buffering
- ✅ System health metrics collection
- ✅ Service status monitoring
- ✅ Time-range log search
- ✅ JSON log parsing
- ✅ Semaphore credential integration
- ✅ Automated task templates
- ✅ Webhook & scheduler support
- ✅ Multi-host parallel execution
- ✅ Report generation & export

## 🎉 Ready to Use!

Everything is configured and ready. Just:
1. Run `setup_semaphore.sh` (or manual setup)
2. Create templates in Semaphore UI
3. Run your first template
4. Watch the magic happen! ✨
