# Two Setup Scripts Explained

## Overview

You have **two different setup scripts** for two different deployment scenarios:

| Aspect | `setup.sh` (Root) | `orchestrator setup/setup.sh` |
|--------|-----------|------|
| **Location** | `/ansible/setup.sh` | `/ansible/orchestrator setup/setup.sh` |
| **Purpose** | Prepare local Ansible environment | Standalone Linux installer |
| **Runs On** | Your control machine (Windows/Mac/Linux) | Target Linux servers only |
| **Dependencies** | Python, Ansible, terraform-vault | curl, unzip, sudo |
| **Downloads From** | N/A | GitHub API |
| **Used By** | Human operator | Ansible playbooks or manual SSH |

---

## Script 1: `setup.sh` (Root Level)

**Location**: `ansible/setup.sh`

**Purpose**: Prepares your LOCAL Ansible environment for deployments

### What It Does

```bash
#!/bin/bash

1. VALIDATE ENVIRONMENT
   ├─ Checks Python3 installed
   ├─ Checks Ansible installed
   └─ Checks ansible-vault available

2. CREATE DIRECTORY STRUCTURE
   ├─ mkdir -p inventory/group_vars/orchestrator_servers
   ├─ mkdir -p roles/{prerequisites,orchestrator,mqtt}/{tasks,templates,handlers}
   ├─ mkdir -p playbooks
   └─ mkdir -p binaries

3. SETUP VAULT (Encryption for secrets)
   └─ Prompts user to enter secrets interactively

4. TEST CONNECTIVITY
   ├─ Asks operator for server IPs
   └─ Tests ping to each server

5. VALIDATE PLAYBOOKS
   ├─ Syntax check: deploy.yml
   ├─ Syntax check: configure.yml
   └─ Syntax check: rollback.yml

6. INSTRUCTIONS
   └─ Tells operator next steps:
      1. Update inventory/production.yml
      2. Update vars.yml
      3. Build binary locally
      4. Run: ansible-playbook playbooks/deploy.yml
```

### When to Run
```
FIRST TIME SETUP
  ↓
python3 setup.sh
  ↓
One-time initialization
```

### What Happens After
```
You can now:
  ✓ Deploy to all servers: ansible-playbook playbooks/deploy.yml
  ✓ Update config: ansible-playbook playbooks/configure.yml
  ✓ Rollback: ansible-playbook playbooks/rollback.yml
```

### Example Output
```
=== BLE Orchestrator Ansible Setup ===
✓ Ansible is installed
✓ Directory structure created
✓ Vault file ready
✓ Connected to 10.0.1.100
✓ All playbooks are valid

Next steps:
1. Update inventory/production.yml with your server IPs
2. Update inventory/group_vars/orchestrator_servers/vars.yml
3. Add secrets to inventory/group_vars/orchestrator_servers/vault.yml
4. Build your binary: CGO_ENABLED=0 GOOS=linux go build
5. Run deployment: ansible-playbook playbooks/deploy.yml
```

---

## Script 2: `orchestrator setup/setup.sh`

**Location**: `ansible/orchestrator setup/setup.sh`

**Purpose**: Standalone Linux installer that runs ON TARGET SERVERS

### What It Does

```bash
#!/usr/bin/env bash

1. VALIDATE OS
   ├─ Must be Ubuntu 22.04+
   └─ Checks /etc/os-release

2. CHECK PREREQUISITES
   ├─ Requires: curl
   ├─ Requires: unzip
   └─ Requires: sudo

3. DOWNLOAD FROM GITHUB
   ├─ Query: https://api.github.com/repos/Lifesigns-PD/orchestrator-releases/releases/latest
   ├─ Download: Installationsmain-{tag}.zip
   └─ Unzip to temp directory

4. RUN INSTALLER
   ├─ Execute: ./DeviceManager_Install.sh
   ├─ Creates: /opt/go-ble-orchestrator
   └─ Enables: go-ble-orchestrator.service

5. OPTIONAL: GATEWAY DASHBOARD
   ├─ Query: https://api.github.com/repos/PD-dev-2025/gateway-dashboard-release/releases/latest
   ├─ Download: gateway-dashboard_linux_amd64.zip
   ├─ Setup config.json
   ├─ Create: /opt/gateway-dashboard
   ├─ Create: /etc/systemd/system/gateway-dashboard.service
   └─ Start both services
```

### When to Run
```
MANUAL SINGLE-SERVER DEPLOYMENT

                    ↓

ssh ubuntu@10.0.1.100 'bash -c "
  curl -fsSL https://raw.githubusercontent.com/Lifesigns-PD/orchestrator-releases/main/setup.sh | sudo bash
"'

                    ↓

Server downloads + installs latest from GitHub
```

### Prerequisites on Target
```bash
# These must be present
curl              # For downloading
unzip             # For extracting
sudo              # For privileged operations
Ubuntu 22.04+     # OS requirement
```

### What Gets Downloaded
```
From GitHub:
├─ go-ble-orchestrator (main app)
├─ ecg_metrics (helper utility)
├─ frontend/ (web assets)
├─ config.json.example (configuration template)
└─ README.md

Installed to:
├─ /opt/go-ble-orchestrator/
└─ /opt/gateway-dashboard/ (optional)

Services created:
├─ /etc/systemd/system/go-ble-orchestrator.service
└─ /etc/systemd/system/gateway-dashboard.service (optional)
```

### Example Output
```
Downloading latest release asset: v1.2.5
Unzipping release bundle...
Making DeviceManager_Install.sh executable...
Starting installer...
✓ orchestrator service installed and started

Additionally you need to update the gateway-dashboard version. Type yes to continue: yes

Downloading gateway-dashboard release: v2.1.0
✓ gateway-dashboard installed and started successfully.
```

---

## Key Differences

### Purpose
- **Root setup.sh**: Sets up YOUR LOCAL Ansible environment
- **Orchestrator setup.sh**: Installs software ON TARGET SERVER

### Trust Boundary
```
Root setup.sh:
┌─ LOCAL CONTROL MACHINE ─┐
│  setup.sh (validator)   │
│  Validates Ansible      │
│  Creates vault          │
└─────────────────────────┘

Orchestrator setup.sh:
┌──────────────────────────┐
│  REMOTE TARGET SERVER    │
│  setup.sh (installer)    │
│  Downloads from GitHub   │
│  Sets up services        │
└──────────────────────────┘
```

### Deployment Flow

**Method A: Ansible (Uses root setup.sh)**
```
1. You run: python3 setup.sh
2. Validate environment
3. Later: ansible-playbook deploy.yml
4. Copies PRE-BUILT binaries to servers
5. Creates systemd services
```

**Method B: GitHub (Uses orchestrator setup.sh)**
```
1. You SSH to server
2. Run: setup.sh directly
3. Script downloads from GitHub
4. Creates systemd services
5. Starts immediately

OR

1. User interactively calls:
   python3 scripts/deploy_orchestrator.py
2. Tool generates SSH command
3. Runs orchestrator setup.sh remotely
```

---

## Decision Tree

```
┌─ Need to deploy to TARGET SERVERS?
│
├─ YES, using Ansible
│  ├─ Run: ./setup.sh (ONE TIME)
│  ├─ Update: inventory/production.yml
│  ├─ Build: binaries locally
│  └─ Run: ansible-playbook playbooks/deploy.yml
│
├─ YES, manually on individual servers
│  ├─ SSH to server:
│  │  ssh ubuntu@10.0.1.100
│  │
│  └─ Run:
│     curl -fsSL https://raw.github.../setup.sh | sudo bash
│
└─ TESTING/QUICK DEPLOYMENT
   └─ Use: python3 scripts/deploy_orchestrator.py
      └─ Handles everything interactively
```

---

## Usage Scenarios

### Scenario 1: Production Multi-Server Deployment

```bash
# STEP 1: Prepare control machine
cd ansible
./setup.sh
# Creates vault, validates structure

# STEP 2: Configure
vi inventory/production.yml           # Add server IPs
vi inventory/group_vars/.../vars.yml  # Update paths
ansible-vault edit inventory/group_vars/.../vault.yml

# STEP 3: Build
cd ../Cassia
CGO_ENABLED=0 GOOS=linux go build -o go-ble-orchestrator

# STEP 4: Deploy to all
cd ../ansible
ansible-playbook playbooks/deploy.yml --ask-vault-pass

# RESULT: All servers have identical version
```

### Scenario 2: Quick Single-Server Test

```bash
# SSH to server
ssh ubuntu@10.0.1.100

# Download and run
curl -fsSL https://raw.github.../setup.sh | sudo bash

# Server is ready to use
sudo systemctl status go-ble-orchestrator

# RESULT: Server has latest version from GitHub
```

### Scenario 3: Interactive Deployment Assistant

```bash
# Run the interactive tool
cd ansible/scripts
python3 deploy_orchestrator.py

# Choose which method:
# Method 1: Ansible (pre-built)
# Method 2: GitHub (auto-download)
# Method 3: Hybrid (use both)

# Tool generates and executes command
# RESULT: Server deployed as requested
```

---

## Common Questions

### Q: Which script do I run first?
**A:** `setup.sh` (root level) - one time to prepare your Ansible environment

### Q: Can I skip the root setup.sh?
**A:** Technically yes, but it validates everything. Recommended to run it once.

### Q: Does orchestrator setup.sh require Ansible?
**A:** No, it's standalone. Can be run manually via SSH or by Ansible playbooks.

### Q: Which is faster?
**A:** 
- Ansible (pre-built): ~1-2 minutes per server
- GitHub: ~3-5 minutes per server (downloads)

### Q: Which should I use for production?
**A:** Ansible - gives you consistency, rollback, and audit trail across multiple servers

### Q: What if I only have one server?
**A:** Either method works:
- Ansible: `ansible-playbook playbooks/deploy.yml`
- GitHub: Manual SSH + setup.sh

---

## File Locations

```
ansible/
├─ setup.sh                           ← Run this first (local validation)
├─ ansible.cfg
├─ requirements.txt
├─ inventory/
│  ├─ production.yml
│  └─ group_vars/orchestrator_servers/
│     ├─ vars.yml
│     └─ vault.yml
├─ playbooks/
│  ├─ deploy.yml                     ← Run after setup.sh
│  ├─ configure.yml
│  └─ rollback.yml
├─ roles/
│  ├─ prerequisites/
│  ├─ mqtt/
│  └─ orchestrator/
├─ scripts/
│  ├─ deploy_orchestrator.py         ← Interactive tool
│  ├─ connectedMachines.py           ← List Tailscale machines
│  └─ .env                           ← Tailscale credentials
├─ orchestrator setup/
│  └─ setup.sh                       ← Run on target servers (remote installer)
├─ DEPLOYMENT_GUIDE.md               ← Full documentation
└─ SETUP_SCRIPTS_EXPLAINED.md        ← This file
```

---

## Summary

- **Root `setup.sh`**: Validates & prepares YOUR local Ansible control machine
- **Orchestrator `setup.sh`**: Installs software ON target servers (standalone)
- **Use together**: Root setup → Ansible playbooks → Orchestrator services
- **Use separately**: Direct SSH → Run orchestrator setup.sh → Done
- **Use interactively**: `deploy_orchestrator.py` → Guides you through both

Choose based on your needs:
- **Many servers**: Use Ansible (root setup.sh first)
- **One server**: Use GitHub (orchestrator setup.sh directly)
- **Unsure**: Use interactive tool (`deploy_orchestrator.py`)
