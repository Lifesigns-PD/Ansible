# Ansible Deployment Architecture

## High-Level Workflow

```
┌─────────────────────────────────────────────────────────────┐
│           CONTROL MACHINE (Your Laptop/CI Server)          │
│                                                              │
│  1. Build Binary (CGO_ENABLED=0 GOOS=linux go build)       │
│  2. Prepare Ansible playbooks & inventory                   │
│  3. Execute: ansible-playbook playbooks/deploy.yml          │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      │ SSH with Vault
                      │ Encrypted Secrets
                      ▼
┌─────────────────────────────────────────────────────────────┐
│             PRODUCTION SERVER (Linux)                       │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Prerequisites Role                                  │   │
│  │ • Install packages (curl, wget, ca-certificates)   │   │
│  │ • Create app user (orcservice:orcservice)           │   │
│  │ • Create /opt/orchestrator structure                │   │
│  │ • Set proper permissions                            │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                  │
│                          ▼                                  │
│  ┌──────────────────────────────────────┬──────────────┐  │
│  │ MQTT Broker                          │ Orchestrator │  │
│  │ (Mosquitto)                          │ App          │  │
│  │                                      │              │  │
│  │ • Port 1883 (MQTT)                   │ • Port 8083  │  │
│  │ • Port 9001 (WebSocket)              │ • Binary:    │  │
│  │ • Allow anonymous connections         │   /opt/...  │  │
│  │ • Data persistence in /var/lib/...   │ • Config JSON│  │
│  │                                      │ • Frontend   │  │
│  │ systemd: mosquitto.service           │ • Runs as    │  │
│  │                                      │   orcservice │  │
│  │                                      │              │  │
│  │                                      │ systemd:     │  │
│  │                                      │ go-ble-...   │  │
│  └──────────────────────────────────────┴──────────────┘  │
│                                                              │
│  Data Flow:                                                 │
│  Devices ──BLE──▶ Cassia AC ──HTTP──▶ Orchestrator         │
│                                             │               │
│                                             ▼               │
│  Orchestrator ──MQTT──▶ Mosquitto ──MQTT──▶ Subscribers    │
│      │                                                      │
│      └──────HTTP──▶ Nexus API (Cloud)                      │
│                                                              │
│  Logs: /opt/orchestrator/logs/                              │
│  Data: /opt/orchestrator/data/                              │
└─────────────────────────────────────────────────────────────┘
```

## Deployment Roles & Responsibilities

### 1. **Prerequisites Role**
Prepares the target system for application deployment.

**Tasks:**
- Package updates and installation
- User/group creation for service isolation
- Directory structure creation with proper permissions
- SELinux (if applicable) context setup

**Idempotent:** ✓ Yes - Safe to run multiple times

### 2. **MQTT Role**
Deploys and configures Mosquitto broker for pub/sub messaging.

**Tasks:**
- Install Mosquitto from apt repository
- Configure listener on port 1883
- Enable persistence
- Start and enable service

**Dependencies:** Prerequisites

**Idempotent:** ✓ Yes

### 3. **Orchestrator Role**
Deploys the main Go application and dependencies.

**Tasks:**
- Copy binary from control machine
- Copy frontend assets and utilities
- Generate config.json from template (Jinja2)
- Create systemd service file
- Start and verify service health

**Dependencies:** Prerequisites, MQTT

**Idempotent:** ✓ Yes with backups

## Configuration Management

### Dynamic Configuration via Jinja2 Templates

**config.json.j2** variables:
```yaml
{{ app_version }}              # Version string
{{ api_endpoint }}             # Cloud API URL
{{ cassia_domain }}            # Cassia AC URL
{{ cassia_client_id }}         # From vault
{{ cassia_client_secret }}     # From vault (encrypted)
{{ mqtt_broker }}              # MQTT connection string
{{ app_data_path }}            # Database path
{{ config_password }}          # Admin password from vault
```

### Secrets Management

```
Vault Encrypted Storage
    ↓
ansible-vault decrypt (on-demand during playbook)
    ↓
Populate Jinja2 templates
    ↓
Deploy to target (never stored in plaintext on disk)
```

## Deployment Strategies

### 1. **Fresh Installation**
```bash
ansible-playbook playbooks/deploy.yml
# Deploys everything from scratch
# Creates users, directories, services
```

### 2. **Configuration Update Only**
```bash
ansible-playbook playbooks/configure.yml \
  -e "cassia_domain=http://new-domain"
# Updates config.json
# Performs backup
# Restarts service
```

### 3. **Blue-Green Deployment**
```bash
# Deploy new version on prod-01 first
ansible-playbook playbooks/deploy.yml -l prod-orchestrator-01

# Test production-01
# If good, deploy to prod-02
ansible-playbook playbooks/deploy.yml -l prod-orchestrator-02
```

### 4. **Rollback**
```bash
ansible-playbook playbooks/rollback.yml
# Restores from .backup files
# Reverts to previous binary & config
```

## Service Dependencies

```
go-ble-orchestrator service
    ↑
    requires
    ↓
mosquitto service (always running)
    ↑
    requires
    ↓
network.target (system boot dependency)
```

**Systemd configuration:**
```ini
[Unit]
After=network.target mosquitto.service
Wants=mosquitto.service
Restart=on-failure
```

This ensures:
1. MQTT starts before orchestrator
2. If MQTT fails, orchestrator restarts until it's back
3. Service survives system reboots

## Data Management

### File Locations

| Component | Path | Owner | Permissions |
|-----------|------|-------|-------------|
| Binary | `/opt/orchestrator/bin/go-ble-orchestrator` | orcservice:orcservice | 0755 |
| Config | `/opt/orchestrator/config/config.json` | orcservice:orcservice | 0644 |
| Database | `/opt/orchestrator/data/unified_orchestrator.db` | orcservice:orcservice | 0644 |
| Logs | `/opt/orchestrator/logs/` | orcservice:orcservice | 0755 |
| Frontend | `/opt/orchestrator/frontend/` | orcservice:orcservice | 0755 |

### Backup Strategy

**Automatic Backups:**
- Before updating config: `config.json.backup`
- Before deploying binary: `go-ble-orchestrator.backup`

**Manual Backup:**
```bash
ansible orchestrator_servers -m shell \
  -a "tar -czf /tmp/orchestrator-backup-$(date +%s).tar.gz /opt/orchestrator"
```

## Verification Flow

```
Post-Deployment Checks:
    ↓
1. Service Status (systemd)
    ├─ Is go-ble-orchestrator active?
    └─ Is mosquitto active?
    ↓
2. Network Connectivity
    ├─ Port 8083 listening (orchestrator)?
    └─ Port 1883 listening (MQTT)?
    ↓
3. Application Health
    └─ GET http://server:8083/ → 200/404
    ↓
4. Configuration Validation
    ├─ config.json syntax valid?
    └─ All environment variables set?
    ↓
✓ Deployment Success
```

## Security Model

### Process Isolation
- Service runs as unprivileged user (orcservice)
- Cannot modify system files
- Cannot access other user data

### Network Isolation (Optional)
```bash
# Restrict MQTT to local only
listener 1883 127.0.0.1

# Expose dashboard on specific subnet
IP_BIND=10.0.1.100
```

### Credential Management
- All secrets in `vault.yml` (encrypted)
- Never logged to plaintext files
- Ansible facts don't expose vault vars
- Config.json contains only decrypted values on target

## Monitoring & Alerts (Optional)

### Systemd Service Health
```bash
# Auto-restart on failure
Restart=on-failure
RestartSec=5
```

### Logging
- systemd journal: `journalctl -u go-ble-orchestrator`
- MQTT logs: `/var/log/mosquitto/mosquitto.log`
- App logs: `/opt/orchestrator/logs/`

### Health Endpoint
```bash
curl http://server:8083/health
# Returns service status and dependencies
```

## Troubleshooting Decision Tree

```
Service not starting?
├─ Check systemd status: systemctl status go-ble-orchestrator
├─ Check logs: journalctl -u go-ble-orchestrator -n 50
├─ Verify config.json syntax: jq . config.json
└─ Check MQTT: systemctl status mosquitto

Config out of date?
├─ Run configure.yml to regenerate
└─ Check /opt/orchestrator/config/config.json.backup

Need to go back?
└─ Run rollback.yml

Performance issues?
├─ Check MQTT broker: systemctl status mosquitto
├─ Monitor system resources: top, free, df
└─ Review app logs for errors
```

## Updating to New Versions

### Workflow
1. Build new binary on control machine
2. Update `app_version` variable
3. Run deploy playbook (creates .backup automatically)
4. Verify new version works
5. Keep backups for rollback

### Version Matrix
```
Version   | Binary Name | Config Format | Migration
v1.1.3    | go-ble-orc  | config.json   | ✓
v1.1.4    | go-ble-orc  | config.json   | ✓
v1.1.4.1  | go-ble-orc  | config.json   | ✓
```

## Scaling Considerations

### Single Server
```
Production Ready:
├─ Orchestrator + MQTT on same machine
├─ Handles up to 50+ concurrent devices
├─ 2GB RAM minimum
└─ 10GB disk (for logs rotation)
```

### Multiple Servers
```
Distributed Setup:
├─ prod-01: MQTT broker (centralized)
├─ prod-02: Orchestrator + local persistence
└─ prod-03: Load-balanced orchestrator

Update orchestrator_servers group_vars to:
  mqtt_host: "prod-01"  (shared broker)
```

### Kubernetes (Future)
Values would translate to:
- Roles → Init containers
- Tasks → Pod startup sequence
- Templates → ConfigMap generation
- Secrets → Kubernetes Secrets

