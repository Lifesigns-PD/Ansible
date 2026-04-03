# Orchestrator Deployment Guide

## Overview

This guide explains the **three deployment methods** for the BLE Orchestrator and when to use each based on your deployment scenario.

### Quick Reference

| Method | When to Use | Speed | Complexity | Rollback |
|--------|------------|-------|------------|----------|
| **Ansible** | Multiple servers, production, version control needed | Medium | Medium | ✅ Yes |
| **GitHub Auto-Download** | Single server, always-latest, manual deployment | Fast | Low | ❌ No |
| **Hybrid** | Multiple servers, consistent versions, production | Medium | Medium | ✅ Yes |

---

## Method 1: Ansible Deployment (Recommended for Production)

### How It Works
```
Your Control Machine
        ↓
    [Pre-built binaries]
        ↓
  Ansible Playbook
        ↓
   Target Servers
```

### Prerequisites
```bash
# On control machine (where you run deployment)
cd /path/to/Ansible
pip install ansible paramiko

# Build binaries first
cd /path/to/CassiaConnectionTest/Cassia
CGO_ENABLED=0 GOOS=linux go build -o go-ble-orchestrator
go build -o ecg_metrics ./ecg_metrics

# Copy to expected location
cp go-ble-orchestrator /path/to/CassiaConnectionTest/Cassia/
cp ecg_metrics /path/to/CassiaConnectionTest/Cassia/
cp -r frontend /path/to/CassiaConnectionTest/Cassia/
```

### Configuration
1. **Update inventory** ([inventory/production.yml](inventory/production.yml)):
```yaml
orchestrator_servers:
  hosts:
    prod-orchestrator-01:
      ansible_host: 10.0.1.100    # Update with Tailscale IP
      app_version: "v1.1.4.1"
```

2. **Update variables** ([inventory/group_vars/orchestrator_servers/vars.yml](inventory/group_vars/orchestrator_servers/vars.yml)):
```yaml
# Update paths
binary_source_dir: "/path/to/CassiaConnectionTest/Cassia"

# Update Cassia connection
cassia_domain: "http://172.16.20.24"  # Your Cassia server
```

3. **Setup secrets** ([inventory/group_vars/orchestrator_servers/vault.yml](inventory/group_vars/orchestrator_servers/vault.yml)):
```bash
ansible-vault create inventory/group_vars/orchestrator_servers/vault.yml
# Add sensitive config like passwords
```

### Deployment

**Using the interactive tool:**
```bash
cd scripts
python3 deploy_orchestrator.py
# Select Method 1 (Ansible)
# Tool will generate the command for you
```

**Manual command:**
```bash
ansible-playbook playbooks/deploy.yml \
  -i inventory/production.yml \
  --ask-vault-pass \
  -e "ansible_user=ubuntu" \
  -vv
```

### What Happens
```
Phase 1: Prerequisites
├─ Update system packages (apt update/upgrade)
├─ Create 'orcservice' user
└─ Create /opt/orchestrator/{bin,config,data,logs}

Phase 2: MQTT Broker
├─ Install Mosquitto
├─ Deploy config from mosquitto.conf.j2
└─ Start mosquitto service (port 1883)

Phase 3: Orchestrator App
├─ Copy go-ble-orchestrator binary
├─ Copy frontend assets
├─ Copy ecg_metrics utility
├─ Generate config.json from template
├─ Create systemd service file
├─ Start service
└─ Health check (10 retries)

Post-Deployment
├─ Verify orchestrator service status
├─ Verify MQTT service status
└─ Dashboard available at http://<ip>:8083
```

### Advantages
✅ Fast - binaries pre-built  
✅ Reproducible - same version everywhere  
✅ Auditurable - all changes logged  
✅ Rollback capability - .backup files preserved  
✅ Configuration management - variables tracked  

### Rollback
```bash
# If deployment fails, simple rollback
ansible-playbook playbooks/rollback.yml \
  -i inventory/production.yml \
  --ask-vault-pass
```

---

## Method 2: GitHub Auto-Download (Recommended for Quick Testing)

### How It Works
```
Target Server (SSH)
        ↓
   setup.sh (from GitHub)
        ↓
Download latest from releases
        ↓
Run DeviceManager_Install.sh
```

### Prerequisites
```bash
# No local builds needed
# Just SSH access to target server
# Ensure you have Tailscale configured
```

### Deployment

**Using the interactive tool:**
```bash
cd scripts
python3 deploy_orchestrator.py
# Select Method 2 (GitHub)
# Tool will generate the SSH transfer command
```

**Manual command:**
```bash
ssh ubuntu@<TAILSCALE_IP> 'bash -c "
  curl -fsSL https://raw.githubusercontent.com/Lifesigns-PD/orchestrator-releases/main/setup.sh | sudo bash
"'
```

### What Happens
```
On Target Server:
├─ Fetch latest release info from GitHub API
├─ Download orchestrator-releases zip
├─ Unzip and run DeviceManager_Install.sh
├─ Create systemd service
├─ Optionally: Fetch and setup gateway-dashboard
└─ Services start on reboot
```

### Advantages
✅ No pre-staging needed  
✅ Always gets latest version  
✅ Includes gateway-dashboard option  
✅ Simple - just run one script  

### Disadvantages
❌ Slower - downloads every time  
❌ Network-dependent - requires GitHub connection  
❌ No rollback built-in  
❌ Hard to audit version consistency  

### When to Use
- Single server testing
- Always want latest release
- Don't need version control
- Quick proof-of-concept

---

## Method 3: Hybrid (Recommended for Production)

### How It Works
```
Build Locally (once)
        ↓
    Binaries
        ↓
  Ansible to N servers
        ↓
  All servers same version
```

### Process
```bash
# 1. Build once
cd /path/to/Cassia
CGO_ENABLED=0 GOOS=linux go build -o go-ble-orchestrator

# 2. Use Ansible to deploy to all servers
cd /path/to/Ansible
ansible-playbook playbooks/deploy.yml \
  -i inventory/production.yml \
  --ask-vault-pass
```

### Advantages
✅ Consistency - all servers run identical binaries  
✅ Speed - no downloads, just copy & deploy  
✅ Control - test binaries before deployment  
✅ Auditability - version tagged & logged  
✅ Rollback - built into Ansible  
✅ Multi-server - deploy to 5, 50, or 500 servers same way  

### Best For
- Production environments
- Multiple servers requiring consistency
- Regulated environments (audit trail needed)
- Version control required

---

## Comparing Deployment Methods

### Feature Matrix

| Feature | Ansible | GitHub | Hybrid |
|---------|---------|--------|--------|
| **Multiple servers** | ✅ | ❌ (one-by-one) | ✅ |
| **Version consistency** | ✅ | ❌ (varies) | ✅ |
| **Rollback** | ✅ | ❌ | ✅ |
| **Audit trail** | ✅ | ⚠ Limited | ✅ |
| **Speed** | Medium | Fast | Medium |
| **Complexity** | Medium | Low | Medium |
| **Network required** | Minimal | Yes (GitHub API) | Minimal |
| **Pre-staging** | Required | None | Required |

---

## Using the Interactive Deployment Tool

### Setup
```bash
# Install dependencies
pip install -r requirements.txt      # Should include: python-dotenv, requests

# Ensure Tailscale CLI installed
# Linux: sudo apt install tailscale
# macOS: brew install tailscale
# Windows: Download from tailscale.com

# Verify .env is in scripts/ directory
cat scripts/.env
# Should show:
# TAILSCALE_API_KEY=tskey-api-...
# Tailscale-tailnet-name=T48tog1ov911CNTRL
```

### Run
```bash
cd ansible/scripts
python3 deploy_orchestrator.py
```

### What It Does
```
1. Fetch all machines from your Tailscale tailnet
2. Display with status (🟢 Online / 🔴 Offline)
3. Prompt user to select target machine
4. Ask for SSH username/password
5. Show 3 deployment method options
6. Generate the appropriate deployment command
7. Execute if user confirms
```

### Example Output
```
════════════════════════════════════════════════════════════
Available Tailscale Machines
════════════════════════════════════════════════════════════

1. prod-orchestrator-01  (100.64.10.5       ) 🟢 Online
2. prod-orchestrator-02  (100.64.10.6       ) 🟢 Online
3. test-server           (100.64.10.10      ) 🔴 Offline

Select machine (1-3): 1
✓ Selected: prod-orchestrator-01 (100.64.10.5)

════════════════════════════════════════════════════════════
SSH Credentials
════════════════════════════════════════════════════════════

SSH Username: ubuntu
SSH Password: ****

════════════════════════════════════════════════════════════
Deployment Methods
════════════════════════════════════════════════════════════

Method 1: Ansible (Recommended for multi-server)
...
```

---

## Environment Setup

### Step 1: Get Tailscale API Key
```bash
# Create at https://app.tailscale.com/settings/keys
# Copy the key: tskey-api-...
```

### Step 2: Update .env
```bash
# Edit scripts/.env
TAILSCALE_API_KEY=tskey-api-YOUR_KEY_HERE
Tailscale-tailnet-name=T48tog1ov911CNTRL
```

### Step 3: Setup Ansible Inventory
```bash
# Edit inventory/production.yml
orchestrator_servers:
  hosts:
    prod-orchestrator-01:
      ansible_host: 100.64.10.5      # Tailscale IP from tool output
      app_version: "v1.1.4.1"
```

### Step 4: Configure Variables
```bash
# Edit inventory/group_vars/orchestrator_servers/vars.yml
binary_source_dir: "/full/path/to/CassiaConnectionTest/Cassia"
cassia_domain: "http://172.16.20.24"
```

---

## Troubleshooting

### "No machines found"
```bash
# Check Tailscale is running
sudo systemctl status tailscale

# Check API key
echo $TAILSCALE_API_KEY

# Try local Tailscale client
tailscale status --json | jq .
```

### Ansible connection fails
```bash
# Test SSH first
ssh -i ~/.ssh/id_rsa ubuntu@100.64.10.5 'whoami'

# Enable verbose output
ansible-playbook deploy.yml -vvv
```

### Binary not found
```bash
# Verify binary location
ls -la /path/to/Cassia/go-ble-orchestrator

# Check vars.yml points to right place
grep binary_source_dir inventory/group_vars/orchestrator_servers/vars.yml
```

### Service won't start
```bash
# SSH into target and check logs
ssh ubuntu@100.64.10.5
sudo journalctl -u go-ble-orchestrator -n 50
```

---

## Quick Start Checklist

- [ ] Build binaries locally
- [ ] Update [ansible.cfg](ansible.cfg) SSH key path
- [ ] Get Tailscale API key
- [ ] Update [scripts/.env](.env)
- [ ] Update [inventory/production.yml](inventory/production.yml)
- [ ] Update [inventory/group_vars/orchestrator_servers/vars.yml](inventory/group_vars/orchestrator_servers/vars.yml)
- [ ] Create vault: `ansible-vault create inventory/group_vars/orchestrator_servers/vault.yml`
- [ ] Test SSH: `ssh ubuntu@<TAILSCALE_IP> whoami`
- [ ] Run: `python3 scripts/deploy_orchestrator.py`

---

## See Also

- [Ansible Configuration](./ansible.cfg)
- [Playbook: Deploy](./playbooks/deploy.yml)
- [Playbook: Configure](./playbooks/configure.yml)
- [Playbook: Rollback](./playbooks/rollback.yml)
- [Manual Setup Script](./orchestrator%20setup/setup.sh)
