# Ansible Playbooks Execution & Systemd Deployment Guide

## Table of Contents
1. [How Playbooks Execute](#how-playbooks-execute)
2. [Systemd vs Docker Comparison](#systemd-vs-docker-comparison)
3. [Step-by-Step Playbook Workflow](#step-by-step-playbook-workflow)
4. [Service Management Deep Dive](#service-management-deep-dive)
5. [Real-World Execution Examples](#real-world-execution-examples)

---

## How Playbooks Execute

### Execution Flow Diagram

```
USER RUNS COMMAND (Your Machine - Control Node)
    │
    │ ansible-playbook playbooks/deploy.yml --ask-vault-pass
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│ Ansible Control Machine                                  │
│ 1. Read inventory/production.yml                         │
│ 2. Decrypt vault.yml (prompt for password)               │
│ 3. Load group_vars/orchestrator_servers/vars.yml         │
│ 4. Parse playbooks/deploy.yml                            │
└──────────────────────────────────┬───────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │ SSH Connection (per host)   │
                    ▼
        ┌───────────────────────────┐
        │ prod-orchestrator-01       │
        │ 10.0.1.100                │
        └───────────────────────────┘
                    ▲
        ┌───────────┴──────────┐
        │                      │
        ▼                      ▼
    Role: Prerequisites    Role: MQTT
    ├─ Task 1            ├─ Task 1
    ├─ Task 2            ├─ Task 2
    └─ Task 3            └─ Task 3
        │                    │
        ▼                    ▼
    Changes Applied     Changes Applied
    (Idempotent)        (Idempotent)
        │                    │
        └────────┬───────────┘
                 │
                 ▼
        Role: Orchestrator
        ├─ Copy binary
        ├─ Generate config
        ├─ Create systemd service
        └─ Start service
                 │
                 ▼
        Service Started (systemd)
                 │
                 ▼
        Playbook Completes
```

### Key Points

1. **Control Machine**: Your laptop/CI server running Ansible
2. **SSH Connection**: Ansible connects to each target via SSH
3. **Python Execution**: Ansible executes Python scripts on target (not Ansible Python, but invokes commands)
4. **Idempotent**: Each task checks before applying (doesn't re-do what's already done)
5. **Sequential by Default**: Tasks run one after another within a role

---

## Systemd vs Docker Comparison

### Docker Approach (What You Had Before)

```
┌─────────────────────────────────────────┐
│         Docker Container                │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │ Orchestrator Process            │   │
│  │ (PID 1 - Main process)          │   │
│  │ - Binary runs as PID 1          │   │
│  │ - Container crash = app crash   │   │
│  │ - No service restart logic      │   │
│  └─────────────────────────────────┘   │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │ Mosquitto Process               │   │
│  │ (PID 2)                         │   │
│  └─────────────────────────────────┘   │
│                                         │
│  Image: 200-300 MB                      │
│  Startup: 2-5 seconds                   │
│  Restart: Relies on Docker engine       │
│  Logging: Docker daemon                 │
│  Config: Mounted volumes                │
└─────────────────────────────────────────┘
      ↓
   docker-compose up -d
```

**Limitations:**
- ❌ Heavyweight (layers, image size)
- ❌ Not system-native
- ❌ Requires Docker daemon running
- ❌ Container restart ≠ service restart
- ❌ No integration with system monitoring

---

### Systemd Approach (New - Native Linux Service)

```
┌─────────────────────────────────────────────────────┐
│              Linux Kernel                           │
│  ┌─────────────────────────────────────────────┐   │
│  │ systemd (PID 1 - Init System)               │   │
│  │                                             │   │
│  │  ┌──────────────────────────────────────┐  │   │
│  │  │ Service: go-ble-orchestrator         │  │   │
│  │  │ ├─ Binary: /opt/orchestrator/bin/... │  │   │
│  │  │ ├─ User: orcservice:orcservice       │  │   │
│  │  │ ├─ State: active (running)           │  │   │
│  │  │ ├─ Restart: on-failure               │  │   │
│  │  │ ├─ PID: 1234 (managed by systemd)    │  │   │
│  │  │ └─ Logs: journalctl                  │  │   │
│  │  └──────────────────────────────────────┘  │   │
│  │                                             │   │
│  │  ┌──────────────────────────────────────┐  │   │
│  │  │ Service: mosquitto.service           │  │   │
│  │  │ ├─ Binary: /usr/sbin/mosquitto       │  │   │
│  │  │ ├─ User: mosquitto:mosquitto         │  │   │
│  │  │ ├─ State: active (running)           │  │   │
│  │  │ ├─ Restart: always                   │  │   │
│  │  │ ├─ PID: 5678 (managed by systemd)    │  │   │
│  │  │ └─ Logs: journalctl                  │  │   │
│  │  └──────────────────────────────────────┘  │   │
│  │                                             │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  ◄─ systemctl start/stop/restart ────────────────► │
│  ◄─ journalctl logs ───────────────────────────────► │
│  ◄─ systemd monitoring & auto-restart ──────────────► │
│                                                     │
└─────────────────────────────────────────────────────┘
      ↓
   systemctl start go-ble-orchestrator
```

**Advantages:**
- ✅ Lightweight (no container overhead)
- ✅ Native OS integration
- ✅ Automatic restart on crash
- ✅ System boot persistence
- ✅ Centralized logging (journalctl)
- ✅ Resource limits built-in
- ✅ Zero external dependencies
- ✅ Better performance (no container layer)

---

## Step-by-Step Playbook Workflow

### Phase 1: Preparation (Your Machine)

```
$ ansible-playbook playbooks/deploy.yml --ask-vault-pass
                    ↓
[Ansible parses: playbooks/deploy.yml]
                    ↓
┌─────────────────────────────────────────────┐
│ Pre-tasks:                                  │
│ ✓ Display deployment info                   │
│ ✓ Validate variables                        │
│ ✓ Assert binary_source_dir exists           │
└─────────────────────────────────────────────┘
                    ↓
[Ansible loads inventory: orchestrator_servers]
                    ↓
Found hosts:
  - prod-orchestrator-01 (10.0.1.100)
  - prod-orchestrator-02 (10.0.1.101)
```

### Phase 2: SSH Connection & Fact Gathering

```
For each host:
  ├─ SSH: ubuntu@10.0.1.100
  ├─ Authenticate: using private key ~/.ssh/id_rsa
  ├─ Execute: /usr/bin/python3 (gather facts)
  │   └─ Returns: OS, kernel, CPU, RAM, packages, etc.
  └─ Cached for reuse (speeds up future runs)
```

### Phase 3: Role Execution (Prerequisites Role)

```
ROLE: prerequisites
├────────────────────────────────────────────
│
├─ TASK 1: Update system packages
│   └─ Command: apt-get update
│   └─ Executed as: root (become: yes)
│   └─ Result: Package list refreshed
│
├─ TASK 2: Install packages
│   └─ Command: apt-get install curl wget systemd ca-certificates ...
│   └─ Executed as: root
│   └─ Result: 8 packages installed
│
├─ TASK 3: Create app user
│   └─ Command: useradd orcservice (if not exists)
│   └─ Executed as: root
│   └─ Result: User orcservice:orcservice created
│
├─ TASK 4: Create directories
│   └─ Creates:
│       ├─ /opt/orchestrator (owner: orcservice)
│       ├─ /opt/orchestrator/bin
│       ├─ /opt/orchestrator/config
│       ├─ /opt/orchestrator/data
│       └─ /opt/orchestrator/logs
│   └─ Permissions: 755 (rwxr-xr-x)
│
└─ TASK 5: Verify permissions
    └─ Ensures all directories are owned by orcservice:orcservice
    └─ (recursive check)
```

**Result After Prerequisites:**
```
Server filesystem state:
✓ All packages present
✓ orcservice user exists
✓ /opt/orchestrator directory structure ready
✓ Permissions correct for app to run
```

---

### Phase 4: Role Execution (MQTT Role)

```
ROLE: mqtt
├────────────────────────────────────────────
│
├─ TASK 1: Install Mosquitto
│   └─ Command: apt-get install mosquitto
│   └─ Binary installed to: /usr/sbin/mosquitto
│   └─ Config directory: /etc/mosquitto/
│   └─ Data directory: /var/lib/mosquitto/
│
├─ TASK 2: Create config directory
│   └─ Creates: /etc/mosquitto/conf.d
│   └─ Owner: mosquitto:mosquitto
│
├─ TASK 3: Deploy mosquitto.conf
│   └─ Template: roles/mqtt/templates/mosquitto.conf.j2
│   └─ Generates from variables (j2 = Jinja2)
│   └─ Output file: /etc/mosquitto/conf.d/orchestrator.conf
│   └─ Contents:
│         listener 1883
│         allow_anonymous true
│         persistence true
│         log_dest file /var/log/mosquitto/mosquitto.log
│
├─ TASK 4: Create data directories
│   └─ Creates:
│       ├─ /var/lib/mosquitto (data persistence)
│       └─ /var/log/mosquitto (logs)
│
├─ TASK 5: Enable Mosquitto service
│   └─ Symlink: /etc/systemd/system/multi-user.target.wants/mosquitto.service
│   └─ Effect: systemd will auto-start mosquitto on boot
│
├─ TASK 6: Start Mosquitto service
│   └─ Command: systemctl start mosquitto
│   └─ Result: Mosquitto listening on port 1883
│
└─ TASK 7: Verify port is listening
    └─ Check: nc -zv localhost 1883
    └─ Wait: up to 10 seconds for port to open
    └─ Timeout if not ready
```

**Result After MQTT:**
```
Mosquitto Service State:
$ systemctl status mosquitto
  Active: active (running) since ...
  Main PID: 5678
  Tasks: 3
  Memory: 1.2M
  CPU: 0%

Listening on:
$ netstat -tlnp | grep 1883
  tcp  0  0  0.0.0.0:1883  LISTEN  5678/mosquitto
```

---

### Phase 5: Role Execution (Orchestrator Role)

#### Step 5a: Stop Running Service
```
TASK: Stop orchestrator service (if running)
  └─ Command: systemctl stop go-ble-orchestrator
  └─ Effect: Service stopped gracefully
  └─ ignore_errors: yes (first run won't have service)
```

#### Step 5b: Copy Binary
```
TASK: Copy binary from control machine
  └─ Source (control): /path/to/CassiaConnectionTest/Cassia/go-ble-orchestrator
  └─ Destination (target): /opt/orchestrator/bin/go-ble-orchestrator
  └─ Owner: orcservice:orcservice
  └─ Permissions: 755 (executable)
  └─ Method: SCP over SSH (secure)
```

**On Target Server:**
```
$ ls -la /opt/orchestrator/bin/
  total 16900
  -rwxr-xr-x  1 orcservice orcservice  16777216  Apr 1 12:00  go-ble-orchestrator
```

#### Step 5c: Copy Frontend & Assets
```
TASK: Copy frontend assets
  └─ Source: ./frontend/
  └─ Destination: /opt/orchestrator/frontend/
  └─ Contents:
      ├─ index.html
      ├─ script.js
      └─ style.css

TASK: Copy ecg_metrics binary
  └─ Source: ./ecg_metrics
  └─ Destination: /opt/orchestrator/ecg_metrics
  └─ Permissions: 755 (executable)
```

#### Step 5d: Generate Dynamic Config from Template
```
TASK: Generate config.json from template
  └─ Template File: roles/orchestrator/templates/config.json.j2
  └─ Input Variables (from vars.yml + vault.yml):
      - {{ app_version }} = v1.1.4.1
      - {{ api_endpoint }} = https://nexus.api.lifesigns.us/...
      - {{ cassia_client_id }} = lifesigns
      - {{ cassia_client_secret }} = ca04600dd2345948# (from vault)
      - {{ mqtt_broker }} = tcp://localhost:1883
      - {{ app_data_path }} = /opt/orchestrator/data
  └─ Jinja2 Rendering (template → JSON)
  └─ Output: /opt/orchestrator/config/config.json
  └─ Backup: /opt/orchestrator/config/config.json.backup
  └─ Trigger: notify restart orchestrator (if changed)

Generated config.json looks like:
{
  "env": "prod",
  "databasePath": "/opt/orchestrator/data/unified_orchestrator.db",
  "appVersion": "v1.1.4.1",
  "configPassword": "Config@2024",
  "cassia": {
    "clientId": "lifesigns",
    "clientSecret": "ca04600dd2345948#",
    "acDomain": "http://172.16.20.24"
  },
  "mqtt": {
    "broker": "tcp://localhost:1883"
  }
  ...
}
```

#### Step 5e: Create Systemd Service File
```
TASK: Create systemd service file
  └─ Template: roles/orchestrator/templates/orchestrator.service.j2
  └─ Variables substituted:
      - {{ service_description }}
      - {{ app_user }}
      - {{ app_group }}
      - {{ app_home }}
      - {{ app_bin_path }}
      - {{ app_config_path }}
  └─ Output: /etc/systemd/system/go-ble-orchestrator.service

Generated service file:
[Unit]
Description=BLE Orchestrator Service
After=network.target mosquitto.service
Wants=mosquitto.service

[Service]
Type=simple
User=orcservice
Group=orcservice
WorkingDirectory=/opt/orchestrator
ExecStart=/opt/orchestrator/bin/go-ble-orchestrator \
          -config /opt/orchestrator/config/config.json
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=go-ble-orchestrator

# Security
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/opt/orchestrator

# Limits
LimitNOFILE=65536
LimitNPROC=4096

[Install]
WantedBy=multi-user.target
```

#### Step 5f: Enable & Start Service
```
TASK: Reload systemd daemon
  └─ Command: systemctl daemon-reload
  └─ Effect: Systemd reads new service file

TASK: Enable service on boot
  └─ Command: systemctl enable go-ble-orchestrator
  └─ Creates symlink:
      /etc/systemd/system/multi-user.target.wants/go-ble-orchestrator.service
      → /etc/systemd/system/go-ble-orchestrator.service
  └─ Effect: Service auto-starts on system boot

TASK: Start orchestrator service
  └─ Command: systemctl start go-ble-orchestrator
  └─ Systemd:
      1. Spawns process as user: orcservice
      2. Sets working directory: /opt/orchestrator
      3. Executes: /opt/orchestrator/bin/go-ble-orchestrator \
                   -config /opt/orchestrator/config/config.json
      4. Captures stdout/stderr to journalctl
      5. Monitors process (PID tracking)
      6. Auto-restart if process dies

TASK: Wait for service health
  └─ Attempts: 10 times
  └─ Delay between: 3 seconds
  └─ Check: curl http://localhost:8083/health
  └─ Wait: Until port 8083 accessible
```

**Result After Orchestrator:**
```
$ systemctl status go-ble-orchestrator
  ● go-ble-orchestrator.service - BLE Orchestrator Service
    Loaded: loaded (/etc/systemd/system/go-ble-orchestrator.service; enabled; vendor preset: enabled)
    Active: active (running) since Tue 2026-04-01 12:05:00 UTC
      Docs: man:systemd.unit(5)
    Main PID: 9876 (go-ble-orchestrator)
      Tasks: 5
      Memory: 45.2M
      CPUTime: 0.2s
      CGroup: /system.slice/go-ble-orchestrator.service
              └─9876 /opt/orchestrator/bin/go-ble-orchestrator \
                      -config /opt/orchestrator/config/config.json

$ netstat -tlnp | grep LISTEN
  tcp  0  0  0.0.0.0:8083    LISTEN  9876/go-ble-orch...
  tcp  0  0  0.0.0.0:1883    LISTEN  5678/mosquitto

$ curl http://localhost:8083/
  ✓ Dashboard loads successfully
```

---

## Service Management Deep Dive

### How Systemd Manages Services

```
SERVICE LIFECYCLE
─────────────────

1. BOOT TIME
────────────
BIOS/UEFI
  ↓
Linux Kernel starts
  ↓
systemd (PID 1) starts
  ↓
systemd reads: /etc/systemd/system/multi-user.target.wants/
  ├─ go-ble-orchestrator.service
  └─ mosquitto.service
  ↓
For EACH service (in dependency order):
  ├─ Check: Wants=, After= dependencies
  ├─ Start prerequisite services first
  └─ Launch the service
  ↓
All services running ✓


2. SERVICE RUNNING
──────────────────
systemd tracks:
  ├─ PID of orchestrator process
  ├─ Memory usage
  ├─ CPU usage
  ├─ Open file descriptors
  ├─ Child processes
  └─ Resource limits

$ systemctl status go-ble-orchestrator
Shows all this info


3. PROCESS CRASH HANDLING
──────────────────────────
If orchestrator crashes:
  ├─ systemd detects PID death
  ├─ Checks Restart=on-failure setting
  ├─ Waits RestartSec=5 (5 seconds)
  ├─ Relaunches service automatically
  ├─ Logs restart attempt to journalctl
  └─ Service comes back online

Example:
  Your app has memory leak
    ↓ after 2 hours, process dies
    ↓ systemd immediately respawns it
    ↓ you can check logs later: journalctl -u go-ble-orchestrator
    ↓ no manual intervention needed


4. MANUAL STOP/START
────────────────────
$ systemctl stop go-ble-orchestrator
  ├─ Send SIGTERM to process
  ├─ Wait for graceful shutdown (15 seconds default)
  ├─ If not stopped: Send SIGKILL
  ├─ Update service status
  └─ Stop monitoring

$ systemctl start go-ble-orchestrator
  └─ Launch again (follows all Unit configuration)

$ systemctl restart go-ble-orchestrator
  └─ Stop + Wait 1 second + Start
  └─ Faster than explicit stop/start


5. SYSTEM SHUTDOWN
──────────────────
System shutdown initiated
  ↓
systemd stops all services (reverse dependency order)
  ├─ go-ble-orchestrator SIGTERM
  ├─ Wait for orchestrator to stop
  ├─ mosquitto SIGTERM
  ├─ Wait for MQTT to stop
  └─ Continue with other services
  ↓
System shuts down cleanly
```

### Systemd Service Dependencies

```
Your orchestrator.service has:
  After=network.target mosquitto.service
  Wants=mosquitto.service

MEANING:
  ├─ network.target: Don't start until network is ready
  ├─ mosquitto.service: Start after mosquitto
  └─ Wants=: If mosquitto fails, still try to start us
           (unlike Requires= which would fail us too)

BOOT SEQUENCE:
  1. Linux boots
  2. systemd starts network.target (waits for networking)
  3. systemd starts mosquitto.service
  4. systemd starts go-ble-orchestrator.service
     (because it's After= mosquitto)
  5. Both services running

If MQTT crashes:
  ├─ systemd auto-restarts mosquitto (Restart=always)
  ├─ orchestrator stays running (Wants= is soft dependency)
  ├─ orchestrator reconnects when MQTT is back
  └─ No cascade failures
```

### Logging & Monitoring

```
WHAT SYSTEMD LOGS AUTOMATICALLY
─────────────────────────────────

$ journalctl -u go-ble-orchestrator
Shows all:
  ├─ When service started
  ├─ Any errors during startup
  ├─ All stdout/stderr from app
  ├─ When/why service restarted
  ├─ Resource usage
  └─ Timestamps for everything

EXAMPLE OUTPUT:
──────────────
Apr 01 12:05:00 prod-01 systemd[1]: Starting BLE Orchestrator Service...
Apr 01 12:05:00 prod-01 systemd[1]: Started BLE Orchestrator Service.
Apr 01 12:05:01 prod-01 go-ble-orchestrator[9876]: [INFO] Server starting on :8083
Apr 01 12:05:01 prod-01 go-ble-orchestrator[9876]: [INFO] Connected to MQTT broker
Apr 01 12:05:02 prod-01 go-ble-orchestrator[9876]: [DEBUG] 3 devices found

Apr 01 13:00:00 prod-01 go-ble-orchestrator[9876]: [ERROR] MQTT connection lost
Apr 01 13:00:00 prod-01 systemd[1]: go-ble-orchestrator.service: Killing remaining processes...
Apr 01 13:00:05 prod-01 systemd[1]: go-ble-orchestrator.service: Restart scheduled.
Apr 01 13:00:05 prod-01 systemd[1]: Starting BLE Orchestrator Service...
Apr 01 13:00:05 prod-01 go-ble-orchestrator[9900]: [INFO] Server starting on :8083
Apr 01 13:00:06 prod-01 go-ble-orchestrator[9900]: [INFO] Connected to MQTT broker

FILTERING:
──────────
# Last 50 lines
journalctl -u go-ble-orchestrator -n 50

# Follow in real-time (like tail -f)
journalctl -u go-ble-orchestrator -f

# Since last boot
journalctl -u go-ble-orchestrator -b

# Since last 2 hours
journalctl -u go-ble-orchestrator --since "2 hours ago"

# Only errors
journalctl -u go-ble-orchestrator -p err

# With JSON output (for parsing/alerting)
journalctl -u go-ble-orchestrator -o json
```

---

## Real-World Execution Examples

### Example 1: Fresh Deployment to 2 Servers

```bash
$ ansible-playbook playbooks/deploy.yml --ask-vault-pass
Vault password: ••••••••••

PLAY [Deploy BLE Orchestrator and MQTT]
───────────────────────────────────────────────────────────────

Gathering Facts
  prod-orchestrator-01: ok
  prod-orchestrator-02: ok

PRE-TASKS
──────────

TASK [Display deployment info]
  prod-orchestrator-01: 
    msg: Deploying go-ble-orchestrator v1.1.4.1
         Target: prod-orchestrator-01
         Environment: production

  prod-orchestrator-02:
    msg: Deploying go-ble-orchestrator v1.1.4.1
         Target: prod-orchestrator-02
         Environment: production

ROLE: Prerequisites
──────────────────

TASK [Update system packages]
  prod-orchestrator-01: changed
    (apt-get update completed)
  prod-orchestrator-02: changed
    (apt-get update completed)

TASK [Install required packages]
  prod-orchestrator-01: changed
    (8 packages installed: curl, wget, ca-certificates, ...)
  prod-orchestrator-02: changed
    (8 packages installed: curl, wget, ca-certificates, ...)

TASK [Create app user]
  prod-orchestrator-01: changed
    (user 'orcservice' created)
  prod-orchestrator-02: changed
    (user 'orcservice' created)

TASK [Create application directories]
  prod-orchestrator-01: changed
    (5 directories created under /opt/orchestrator)
  prod-orchestrator-02: changed
    (5 directories created under /opt/orchestrator)

ROLE: MQTT
──────────

TASK [Install Mosquitto]
  prod-orchestrator-01: changed
    (mosquitto installed)
  prod-orchestrator-02: changed
    (mosquitto installed)

TASK [Deploy mosquitto configuration]
  prod-orchestrator-01: changed
    (config file created at /etc/mosquitto/conf.d/orchestrator.conf)
  prod-orchestrator-02: changed
    (config file created at /etc/mosquitto/conf.d/orchestrator.conf)

TASK [Enable Mosquitto service]
  prod-orchestrator-01: changed
    (service enabled for boot)
  prod-orchestrator-02: changed
    (service enabled for boot)

TASK [Start Mosquitto service]
  prod-orchestrator-01: changed
    (mosquitto started, PID: 1234)
  prod-orchestrator-02: changed
    (mosquitto started, PID: 5678)

ROLE: Orchestrator
──────────────────

TASK [Copy binary]
  prod-orchestrator-01: changed
    (16.8 MB binary copied via SCP)
  prod-orchestrator-02: changed
    (16.8 MB binary copied via SCP)

TASK [Copy frontend assets]
  prod-orchestrator-01: changed
    (frontend/ directory copied)
  prod-orchestrator-02: changed
    (frontend/ directory copied)

TASK [Generate config.json]
  prod-orchestrator-01: changed
    (template rendered with 25 variables)
  prod-orchestrator-02: changed
    (template rendered with 25 variables)

TASK [Create systemd service file]
  prod-orchestrator-01: changed
    (service file created at /etc/systemd/system/go-ble-orchestrator.service)
  prod-orchestrator-02: changed
    (service file created at /etc/systemd/system/go-ble-orchestrator.service)

TASK [Reload systemd daemon]
  prod-orchestrator-01: ok
    (systemd daemon reloaded)
  prod-orchestrator-02: ok
    (systemd daemon reloaded)

TASK [Enable orchestrator service]
  prod-orchestrator-01: changed
    (service enabled for boot)
  prod-orchestrator-02: changed
    (service enabled for boot)

TASK [Start orchestrator service]
  prod-orchestrator-01: changed
    (service started, PID: 2468)
  prod-orchestrator-02: changed
    (service started, PID: 3579)

TASK [Wait for orchestrator to be healthy]
  prod-orchestrator-01: ok
    (HTTP health check passed after 1 attempt)
  prod-orchestrator-02: ok
    (HTTP health check passed after 1 attempt)

POST-TASKS
──────────

TASK [Check service status]
  prod-orchestrator-01:
    msg: go-ble-orchestrator is active
  prod-orchestrator-02:
    msg: go-ble-orchestrator is active

PLAY RECAP
─────────
prod-orchestrator-01: ok=28 changed=24 unreachable=0 failed=0
prod-orchestrator-02: ok=28 changed=24 unreachable=0 failed=0
╔════════════════════════════════════════════════════════════╗
║          DEPLOYMENT COMPLETED SUCCESSFULLY ✓               ║
╚════════════════════════════════════════════════════════════╝

NEXT: Verify services running
$ ssh ubuntu@10.0.1.100
$ systemctl status go-ble-orchestrator
  ● go-ble-orchestrator.service - BLE Orchestrator Service
    Active: active (running)
    Main PID: 2468

$ curl http://localhost:8083
  Dashboard loads successfully ✓
```

---

### Example 2: Configuration Update (No Redeployment)

```bash
$ ansible-playbook playbooks/configure.yml \
    -e "cassia_domain=http://new.domain.com" \
    --ask-vault-pass

Vault password: ••••••••••

PLAY [Update configuration and restart services]
────────────────────────────────────────────────

TASK [Backup current configuration]
  prod-orchestrator-01: changed
    (config.json backed up to config.json.backup)
  prod-orchestrator-02: changed
    (config.json backed up to config.json.backup)

TASK [Regenerate config.json]
  prod-orchestrator-01: changed
    (config.json updated with new cassia_domain)
  prod-orchestrator-02: changed
    (config.json updated with new cassia_domain)

TASK [Restart orchestrator service]
  (triggered by config change)
  prod-orchestrator-01: changed
    (service restarted, PID changed from 2468 → 2500)
  prod-orchestrator-02: changed
    (service restarted, PID changed from 3579 → 3600)

TASK [Verify orchestrator is running]
  prod-orchestrator-01: ok
    (systemd status confirmed active)
  prod-orchestrator-02: ok
    (systemd status confirmed active)

PLAY RECAP
─────────
prod-orchestrator-01: ok=6 changed=3 unreachable=0 failed=0
prod-orchestrator-02: ok=6 changed=3 unreachable=0 failed=0

RESULT:
 ✓ Configuration updated
 ✓ Service restarted (zero-downtime migration)
 ✓ New cassia_domain active
 ✓ No binary redeployment needed
```

---

### Example 3: What Happens on Service Crash

```
SCENARIO: Orchestrator crashes at 2:45 AM

BEFORE:
───────
$ systemctl status go-ble-orchestrator
  ● go-ble-orchestrator.service - BLE Orchestrator Service
    Active: active (running)
    Main PID: 2500


CRASH MOMENT (2:45:00 AM):
──────────────────────
App memory leak → Out of memory → Process killed by kernel


SYSTEMD RESPONSE (automatic):
─────────────────────────────
2:45:00 - Kernel: Process killed (OOM)
2:45:00 - systemd: Detected PID 2500 died
2:45:00 - systemd: Check Restart=on-failure → YES
2:45:00 - systemd: Start RestartSec timer (5 seconds)
2:45:05 - systemd: Respawn process
         └─ Launches: /opt/orchestrator/bin/go-ble-orchestrator \
                      -config /opt/orchestrator/config/config.json
2:45:05 - Service running with new PID: 2520
2:45:06 - Service ready to serve requests


LOGS:
─────
$ journalctl -u go-ble-orchestrator --since "2:40 AM"

Apr 01 02:43:00 prod-01 go-ble-orchestrator[2500]: [INFO] Processing 45 devices
Apr 01 02:44:00 prod-01 go-ble-orchestrator[2500]: [DEBUG] Memory: 2048M
Apr 01 02:44:30 prod-01 go-ble-orchestrator[2500]: [WARN] Memory: 2560M
Apr 01 02:44:59 prod-01 go-ble-orchestrator[2500]: [ERROR] Out of memory
Apr 01 02:45:00 prod-01 systemd[1]: go-ble-orchestrator.service: Main process exited, code=killed, status=9/KILL
Apr 01 02:45:00 prod-01 systemd[1]: go-ble-orchestrator.service: Unit entered failed state.
Apr 01 02:45:00 prod-01 systemd[1]: go-ble-orchestrator.service: Failed with result 'signal'.
Apr 01 02:45:05 prod-01 systemd[1]: go-ble-orchestrator.service: Service hold-off time over, scheduling restart.
Apr 01 02:45:05 prod-01 systemd[1]: Restart scheduled for go-ble-orchestrator.service.
Apr 01 02:45:05 prod-01 systemd[1]: Starting BLE Orchestrator Service...
Apr 01 02:45:05 prod-01 systemd[1]: Started BLE Orchestrator Service.
Apr 01 02:45:06 prod-01 go-ble-orchestrator[2520]: [INFO] Server starting on :8083
Apr 01 02:45:06 prod-01 go-ble-orchestrator[2520]: [INFO] Connected to MQTT broker


USERS DON'T NOTICE:
───────────────────
✓ 5 second downtime only
✓ Devices continue to work (reconnect to broker)
✓ No manual intervention needed
✓ Logs available for post-mortem analysis
```

---

### Example 4: Manual Service Control

```bash
# Check status
$ systemctl status go-ble-orchestrator
  ● go-ble-orchestrator.service - BLE Orchestrator Service
    Active: active (running) since Tue 2026-04-01 12:05:00 UTC; 2 days ago
    Main PID: 2520
    Tasks: 5
    Memory: 45.2M
    CPU: 0.1%s

# Stop service (graceful shutdown)
$ sudo systemctl stop go-ble-orchestrator
  (sends SIGTERM to process, waits 15 seconds, then SIGKILL if needed)

# Verify stopped
$ systemctl status go-ble-orchestrator
  ● go-ble-orchestrator.service - BLE Orchestrator Service
    Active: inactive (dead)
    Main PID: -

# Start service again
$ sudo systemctl start go-ble-orchestrator
  (launches process, connects to MQTT, ready for requests)

# Restart (stop + start)
$ sudo systemctl restart go-ble-orchestrator
  (useful for config reload, version updates, etc.)

# View logs (last 100 lines)
$ sudo journalctl -u go-ble-orchestrator -n 100

# Follow logs in real-time
$ sudo journalctl -u go-ble-orchestrator -f
  (shows logs as they're written, press Ctrl+C to exit)

# View resource usage
$ systemctl status go-ble-orchestrator
  Shows: Memory, CPU, Tasks, ...

# Check if service enabled on boot
$ systemctl is-enabled go-ble-orchestrator
  enabled

# Disable auto-start on boot (but keep running)
$ sudo systemctl disable go-ble-orchestrator
  (remove from startup, but running service stays running)

# Enable auto-start again
$ sudo systemctl enable go-ble-orchestrator
  (recreate symlink for boot startup)
```

---

## Key Differences: Systemd vs Docker

| Aspect | Docker | Systemd |
|--------|--------|---------|
| **Image Size** | 200-300 MB | 0 MB (binary only) |
| **Startup Time** | 2-5 seconds | <1 second |
| **System Integration** | Isolated container | Native OS service |
| **Auto-restart** | Manual (docker restart policy) | Built-in (Restart=on-failure) |
| **Logging** | Docker daemon logs | systemd journalctl |
| **Dependency Management** | docker-compose services | systemd Units (After=, Wants=) |
| **Process Monitoring** | Docker API | systemctl, systemd directly |
| **Resource Limits** | cgroup (via docker) | systemd resource (native) |
| **Boot Integration** | Requires Docker daemon | systemd (init system) |
| **Configuration** | docker-compose.yml | .service files |
| **Persistence** | Docker volumes | Filesystem volumes |
| **OS Agnostic** | ✓ Yes | ✗ Linux only |
| **Performance** | ~5% overhead | <0.5% overhead |

---

## Systemd Advantages for Your Use Case

### 1. **Zero Overhead**
```
Docker: 
  Kernel → Docker daemon → Container → Application
  (3 layers, ~50MB RAM overhead)

Systemd:
  Kernel → Application
  (direct, 5MB RAM overhead max)
```

### 2. **Automatic Failure Recovery**
```
Docker: Manual restart
  Container crashes
    ↓ (nothing happens unless restart policy set)
    ↓ manual docker start
    ↓ monitoring needed

Systemd: Automatic restart
  Service crashes
    ↓ systemd detects immediately
    ↓ auto-restart after RestartSec
    ↓ built-in, no extra monitoring needed
```

### 3. **Cross-Server Consistency**
```
Your setup:
  ├─ Production Server 1: systemd service
  ├─ Production Server 2: systemd service  
  └─ All running same process, same interface

No Docker runtime version differences
No container image compatibility issues
```

### 4. **Easier Debugging**
```
Docker:
  $ docker logs container_name
  $ docker exec -it container_name /bin/bash
  $ docker stats

Systemd:
  $ journalctl -u service_name
  $ systemctl status service_name
  $ ssh directly to machine
  Standard Linux tools everywhere
```

### 5. **Deployment Simplicity**
```
Docker:
  1. Build image
  2. Push to registry
  3. Pull on server
  4. Run container
  5. Manage volumes

Systemd:
  1. Build binary
  2. Copy binary to /opt/orchestrator/bin/
  3. systemctl start service_name
  Done.
```

---

## Why No Docker Here

After reviewing your Docker setup, here's why systemd is better for this specific case:

1. **Single Binary App**: You're not orchestrating 10+ services. One app + one MQTT broker = systemd shines.

2. **High Availability Needed**: Crashes must auto-recover. Systemd does this natively. Docker needs external orchestration (Kubernetes).

3. **Resource-Constrained**: Your server doesn't benefit from container isolation. Waste less RAM with systemd.

4. **Operational Simplicity**: No image rebuilds, no registry, no version management. Just point to binary path.

5. **Cloud-Native DevOps**: Ansible + systemd is simpler than Ansible + Docker + docker-compose.

---

## Summary: Ansible + Systemd Workflow

```
Flow:
────
1. You run: ansible-playbook deploy.yml
2. Ansible connects to servers via SSH
3. For each role:
   ├─ Prerequisites: Install packages, create user/directories
   ├─ MQTT: Install Mosquitto, create systemd service
   └─ Orchestrator: Copy binary, template config, create systemd service
4. Systemd services start automatically
5. Services configured for auto-restart on crash
6. Logs captured in journalctl
7. Done.

Result:
───────
✓ go-ble-orchestrator service running as orcservice user
✓ mosquitto service running as mosquitto user
✓ Auto-restart on failure (5 second delay)
✓ Boot persistence (auto-start on reboot)
✓ Centralized logging (journalctl)
✓ Zero Docker overhead
✓ Full Ansible idempotency (re-run safely)
```

