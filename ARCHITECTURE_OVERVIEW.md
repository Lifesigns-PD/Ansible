# Complete Deployment Architecture

## Your Deployment Stack

```
┌─────────────────────────────────────────────────────────────────────┐
│                    YOUR LOCAL MACHINE (Control)                     │
│                                                                     │
│  Python                                                             │
│  ├─ scripts/deploy_orchestrator.py    ← Interactive deployment tool
│  ├─ scripts/connectedMachines.py      ← List Tailscale machines
│  └─ scripts/.env                      ← Tailscale API credentials
│                                                                     │
│  Ansible                                                            │
│  ├─ ansible.cfg                       ← SSH/host config
│  ├─ inventory/production.yml          ← Server IPs & versions
│  ├─ inventory/group_vars/.../         ← Variables & secrets
│  └─ playbooks/                        ← deploy, configure, rollback
│                                                                     │
│  Source Code (for building)                                         │
│  └─ ../Cassia/                        ← Binary build location
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
        │                      │                        │
        ├─ SSH ───────────────┤                        │
        │                     │                        │
        ├─ Builds binaries ───┤ (Ansible copies) ──────┤
        │                     │                        │
        v                     v                        v
┌──────────────────────┐  ┌──────────────────────┐  ┌─────────┐
│ Tailscale Tailnet    │  │ Target Servers       │  │ GitHub  │
│ ===================  │  │ (Ubuntu 22.04+)      │  │ API     │
│                      │  │                      │  │ Releases│
│ VPN Overlay Network  │  │ ┌──────────────────┐ │  │ Repo    │
│                      │  │ │ /opt/            │ │  │         │
│ 100.64.10.0/8        │  │ ├─ orchestrator/   │ │  │ ✓ Fast  │
│ ==================== │  │ │  ├─ bin/         │ │  │ ✓ Latest│
│ prod-orch-01         │  │ │  ├─ config/      │ │  │ ✓ Auto- │
│ prod-orch-02         │  │ │  ├─ data/        │ │  │   download
│ test-server          │  │ │  └─ logs/        │ │  │         │
│ ...                  │  │ ├─ gateway-dash   │ │  │ Used by:|
│                      │  │ └─ mosquitto/      │ │  │ setup.sh│
│ (Listed by          │  │ /etc/systemd/       │ │  │         │
│  deploy_orchestr     │  │ ├─ go-ble-orch...  │ │  └─────────┘
│  ator.py)           │  │ └─ gateway-dash...  │ │
│                      │  │ /var/lib/mosquitto │ │
└──────────────────────┘  │ /var/log/          │ │
                          │                    │ │
                          │ Services:          │ │
                          │ ├─ orchestrator    │ │
                          │ ├─ mosquitto       │ │
                          │ └─ gateway-dash    │ │
                          │                    │ │
                          │ Configuration:     │ │
                          │ ├─ config.json     │ │
                          │ ├─ mqtt broker     │ │
                          │ └─ systemd units   │ │
                          └────────────────────┘ │
                                                  │
                          Deployment Source: ────┘
                          Option A: Ansible (pre-built binaries)
                          Option B: GitHub API (auto-download)
                          Option C: Hybrid (both)
```

---

## The Two Deployment Paths

### Path 1: Ansible (Recommended for Production)

```
STEP 1: Prepare                     STEP 2: Build                STEP 3: Deploy
═════════════════════════════════════════════════════════════════════════════

Control Machine:                    Control Machine:            Target Servers:
├─ python3 setup.sh              ├─ cd ../Cassia            Ansible does:
│  ├─ Validate Ansible           │  ├─ go build ...         ├─ Copy binaries
│  ├─ Create vault               │  ├─ Build ecg_metrics    ├─ Create user
│  └─ Test SSH                   │  └─ Result: Binaries     ├─ Create dirs
│                                │                          ├─ Install MQTT
├─ Edit inventory                ├─ Pre-built binaries      ├─ Deploy app
├─ Edit vars.yml                 │  now ready for use       ├─ Create systemd
├─ Create vault.yml              │                          ├─ Start services
│                                                           └─ Health check
└─ Ready for deployment


Command:
$ ansible-playbook playbooks/deploy.yml --ask-vault-pass


Result:
✓ All servers identical version
✓ Full audit trail in logs
✓ Rollback capability
✓ Reproducible deployments
```

### Path 2: GitHub Auto-Download (Recommended for Testing)

```
STEP 1: No prep needed!          STEP 2: Deploy              STEP 3: Verify
═════════════════════════════════════════════════════════════════════════════

.env has API key        SSH to target server:       Server installed:
Tailnet configured      $ ssh ubuntu@100.64.10.5    ├─ go-ble-orchestrator
                       
                        Target server runs:          ├─ gateway-dashboard
(No binary build        $ curl ... | sudo bash
needed!)                                            └─ Both start on boot

                        Server fetches from GitHub:
                        ├─ Query latest release
                        ├─ Download zip
                        ├─ Extract
                        └─ Run installer


Command:
$ ssh ubuntu@100.64.10.5 'bash -c "curl -fsSL https://raw.github.../setup.sh | sudo bash"'

OR:
$ python3 scripts/deploy_orchestrator.py → Select Method 2


Result:
✓ Always latest version
✓ No pre-staging needed
✓ One-liner deployment
✓ Slower (includes download)
```

---

## Flow: Using the Interactive Tool

```
USER RUNS:
$ python3 scripts/deploy_orchestrator.py
│
├─ PHASE 1: DISCOVERY
│  ├─ Read scripts/.env
│  │  └─ TAILSCALE_API_KEY=tskey-api-...
│  │  └─ Tailscale-tailnet-name=T48tog1ov911CNTRL
│  │
│  └─ Query Tailscale API
│     (GET /api/v2/tailnet/{tailnet}/devices)
│     │
│     └─ Returns:
│        ├─ prod-orchestrator-01: 100.64.10.5  (🟢 Online)
│        ├─ prod-orchestrator-02: 100.64.10.6  (🟢 Online)
│        └─ test-server:          100.64.10.10 (🔴 Offline)
│
├─ PHASE 2: USER INTERACTION
│  ├─ Display machines
│  │  "1. prod-orchestrator-01 (100.64.10.5) 🟢 Online"
│  │
│  ├─ Ask: Select machine (1-3)?
│  │  User: 1
│  │
│  ├─ Ask: SSH Username?
│  │  User: ubuntu
│  │
│  └─ Ask: SSH Password?
│     User: ****
│
├─ PHASE 3: METHOD SELECTION
│  ├─ Display 3 options:
│  │  1. Ansible (pre-built)
│  │  2. GitHub (auto-download)
│  │  3. Hybrid (both)
│  │
│  └─ Generate command based on choice
│
└─ PHASE 4: EXECUTION
   ├─ Show command
   ├─ Ask: Execute? (y/n)
   │  User: y
   │
   └─ Run command
      ├─ SSH to server
      ├─ Execute deployment
      └─ Display results


DEPLOYMENT COMMAND GENERATED:

Method 1 (Ansible):
$ cd /path/to/ansible && \
  ansible-playbook playbooks/deploy.yml \
  -i inventory/production.yml \
  -e ansible_host=100.64.10.5 \
  -e ansible_user=ubuntu \
  -e ansible_password=*** \
  --ask-vault-pass -vv

Method 2 (GitHub):
$ ssh ubuntu@100.64.10.5 'bash -c "
  curl -fsSL https://raw.github.../setup.sh | sudo bash
"'

Method 3 (Hybrid):
$ cd /path/to/ansible && \
  ansible-playbook playbooks/deploy.yml \
  (same as Method 1)
```

---

## Configuration Files Reference

### scripts/.env
```bash
# Tailscale credentials (get from https://app.tailscale.com/settings/keys)
TAILSCALE_API_KEY=tskey-api-kKExQPNGLY11CNTRL-...
Tailscale-tailnet-name=T48tog1ov911CNTRL
```

Loaded by:
- `deploy_orchestrator.py` (uses API to list machines)
- `connectedMachines.py` (uses local Tailscale CLI)

### inventory/production.yml
```yaml
orchestrator_servers:
  hosts:
    prod-orchestrator-01:
      ansible_host: 100.64.10.5           # Tailscale IP
      app_version: "v1.1.4.1"
    prod-orchestrator-02:
      ansible_host: 100.64.10.6
      app_version: "v1.1.4.1"
```

Used by:
- Ansible playbooks (which servers to deploy to)
- `deploy_orchestrator.py` (fallback if Tailscale unavailable)

### inventory/group_vars/orchestrator_servers/vars.yml
```yaml
app_name: "go-ble-orchestrator"
service_port: 8083
cassia_domain: "http://172.16.20.24"
mqtt_broker: "tcp://localhost:1883"
binary_source_dir: "/path/to/Cassia"      # ← Update this!
```

Used by:
- Ansible roles (template interpolation)
- Jinja2 templates for config generation

### inventory/group_vars/orchestrator_servers/vault.yml
```yaml
ansible_password: "ubuntu_password"
config_password: "Config@2024"
```

Encrypted with: `ansible-vault`

Access: `ansible-vault view vault.yml` (asks for password)

### ansible.cfg
```ini
[defaults]
inventory = inventory/production.yml
remote_user = ubuntu
private_key_file = ~/.ssh/id_rsa
```

Controls:
- Default inventory file
- SSH user & key
- Privilege escalation settings
- Fact caching for performance

---

## Data Flow During Deployment

### Ansible Deployment
```
1. Read configuration
   │
   ├─ Load inventory/production.yml
   │  └─ Get server IPs: 100.64.10.5, 100.64.10.6
   │
   ├─ Load vars.yml
   │  └─ Get: binary_source_dir, cassia_domain, etc.
   │
   └─ Load vault.yml (encrypted)
      └─ Get: credentials, passwords

2. Connect via SSH
   │
   ├─ SSH to 100.64.10.5 (ubuntu@)
   ├─ Authenticate (key or vault password)
   └─ Open SSH session

3. Execute role: prerequisites
   │
   ├─ apt update/upgrade
   ├─ Create orcservice user
   └─ mkdir -p /opt/orchestrator/{bin,config,data,logs}

4. Execute role: mqtt
   │
   ├─ apt install mosquitto
   ├─ Deploy /etc/mosquitto/conf.d/orchestrator.conf
   │  (from templates/mosquitto.conf.j2)
   └─ systemctl start mosquitto

5. Execute role: orchestrator
   │
   ├─ Copy binary
   │  src: /path/to/Cassia/go-ble-orchestrator
   │  dest: /opt/orchestrator/bin/
   │
   ├─ Copy frontend
   │  src: /path/to/Cassia/frontend/
   │  dest: /opt/orchestrator/frontend/
   │
   ├─ Generate config.json
   │  from: templates/config.json.j2
   │  vars: cassia_domain, mqtt_broker, etc.
   │  dest: /opt/orchestrator/config/config.json
   │
   ├─ Create systemd service
   │  from: templates/orchestrator.service.j2
   │  dest: /etc/systemd/system/go-ble-orchestrator.service
   │
   ├─ systemctl daemon-reload
   ├─ systemctl enable go-ble-orchestrator
   ├─ systemctl start go-ble-orchestrator
   └─ Health check

6. Post-deployment verification
   │
   ├─ systemctl status go-ble-orchestrator
   ├─ systemctl status mosquitto
   └─ curl http://localhost:8083/health

7. Repeat for 100.64.10.6
```

### GitHub Deployment
```
1. SSH to target
   │
   └─ ssh ubuntu@100.64.10.5

2. Run setup.sh script
   │
   ├─ Fetch from GitHub
   │  GET /repos/Lifesigns-PD/orchestrator-releases/releases/latest
   │  └─ Returns: zip URL + version
   │
   ├─ Download zip
   │  curl -o Installationsmain.zip
   │  └─ ~50-100 MB
   │
   ├─ Unzip
   │  └─ Extract to temp directory
   │
   ├─ Run installer
   │  ./DeviceManager_Install.sh
   │  └─ Creates systemd service
   │
   └─ Optional: Setup gateway-dashboard
      ├─ Fetch latest from GitHub
      ├─ Download + unzip
      └─ Create systemd service
```

---

## Summary Table

| Aspect | Ansible | GitHub |
|--------|---------|--------|
| **Who deploys** | You (from control machine) | Target server (self-service) |
| **Where binaries come from** | Your local build | GitHub releases |
| **Setup time** | Medium | Quick |
| **Deployment time** | ~2 min/server | ~3-5 min/server |
| **For multiple servers** | ✅ One command deploys all | ❌ Must SSH to each |
| **Version consistency** | ✅ All same | ❌ May vary |
| **Audit trail** | ✅ ansible.log | ⚠ Only terminal output |
| **Rollback** | ✅ Built-in | ❌ Manual |
| **Network requirements** | SSH to servers | GitHub API access |
| **Pre-staging** | ✅ Build binaries first | ❌ Not needed |
| **Best for** | Production multi-server | Single server testing |

---

## File Organization

```
ansible/                          ← The Ansible deployment system
├─ setup.sh                        ← Run FIRST (one-time local setup)
├─ QUICK_REFERENCE.sh             ← This file (cheat sheet)
├─ DEPLOYMENT_GUIDE.md            ← Complete deployment guide
├─ SETUP_SCRIPTS_EXPLAINED.md     ← Detailed comparison
├─ ansible.cfg                    ← Ansible configuration
├─ requirements.txt               ← Python dependencies
│
├─ scripts/
│  ├─ deploy_orchestrator.py      ← Interactive deployment tool
│  ├─ connectedMachines.py        ← List Tailscale machines
│  └─ .env                        ← Tailscale API credentials
│
├─ inventory/                     ← Where, what, and how
│  ├─ production.yml              ← Target servers
│  └─ group_vars/orchestrator_servers/
│     ├─ vars.yml                 ← Variables
│     └─ vault.yml                ← Secrets (encrypted)
│
├─ playbooks/                     ← Orchestration logic
│  ├─ deploy.yml                  ← Main deployment
│  ├─ configure.yml               ← Config updates
│  └─ rollback.yml                ← Emergency rollback
│
├─ roles/                         ← Reusable deployment tasks
│  ├─ prerequisites/
│  │  └─ tasks/main.yml           ← System setup
│  ├─ mqtt/
│  │  ├─ tasks/main.yml           ← MQTT installation
│  │  └─ templates/
│  │     └─ mosquitto.conf.j2     ← MQTT configuration
│  └─ orchestrator/
│     ├─ handlers/main.yml        ← Service restarts
│     ├─ tasks/main.yml           ← App deployment
│     └─ templates/
│        ├─ config.json.j2        ← App config template
│        └─ orchestrator.service.j2 ← Systemd unit
│
└─ orchestrator setup/            ← Standalone installer (for GitHub method)
   └─ setup.sh                    ← Run on target server directly
```

---

## Next Steps

1. **Read**: [QUICK_REFERENCE.sh](QUICK_REFERENCE.sh)
2. **Read**: [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)
3. **Setup**: Follow the "Quick Start Checklist"
4. **Deploy**: Choose your method
   - Option A: `python3 scripts/deploy_orchestrator.py` (interactive)
   - Option B: `ansible-playbook playbooks/deploy.yml` (manual Ansible)
   - Option C: `ssh ... | bash` (GitHub method)
5. **Verify**: Check logs and service status
6. **Maintain**: Use `playbooks/configure.yml` for updates, `rollback.yml` for emergency

---

## Key Concepts

- **Tailscale**: VPN overlay network - allows secure SSH without port forwarding
- **Ansible**: Infrastructure as Code - describe desired state, Ansible enforces it
- **Roles**: Reusable sets of tasks (prerequisites, mqtt, orchestrator)
- **Handlers**: Tasks that only run when notified (service restarts)
- **Templates**: Jinja2 files that get rendered with variables (j2 files)
- **Vault**: Ansible's encryption system for secrets
- **Fact Caching**: Speed optimization - cache host info so playbook runs faster
- **Tags**: Selectively run parts of playbooks
- **Idempotency**: Safe to run multiple times, only makes changes if needed

---

That's it! You now have:
✅ Three deployment methods
✅ Interactive tool to guide you
✅ Complete documentation
✅ Quick reference guides
✅ Automatic Tailscale machine discovery
✅ Production-ready Ansible infrastructure

Happy deploying! 🚀
