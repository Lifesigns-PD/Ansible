# Semaphore Integration Guide - Orchestrator Dashboard

Complete setup guide to integrate Orchestrator machine discovery, monitoring, and management into Semaphore UI.

## 📋 Prerequisites

- ✅ Semaphore running in Docker at `/home/varun/` (already confirmed)
- ✅ Tailscale API key (`TAILSCALE_API_KEY`)
- ✅ Tailscale tenant name (`TAILSCALE_TENANT_NAME`)
- ✅ Linux credentials (`LINUX_USER`, `LINUX_PASS`)
- ✅ Ansible installed on Semaphore host

## 🔧 Setup Steps

### Step 1: Configure Semaphore Credentials

In **Semaphore UI → Settings → Credentials**, create the following:

#### 1.1 Tailscale API Key
- **Type**: Key/Secret
- **Name**: `Tailscale-API-Key`
- **Secret**: `<your-TAILSCALE_API_KEY>`
- **Environment**: `TAILSCALE_API_KEY`

#### 1.2 Tailscale Tenant Name
- **Type**: Key/Secret
- **Name**: `Tailscale-Tenant`
- **Secret**: `<your-TAILSCALE_TENANT_NAME>`
- **Environment**: `TAILSCALE_TENANT_NAME`

#### 1.3 Linux Credentials
- **Type**: Login
- **Name**: `Linux-SSH-Creds`
- **Username**: `{{ LINUX_USER }}`
- **Password**: `{{ LINUX_PASS }}`

### Step 2: Add Dynamic Inventory

1. Go to **Semaphore UI → Project → Inventories**
2. Click **New Inventory**
3. **Name**: `Tailscale-Devices`
4. **Type**: `Inventory Plugin`
5. **Inventory Plugin**: Python Script (Custom)
6. **Inventory Contents**: Copy from `inventory/tailscale_dynamic_inventory.py`

Semaphore will auto-execute this script before each playbook run, discovering all Tailnet devices dynamically.

### Step 3: Create Environment Variables

1. Go to **Semaphore UI → Project → Environment Variables**
2. Add for each variable:

```yaml
TAILSCALE_API_KEY: ${{ TAILSCALE_API_KEY }}
TAILSCALE_TENANT_NAME: ${{ TAILSCALE_TENANT_NAME }}
LINUX_USER: ubuntu
LINUX_PASS: ${{ LINUX_PASS }}
ANSIBLE_HOST_KEY_CHECKING: False
ANSIBLE_PYTHON_INTERPRETER: /usr/bin/python3
```

### Step 4: Create Task Templates

Create the following templates in **Semaphore UI → Project → Templates**:

#### 4.1 Dashboard Discovery Template
- **Name**: `Orchestrator-Dashboard`
- **Playbook**: `playbooks/Dashboard-Orchestrator.yml`
- **Inventory**: `Tailscale-Devices`
- **Environment**: Use variables created above
- **Credentials**: `Linux-SSH-Creds`
- **Options**: 
  - ✅ Use Web Hook
  - ✅ Ask at launch for inventory hosts
  - Extra variables: (leave blank - auto-discovered)

**Usage**: Run this template to discover all machines, get their status, logs, and system metrics.

#### 4.2 Health Monitor Template
- **Name**: `Monitor-Machine-Health`
- **Playbook**: `playbooks/Monitor-Health.yml`
- **Inventory**: `Tailscale-Devices`
- **Environment**: Same as above
- **Credentials**: `Linux-SSH-Creds`
- **Variables** (ask at launch):
  ```yaml
  target_hosts: "all"   # or specific host
  ```

**Usage**: Run on specific or all machines to get real-time health metrics.

#### 4.3 JSON Log Viewer Template
- **Name**: `View-JSON-Logs`
- **Playbook**: `playbooks/LogViewer-JSON.yml`
- **Inventory**: `Tailscale-Devices`
- **Environment**: Same as above
- **Variables** (ask at launch):
  ```yaml
  log_file: app.log          # or any log file
  start_date: "2024-04-01"   # dd-mm-yyyy
  start_time: "14:00:00"     # hh:mm:ss
  end_date: "2024-04-03"
  end_time: "18:00:00"
  ```

**Usage**: Search logs by time range, view in real-time, export results.

#### 4.4 Log Streaming Template  
- **Name**: `Stream-Log-File`
- **Playbook**: `playbooks/LogViewer-JSON.yml` (second play)
- **Inventory**: `Tailscale-Devices`
- **Variables** (ask at launch):
  ```yaml
  log_file_name: app.log
  tail_lines: 100
  ```

**Usage**: Stream any log file in real-time.

### Step 5: Update Semaphore Docker Environment

Mount the Ansible directory and set credentials:

```bash
cd /home/varun/
# Edit docker-compose.yml or your Semaphore startup to:
# 1. Mount your Ansible directory:
#    volumes:
#      - /path/to/ansible:/ansible:ro

# 2. Set environment variables:
#    environment:
#      - TAILSCALE_API_KEY=<your-key>
#      - TAILSCALE_TENANT_NAME=<your-tenant>
```

### Step 6: Test the Integration

1. In Semaphore UI, go to **Project → Templates**
2. Select `Orchestrator-Dashboard`
3. Click **Run Template**
4. Wait for execution (2-3 minutes first time)
5. Check results:
   - Task output shows all machines, logs, services
   - Reports saved to `/tmp/orchestrator_dashboard_*.json`

## 📊 Dashboard Features Available in Semaphore

### 🌐 Network Discovery
- **What**: Auto-discover all devices in Tailnet
- **Where**: View in `Dashboard-Orchestrator` template output
- **Frequency**: Every run (configurable via webhook)

### 📁 Log Management
- **What**: Search logs by time range, stream logs, view file lists
- **Where**: Use `View-JSON-Logs` and `Stream-Log-File` templates
- **Locations**: Automatically checks both current and legacy paths

### 🔍 Real-Time Monitoring
- **What**: CPU, memory, disk, network metrics per machine
- **Where**: Use `Monitor-Machine-Health` template
- **Data**: Saved as JSON reports, viewable in Semaphore

### 🔧 Service Management
- **What**: Check orchestrator, SSH, Tailscale status
- **Where**: Included in all templates, shown in output

### 📊 Health Alerts
- **What**: Failed SSH attempts, system errors, resource warnings
- **Where**: `Monitor-Machine-Health` output

## 🔄 Automation with Webhooks

Setup automatic runs for dashboard discovery:

1. **Semaphore UI → Project → Templates → Orchestrator-Dashboard**
2. Click **Edit**
3. **Webhook**: Enable
4. Copy webhook URL
5. **Setup cron job** (on Semaphore host):
   ```bash
   # Every 5 minutes
   */5 * * * * curl -X POST "https://semaphore.example.com/api/project/1/templates/1/run" \
     -H "Authorization: Bearer YOUR_API_TOKEN"
   ```

Or use Semaphore's built-in scheduler (Settings → Scheduler).

## 📈 Scaling to Multiple Projects

Each project can have:
- Own Tailnet credentials
- Own machine list
- Own log directories
- Isolated templates

Just create new **Project** in Semaphore and repeat Steps 1-4.

## 🐛 Troubleshooting

### Inventory Not Discovering Machines
```bash
# Test inventory script locally
/ansible/inventory/tailscale_dynamic_inventory.py --list
# Should output JSON with all devices
```

### SSH Connections Failing
1. Verify credentials in Semaphore
2. Test manually:
   ```bash
   ssh -i <keyfile> ubuntu@<tailscale-ip>
   ```
3. Check `ANSIBLE_HOST_KEY_CHECKING=False` is set

### Logs Not Found
- Template checks both:
  - `/opt/go-ble-orchestrator/logs/`
  - `/opt/go-ble-orchestrator/`
- Check both locations exist on target

### Webhook Not Firing
1. Verify API token has correct permissions
2. Check logs: `docker logs semaphore`
3. Test webhook manually with curl

## 🎯 Next Steps

1. ✅ Setup credentials (Step 1)
2. ✅ Add dynamic inventory (Step 2)
3. ✅ Create environment variables (Step 3)
4. ✅ Create task templates (Step 4)
5. ✅ Test templates (Step 6)
6. 🔄 Setup webhooks for auto-runs (Optional)
7. 📊 Create dashboard with template grouping (Optional)

## 📚 File Structure

```
ansible/
├── inventory/
│   └── tailscale_dynamic_inventory.py    # ← NEW: Semaphore dynamic inventory
├── playbooks/
│   ├── Dashboard-Orchestrator.yml        # ← NEW: All-in-one discovery
│   ├── LogViewer-JSON.yml                # ← NEW: Log search & stream
│   ├── Monitor-Health.yml                # ← NEW: System metrics
│   ├── configure.yml
│   ├── deploy.yml
│   └── rollback.yml
└── roles/
    ├── mqtt/
    ├── orchestrator/
    └── prerequisites/
```

## 🔐 Security Notes

- Store credentials in Semaphore vault, not in files
- Use SSH keys instead of passwords where possible
- Limit API token permissions to minimum required
- Rotate API keys regularly
- Audit template access and runs

## 📞 Support

- Check Semaphore logs: `docker logs semaphore`
- Install verbose logging in templates by adding: `-vvv` flag
- Check Ansible documentation for error codes
- Verify network connectivity to all Tailscale IPs
