#!/usr/bin/env bash
# QUICK START GUIDE
# Use this cheat sheet for the three deployment scenarios

cat << 'EOF'

╔═══════════════════════════════════════════════════════════════════════════╗
║                                                                           ║
║         BLE ORCHESTRATOR DEPLOYMENT - QUICK START REFERENCE              ║
║                                                                           ║
╚═══════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 1: SETUP (One-time on your local machine)                          │
└─────────────────────────────────────────────────────────────────────────┘

# Install dependencies
pip install -r requirements.txt

# Run initial setup (this validates everything)
./setup.sh
  ├─ Checks Ansible installed
  ├─ Creates vault for secrets
  ├─ Tests SSH connectivity
  └─ Validates all playbooks

# Update configuration files
vi inventory/production.yml              # Add your server IPs
vi inventory/group_vars/orchestrator_servers/vars.yml
ansible-vault edit inventory/group_vars/orchestrator_servers/vault.yml

# Build binaries locally
cd ../Cassia
CGO_ENABLED=0 GOOS=linux go build -o go-ble-orchestrator
go build -o ecg_metrics ./cmd/ecg_metrics

┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 2: DEPLOY (Choose your method)                                     │
└─────────────────────────────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════════════════
OPTION A: Interactive Tool (Recommended)
═══════════════════════════════════════════════════════════════════════════

cd ansible/scripts
python3 deploy_orchestrator.py

# The tool will:
# 1. List all machines in your Tailscale tailnet
# 2. Ask you to select one
# 3. Prompt for SSH credentials
# 4. Show 3 deployment methods
# 5. Generate and execute the command

Example:
  $ python3 deploy_orchestrator.py
  
  Available Tailscale Machines
  ════════════════════════════════════════════════════════
  1. prod-orchestrator-01  (100.64.10.5)   🟢 Online
  2. prod-orchestrator-02  (100.64.10.6)   🟢 Online
  3. test-server           (100.64.10.10)  🔴 Offline
  
  Select machine (1-3): 1
  SSH Username: ubuntu
  SSH Password: ****
  
  Method 1: Ansible (Recommended)
  Method 2: GitHub Auto-Download
  Method 3: Hybrid
  
  Which deployment method? (1-3): 1

═══════════════════════════════════════════════════════════════════════════
OPTION B: Ansible (Manual)
═══════════════════════════════════════════════════════════════════════════

For MULTIPLE servers with CONSISTENT versions:

cd ansible
ansible-playbook playbooks/deploy.yml \
  -i inventory/production.yml \
  --ask-vault-pass \
  -vv

# What happens:
# 1. System packages installed
# 2. MQTT broker (Mosquitto) setup
# 3. Binaries copied from YOUR machine
# 4. Services created and enabled
# 5. Health checks performed

# Time: ~2 minutes per server
# Rollback: ✅ Supported

═══════════════════════════════════════════════════════════════════════════
OPTION C: GitHub Auto-Download (Manual)
═══════════════════════════════════════════════════════════════════════════

For SINGLE server with ALWAYS-LATEST version:

# SSH manually
ssh ubuntu@<TAILSCALE_IP>

# Then on target server, run:
curl -fsSL https://raw.githubusercontent.com/Lifesigns-PD/orchestrator-releases/main/setup.sh | sudo bash

# OR as one command:
ssh ubuntu@100.64.10.5 'bash -c "
  curl -fsSL https://raw.github.../setup.sh | sudo bash
"'

# What happens:
# 1. Fetches latest release from GitHub
# 2. Downloads orchestrator + gateway-dashboard
# 3. Creates systemd services
# 4. Starts services

# Time: ~3-5 minutes (includes download)
# Rollback: ❌ Not built-in (but GitHub has old releases)

═══════════════════════════════════════════════════════════════════════════
OPTION D: Hybrid (Ansible to Multiple Servers)
═══════════════════════════════════════════════════════════════════════════

For MULTIPLE servers needing CONSISTENCY and AUDIT TRAIL:

# Same as Ansible (Option B), but for all servers in inventory
cd ansible
ansible-playbook playbooks/deploy.yml \
  -i inventory/production.yml \
  --ask-vault-pass

# Deploy to all servers at once:
# prod-orchestrator-01 ✓ Deployed v1.1.4.1
# prod-orchestrator-02 ✓ Deployed v1.1.4.1
# prod-orchestrator-03 ✓ Deployed v1.1.4.1

┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 3: VERIFY DEPLOYMENT                                               │
└─────────────────────────────────────────────────────────────────────────┘

# SSH into deployed server
ssh ubuntu@<TAILSCALE_IP>

# Check orchestrator status
sudo systemctl status go-ble-orchestrator

# Check MQTT status
sudo systemctl status mosquitto

# View logs
sudo journalctl -u go-ble-orchestrator -f
sudo journalctl -u mosquitto -f

# Access dashboard
curl -s http://localhost:8083/health

# Check config
cat /opt/orchestrator/config/config.json | jq .

┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 4: MANAGE (After deployment)                                       │
└─────────────────────────────────────────────────────────────────────────┘

Update configuration without redeploying:
  ansible-playbook playbooks/configure.yml \
    -i inventory/production.yml \
    --ask-vault-pass

Rollback to previous version:
  ansible-playbook playbooks/rollback.yml \
    -i inventory/production.yml \
    --ask-vault-pass

Check deployment logs:
  cat ansible-deployment.log

┌─────────────────────────────────────────────────────────────────────────┐
│ ENVIRONMENT SETUP                                                        │
└─────────────────────────────────────────────────────────────────────────┘

Edit scripts/.env:

  TAILSCALE_API_KEY=tskey-api-YOUR_KEY_HERE
  Tailscale-tailnet-name=T48tog1ov911CNTRL

Get API key from: https://app.tailscale.com/settings/keys

┌─────────────────────────────────────────────────────────────────────────┐
│ WHICH METHOD TO CHOOSE?                                                 │
└─────────────────────────────────────────────────────────────────────────┘

  ┌─ How many servers?
  │
  ├─ Just 1-2 servers
  │  └─ Use GITHUB (simplest, fastest)
  │     $ ssh user@ip 'curl ... | sudo bash'
  │
  ├─ 3+ servers
  │  └─ Use ANSIBLE (consistent, auditable)
  │     $ ansible-playbook playbooks/deploy.yml
  │
  └─ Unsure
     └─ Use INTERACTIVE TOOL (guided through all options)
        $ python3 scripts/deploy_orchestrator.py

┌─────────────────────────────────────────────────────────────────────────┐
│ TROUBLESHOOTING                                                         │
└─────────────────────────────────────────────────────────────────────────┘

Deploy fails with "Binary not found":
  ✓ Check: ls -la /path/to/Cassia/go-ble-orchestrator
  ✓ Update: binary_source_dir in vars.yml

Cannot connect via SSH:
  ✓ Check: ssh -i ~/.ssh/id_rsa ubuntu@100.64.10.5 whoami
  ✓ Verify: Private key matches inventory config

Tailscale not showing machines:
  ✓ Check: tailscale status
  ✓ Check: TAILSCALE_API_KEY is set
  ✓ Check: Tailnet name is correct

Service won't start:
  ✓ SSH to server: ssh ubuntu@100.64.10.5
  ✓ Check logs: sudo journalctl -u go-ble-orchestrator -n 50
  ✓ Check config: cat /opt/orchestrator/config/config.json

┌─────────────────────────────────────────────────────────────────────────┐
│ FILES TO MAINTAIN                                                       │
└─────────────────────────────────────────────────────────────────────────┘

  ✓ inventory/production.yml              (server IPs)
  ✓ inventory/group_vars/.../vars.yml    (variables)
  ✓ inventory/group_vars/.../vault.yml   (secrets - encrypted)
  ✓ ansible.cfg                           (SSH config)
  ✓ scripts/.env                          (Tailscale API key)

  ✓ playbooks/deploy.yml                  (main deployment)
  ✓ playbooks/configure.yml               (update config)
  ✓ playbooks/rollback.yml                (emergency rollback)

  ✓ roles/prerequisites/                  (system setup)
  ✓ roles/mqtt/                           (MQTT broker)
  ✓ roles/orchestrator/                   (app deployment)

┌─────────────────────────────────────────────────────────────────────────┐
│ USEFUL COMMANDS                                                         │
└─────────────────────────────────────────────────────────────────────────┘

# List Tailscale machines (local)
tailscale status

# List Tailscale machines (API)
python3 scripts/connectedMachines.py

# Test Ansible connectivity
ansible orchestrator_servers -i inventory/production.yml -m ping

# Validate playbook syntax
ansible-playbook playbooks/deploy.yml --syntax-check

# Dry run (no changes)
ansible-playbook playbooks/deploy.yml --check

# Deploy with tags
ansible-playbook playbooks/deploy.yml --tags mqtt,orchestrator

# View vault contents (interactive)
ansible-vault view inventory/group_vars/orchestrator_servers/vault.yml

# Edit vault
ansible-vault edit inventory/group_vars/orchestrator_servers/vault.yml

# High verbosity
ansible-playbook playbooks/deploy.yml -vvvv

┌─────────────────────────────────────────────────────────────────────────┐
│ DOCUMENTATION                                                           │
└─────────────────────────────────────────────────────────────────────────┘

  📖 DEPLOYMENT_GUIDE.md          Full deployment guide
  📖 SETUP_SCRIPTS_EXPLAINED.md   Detailed setup.sh comparison
  📖 roles/*/                     Role documentation
  📖 playbooks/*.yml              Playbook documentation

═══════════════════════════════════════════════════════════════════════════

Need help? Run:
  $ python3 scripts/deploy_orchestrator.py

EOF
