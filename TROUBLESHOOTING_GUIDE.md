# Practical Troubleshooting & Verification Guide

## Pre-Deployment Checklist (On Your Machine)

### 1. Verify Ansible Installation
```bash
# Check Ansible version
$ ansible --version
  ansible [core 2.14.0]
  python version = 3.11.0
  ✓ Should be 2.10+

# Check if ansible-vault available
$ ansible-vault --version
  ansible-vault [core 2.14.0]
  ✓ Should exist

# Check Python dependencies
$ python -m pip list | grep -E "ansible|paramiko|jinja2|pyyaml"
  ansible          2.14.0
  paramiko         3.0.0
  Jinja2           3.1.0
  PyYAML           6.0
  ✓ All present
```

### 2. Verify SSH Configuration
```bash
# Check SSH key exists
$ ls -l ~/.ssh/id_rsa
  -rw------- 1 user user 3434 Apr 01 12:00 ~/.ssh/id_rsa
  ✓ Permissions should be 600

# Test SSH connectivity to each server
$ ssh -i ~/.ssh/id_rsa ubuntu@10.0.1.100 "echo OK"
  OK
  ✓ Can connect

# Check sudo access (needed for Ansible)
$ ssh -i ~/.ssh/id_rsa ubuntu@10.0.1.100 "sudo whoami"
  root
  ✓ Can execute sudo without password
  (or have ssh key setup correctly)
```

### 3. Verify Binary Built
```bash
# Build binary on your machine
$ cd /path/to/CassiaConnectionTest/Cassia
$ CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o go-ble-orchestrator

# Verify it's a Linux binary
$ file go-ble-orchestrator
  go-ble-orchestrator: ELF 64-bit LSB executable, x86-64, version 1 (SYSV), dynamically linked
  ✓ Is Linux ELF binary (not Windows)

# Verify size is reasonable
$ ls -lh go-ble-orchestrator
  -rw-r--r-- 1 user user 16M Apr 01 12:00 go-ble-orchestrator
  ✓ Should be 15-20MB range

# Test running it locally (optional)
$ ./go-ble-orchestrator -help
  Usage of ./go-ble-orchestrator:
    -config string
        Path to config file (default "config.json")
  ✓ Binary works
```

### 4. Inventory & Configuration Validation
```bash
# Check inventory file
$ cat inventory/production.yml
  all:
    children:
      orchestrator_servers:
        hosts:
          prod-orchestrator-01:
            ansible_host: 10.0.1.100
          prod-orchestrator-02:
            ansible_host: 10.0.1.101

# Verify all hosts resolve
$ ansible-inventory -i inventory/production.yml --list | jq '.all.children.orchestrator_servers.hosts'
  ✓ Should show your hosts

# Verify group exists
$ ansible-inventory -i inventory/production.yml --graph
  ✓ Should see @all/@ungrouped/orchestrator_servers tree

# Test connectivity
$ ansible all -i inventory/production.yml -m ping --ask-vault-pass
  Vault password: ••••••••••
  10.0.1.100 | SUCCESS => { "ping": "pong" }
  10.0.1.101 | SUCCESS => { "ping": "pong" }
  ✓ Both servers reachable
```

### 5. Vault Validation
```bash
# Check vault file exists
$ test -f inventory/group_vars/orchestrator_servers/vault.yml && echo "EXISTS"
  EXISTS

# View vault contents (prompted for password)
$ ansible-vault view inventory/group_vars/orchestrator_servers/vault.yml
  Vault password: ••••••••••
  cassia_client_id: "lifesigns"
  cassia_client_secret: "secret123"
  ✓ Can decrypt successfully

# Verify no plaintext secrets in git
$ grep -r "ca04600dd2345948#" . --exclude-dir=.git
  (should find nothing - or only in vault.yml encrypted form)
  ✓ Secrets are protected
```

---

## Dry-Run: Test Without Making Changes

```bash
# Run playbook in check mode (safe preview)
$ ansible-playbook playbooks/deploy.yml \
    -i inventory/production.yml \
    --ask-vault-pass \
    -C

  Vault password: ••••••••••
  
  PLAY [Deploy BLE Orchestrator and MQTT]
  
  Gathering Facts
    10.0.1.100: ok
    10.0.1.101: ok
  
  PRE-TASKS
    Display deployment info: ok=2
    Validate prerequisites: ok=2
  
  ROLE: prerequisites
    Update system packages: changed=2
    Install required packages: changed=2
    Create app user: changed=2
    Create directories: changed=2
    Verify permissions: ok=2
  
  [... more output ...]
  
  PLAY RECAP
  ─────────
  10.0.1.100: ok=28 changed=24 unreachable=0 failed=0
  10.0.1.101: ok=28 changed=24 unreachable=0 failed=0

# What -C does:
# ✓ Reads all files
# ✓ Parses all templates
# ✓ Shows what WOULD change
# ✓ Makes NO actual changes to servers
# ✓ Perfect for validation before real run
```

---

## Actual Deployment

```bash
# Deploy for real
$ ansible-playbook playbooks/deploy.yml \
    -i inventory/production.yml \
    --ask-vault-pass

  Vault password: ••••••••••
  
  # Wait for completion (~2-5 minutes per server)
  # ... lots of output ...
  
  PLAY RECAP
  ─────────
  10.0.1.100: ok=28 changed=24 unreachable=0 failed=0
  10.0.1.101: ok=28 changed=24 unreachable=0 failed=0
  
  ✓ SUCCESS!
```

---

## Post-Deployment Verification

### On Your Machine (Control Node)

```bash
# Verify Ansible can still reach servers
$ ansible all -i inventory/production.yml -m ping --ask-vault-pass
  10.0.1.100 | SUCCESS => { "ping": "pong" }
  10.0.1.101 | SUCCESS => { "ping": "pong" }
  ✓ Connected

# Check services status via Ansible
$ ansible orchestrator_servers -i inventory/production.yml \
    -m systemd_service \
    -a "name=go-ble-orchestrator" \
    --ask-vault-pass
    
  10.0.1.100 | SUCCESS => {
    "status": {
      "ActiveState": "active",
      "UnitFileState": "enabled"
    }
  }
  10.0.1.101 | SUCCESS => {
    "status": {
      "ActiveState": "active",
      "UnitFileState": "enabled"
    }
  }
  ✓ Both services running
```

### On Each Target Server (SSH)

```bash
# SSH into server
$ ssh -i ~/.ssh/id_rsa ubuntu@10.0.1.100

# Check orchestrator service
ubuntu@prod-01:~$ sudo systemctl status go-ble-orchestrator
  ● go-ble-orchestrator.service - BLE Orchestrator Service
    Loaded: loaded (/etc/systemd/system/go-ble-orchestrator.service; enabled; vendor preset: enabled)
    Active: active (running) since Tue 2026-04-01 12:05:00 UTC; 2 min 30s ago
    Main PID: 2500 (go-ble-orchestrator)
    Tasks: 5
    Memory: 45.2M
    CPU: 0.2s
    CGroup: /system.slice/go-ble-orchestrator.service
            └─2500 /opt/orchestrator/bin/go-ble-orchestrator -config /opt/orchestrator/config/config.json
  
  ✓ Service running
  ✓ PID: 2500 (tracked by systemd)
  ✓ Memory: 45.2M (reasonable)
  ✓ Enabled on boot

# Check MQTT service
ubuntu@prod-01:~$ sudo systemctl status mosquitto
  ● mosquitto.service - Mosquitto MQTT Broker
    Loaded: loaded (/etc/mosquitto/mosquitto.service; enabled; vendor preset: enabled)
    Active: active (running) since Tue 2026-04-01 12:05:00 UTC; 2 min 30s ago
    Main PID: 1234 (mosquitto)
    Tasks: 3
    Memory: 1.2M
    CGroup: /system.slice/mosquitto.service
            └─1234 /usr/sbin/mosquitto -c /etc/mosquitto/mosquitto.conf
  
  ✓ Service running

# Check ports are listening
ubuntu@prod-01:~$ sudo netstat -tlnp | grep LISTEN
  tcp  0  0  0.0.0.0:8083    LISTEN  2500/go-ble-orch
  tcp  0  0  0.0.0.0:1883    LISTEN  1234/mosquitto
  
  ✓ Port 8083 (orchestrator) listening
  ✓ Port 1883 (MQTT) listening

# Test dashboard accessibility
ubuntu@prod-01:~$ curl http://localhost:8083/
  <!DOCTYPE html>
  <html>
  <head>
    <title>BLE Orchestrator Dashboard</title>
  ...
  
  ✓ Dashboard loads

# Check configuration
ubuntu@prod-01:~$ cat /opt/orchestrator/config/config.json | jq '.cassia'
  {
    "clientId": "lifesigns",
    "acDomain": "http://172.16.20.24",
    ...
  }
  
  ✓ Config deployed correctly

# Check logs
ubuntu@prod-01:~$ sudo journalctl -u go-ble-orchestrator -n 20
  Apr 01 12:05:00 prod-01 systemd[1]: Starting BLE Orchestrator Service...
  Apr 01 12:05:00 prod-01 systemd[1]: Started BLE Orchestrator Service.
  Apr 01 12:05:00 prod-01 go-ble-orchestrator[2500]: [INFO] Server starting on :8083
  Apr 01 12:05:01 prod-01 go-ble-orchestrator[2500]: [INFO] Connected to MQTT broker
  Apr 01 12:05:02 prod-01 go-ble-orchestrator[2500]: [DEBUG] Loaded 0 devices
  
  ✓ Service started cleanly
  ✓ Connected to MQTT
  ✓ Ready to serve

# Check file ownership/permissions
ubuntu@prod-01:~$ ls -la /opt/orchestrator/
  drwxr-xr-x 5 orcservice orcservice 4096 Apr 01 12:05 .
  drwxr-xr-x 3 root       root       4096 Apr 01 12:01 ..
  drwxr-xr-x 2 orcservice orcservice 4096 Apr 01 12:05 bin
  drwxr-xr-x 2 orcservice orcservice 4096 Apr 01 12:05 config
  drwxr-xr-x 2 orcservice orcservice 4096 Apr 01 12:05 data
  drwxr-xr-x 2 orcservice orcservice 4096 Apr 01 12:05 logs
  
  ✓ All owned by orcservice
  ✓ Permissions correct for unprivileged user
```

---

## Troubleshooting: Common Issues & Solutions

### Issue 1: "Service won't start"

**Error shown:**
```bash
$ sudo systemctl start go-ble-orchestrator
$ sudo systemctl status go-ble-orchestrator

  ● go-ble-orchestrator.service - BLE Orchestrator Service
    Active: failed (Result: exit-code)
    Main PID: -
    Process: 2500 ExecStart=/opt/orchestrator/bin/go-ble-orchestrator ... (code=exited, status=1)
```

**Diagnosis:**

```bash
# Check detailed logs
$ sudo journalctl -u go-ble-orchestrator -n 50
  Apr 01 12:05:00 prod-01 go-ble-orchestrator[2500]: Error: cannot load config.json
  Apr 01 12:05:00 prod-01 go-ble-orchestrator[2500]: Reason: file not found

# Check if binary exists
$ ls -la /opt/orchestrator/bin/go-ble-orchestrator
  ls: cannot access: No such file or directory
  ✗ Binary not copied

# Check if config exists
$ ls -la /opt/orchestrator/config/config.json
  ls: cannot access: No such file or directory
  ✗ Config not generated
```

**Solutions:**

```bash
# Rerun deployment specifically for orchestrator role
$ ansible-playbook playbooks/deploy.yml \
    -i inventory/production.yml \
    -l prod-orchestrator-01 \
    -t orchestrator \
    --ask-vault-pass
  ✓ Re-copies binary and deploys config

# Or manually re-copy
$ scp -i ~/.ssh/id_rsa go-ble-orchestrator ubuntu@10.0.1.100:/opt/orchestrator/bin/
$ ssh ubuntu@10.0.1.100 sudo chown orcservice:orcservice /opt/orchestrator/bin/go-ble-orchestrator
$ ssh ubuntu@10.0.1.100 sudo chmod 755 /opt/orchestrator/bin/go-ble-orchestrator
$ ssh ubuntu@10.0.1.100 sudo systemctl start go-ble-orchestrator
```

---

### Issue 2: "MQTT connection refused"

**Error in orchestrator logs:**
```bash
$ sudo journalctl -u go-ble-orchestrator
  go-ble-orchestrator[2500]: [ERROR] Failed to connect to MQTT broker: connection refused
  go-ble-orchestrator[2500]: [ERROR] Reconnecting in 5 seconds...
```

**Diagnosis:**

```bash
# Check if MQTT is running
$ sudo systemctl status mosquitto
  ● mosquitto.service
    Active: failed
  ✗ Not running

# Check MQTT port
$ sudo netstat -tlnp | grep 1883
  (nothing shown)
  ✗ Port not listening

# Check MQTT service logs
$ sudo journalctl -u mosquitto
  Apr 01 12:05:00 prod-01 mosquitto[1234]: Error: Config file has error
```

**Solutions:**

```bash
# Start MQTT service
$ sudo systemctl start mosquitto
$ sudo systemctl status mosquitto
  ✓ Should show active

# If still broken, check config
$ cat /etc/mosquitto/conf.d/orchestrator.conf
  listener 1883
  allow_anonymous true
  persistence true

# Redeploy MQTT config
$ ansible-playbook playbooks/deploy.yml \
    -i inventory/production.yml \
    -l prod-orchestrator-01 \
    -t mqtt \
    --ask-vault-pass

# Check again
$ sudo netstat -tlnp | grep mosquitto
  tcp  0  0  0.0.0.0:1883  LISTEN  1234/mosquitto
  ✓ Listening

# Restart orchestrator (will reconnect)
$ sudo systemctl restart go-ble-orchestrator
```

---

### Issue 3: "SSH key authentication fails"

**Error:**
```bash
$ ansible all -i inventory/production.yml -m ping
  10.0.1.100 | UNREACHABLE! => {
    "msg": "Failed to connect to the host via ssh: Permission denied (publickey)."
  }
```

**Diagnosis:**

```bash
# Test direct SSH
$ ssh -i ~/.ssh/id_rsa ubuntu@10.0.1.100 "echo OK"
  Permission denied (publickey).

# Check if key works
$ ssh-keygen -l -f ~/.ssh/id_rsa
  2048 SHA256:abc... /home/user/.ssh/id_rsa
  ✓ Key exists

# Check if key is in ssh-agent
$ ssh-add -l
  (empty list or not showing your key)
  ✗ Key not in agent
```

**Solutions:**

```bash
# Add key to SSH agent
$ ssh-add ~/.ssh/id_rsa
  Identity added: /home/user/.ssh/id_rsa
  ✓ Key now in agent

# Try Ansible again
$ ansible all -i inventory/production.yml -m ping
  10.0.1.100 | SUCCESS => { "ping": "pong" }
  ✓ Works now

# Alternatively, generate new key on server
$ ssh ubuntu@10.0.1.100
ubuntu@prod-01:~$ curl https://github.com/<your_username>.keys >> ~/.ssh/authorized_keys

# Or re-copy key
$ ssh-copy-id -i ~/.ssh/id_rsa.pub ubuntu@10.0.1.100
  Number of key(s) added: 1
  ✓ Key added to authorized_keys
```

---

### Issue 4: "Vault password incorrect"

**Error:**
```bash
$ ansible-playbook playbooks/deploy.yml --ask-vault-pass
  Vault password: ••••••••••
  
  fatal: [10.0.1.100]: FAILED! => {
    "msg": "error while decrypting vault-encrypted string"
  }
```

**Diagnosis:**

```bash
# Test vault access directly
$ ansible-vault view inventory/group_vars/orchestrator_servers/vault.yml
  Vault password: {WRONG_PASSWORD}
  ERROR! Decryption failed
  ✗ Password incorrect
```

**Solutions:**

```bash
# If you forgot password: Recreate vault file
# (Warning: old password will be lost)
$ rm inventory/group_vars/orchestrator_servers/vault.yml
$ ansible-vault create inventory/group_vars/orchestrator_servers/vault.yml
  New Vault password: ••••••••••
  Confirm Vault password: ••••••••••
  # Add your secrets again

# Or use password file (for CI/CD)
$ echo "my_vault_password" > ~/.vault_pass
$ chmod 600 ~/.vault_pass
$ ansible-playbook playbooks/deploy.yml \
    --vault-password-file ~/.vault_pass
  ✓ No password prompt
```

---

### Issue 5: "Port 8083 not responding"

**Error:**
```bash
$ curl http://10.0.1.100:8083/
  curl: (7) Failed to connect to 10.0.1.100 port 8083: Connection refused
```

**Diagnosis:**

```bash
# Check if service is running
$ sudo systemctl status go-ble-orchestrator
  ✗ Inactive or failed

# Check if port is being used by something else
$ sudo netstat -tlnp | grep 8083
  (nothing shown or different process)

# Check if firewall blocks it
$ sudo ufw status
  Status: active
  8083                       DENY   IN
  ✗ Port blocked by firewall

# Test locally on server
$ curl localhost:8083/
  curl: (7) Failed to connect to 127.0.0.1 port 8083
  ✗ Port not open even locally
```

**Solutions:**

```bash
# Restart service
$ sudo systemctl restart go-ble-orchestrator
$ sudo systemctl status go-ble-orchestrator
  ✓ Active

# Wait a moment for startup
$ sleep 2

# Test again
$ curl http://localhost:8083/
  ✓ Loads dashboard

# Open firewall (if applicable)
$ sudo ufw allow 8083
  Rule added
  # or with source restriction:
$ sudo ufw allow from 10.0.0.0/8 to any port 8083
  ✓ Port now accessible from 10.x network

# Test from another machine
$ curl http://10.0.1.100:8083/
  ✓ Dashboard loads
```

---

### Issue 6: "Process keeps restarting (restart loop)"

**Symptom:**
```bash
$ sudo journalctl -u go-ble-orchestrator
  [12:05:00] Started
  [12:05:02] Exited with code=1
  [12:05:07] Started
  [12:05:09] Exited with code=1
  [12:05:14] Started
  ... repeating pattern ...
```

**Diagnosis:**

```bash
# Check if it's a config error
$ cat /opt/orchestrator/config/config.json | jq '.' > /dev/null
  # If parsing error shown: JSON syntax wrong
  
# Check if MQTT is available
$ sudo systemctl status mosquitto
  ✗ Not running
  → Orchestrator can't connect, crashes

# Check if required file missing
$ ls -la /opt/orchestrator/frontend/
  ls: cannot access: No such file or directory
  ✗ Frontend not deployed
```

**Solutions:**

```bash
# Fix config JSON
$ sudo cat /opt/orchestrator/config/config.json | jq .
  (check for syntax errors)
$ sudo systemctl restart mosquitto  # Ensure MQTT running

# Re-deploy orchestrator role
$ ansible-playbook playbooks/deploy.yml \
    -i inventory/production.yml \
    -l prod-orchestrator-01 \
    -t orchestrator \
    --ask-vault-pass

# Verify all dependencies
$ sudo systemctl start mosquitto
$ sudo systemctl restart go-ble-orchestrator
$ sleep 3
$ sudo systemctl status go-ble-orchestrator
  ✓ Active (running)
  ✓ Restart count should stabilize

# Check restart limit hasn't been hit
$ systemctl status go-ble-orchestrator | grep "restart"
  # If many restarts: limit might be triggered
  # Reset with:
$ sudo systemctl reset-failed go-ble-orchestrator
$ sudo systemctl restart go-ble-orchestrator
```

---

## Verification Checklist

### Before Production

```bash
# Functional Tests
□ localhost:8083 responds with dashboard
□ curl http://server:8083/health returns 200
□ MQTT broker listening on port 1883
□ Can publish/subscribe to MQTT topics
□ Database file created at /opt/orchestrator/data/
□ Logs appear in journalctl

# Operational Tests
□ systemctl stop/start works
□ systemctl restart works
□ Service auto-starts after manual stop
□ Service survives test reboot
□ Configuration applies correctly
□ Ansible re-deploy is safe (idempotent)

# Security Tests  
□ Service runs as orcservice (non-root)
□ Config.json is readable only by orcservice
□ SSH keys are 600 permissions
□ Vault password is not in .git
□ No secrets in logs or journalctl

# Monitoring Tests
□ journalctl shows all startup messages
□ Error messages are clear and actionable
□ Resource usage reasonable (memory < 100M)
□ No excessive CPU usage at idle
□ Disk space adequate for logs
```

### After Deployment

```bash
# System Check
□ Both services active (running)
□ Both services enabled (boot startup)
□ No failed units (systemctl --failed empty)
□ Disk mount points available
□ Network connectivity to broker/API endpoints

# Application Check
□ Dashboard loads
□ MQTT publishing working
□ API calls to Nexus/Cassia successful
□ Database operations working
□ Device connections established

# Monitoring Check
□ journalctl contains no errors
□ systemd cgroups memory within limits
□ CPU not continuously at 100%
□ Disk I/O reasonable
□ Network connections established
```

---

## Emergency Procedures

### If Service Crashes & Won't Restart

```bash
# Emergency stop (disable auto-restart temporarily)
$ sudo systemctl mask go-ble-orchestrator
  # Creates /etc/systemd/system/go-ble-orchestrator.service.d/override.conf

# Investigate
$ sudo journalctl -u go-ble-orchestrator -n 100
  (find root cause)

# Fix issue
$ sudo nano /opt/orchestrator/config/config.json
  (fix config, save)

# Re-enable auto-restart
$ sudo systemctl unmask go-ble-orchestrator

# Start manually
$ sudo systemctl start go-ble-orchestrator
$ sudo systemctl status go-ble-orchestrator
```

### Rollback to Previous Version

```bash
# Via Ansible
$ ansible-playbook playbooks/rollback.yml --ask-vault-pass

# Manual rollback
$ sudo cp /opt/orchestrator/bin/go-ble-orchestrator.backup \
          /opt/orchestrator/bin/go-ble-orchestrator
$ sudo systemctl restart go-ble-orchestrator
```

### Complete File Restoration

```bash
# If entire /opt/orchestrator corrupted

# Stop service
$ sudo systemctl stop go-ble-orchestrator

# Restore from backup (if you have one)
$ sudo tar -xzf /backup/orchestrator-backup.tar.gz -C /

# Or redeploy entirely
$ ansible-playbook playbooks/deploy.yml \
    -i inventory/production.yml \
    -l prod-orchestrator-01 \
    --ask-vault-pass
```

---

## Performance Validation

```bash
# Check resource usage
$ watch -n 1 'systemctl status go-ble-orchestrator | grep -E "Memory|CPU|Tasks"'

# Expected baseline (idle):
#   Memory: ~45M
#   CPU: < 1%
#   Tasks: 5

# View long-term metrics
$ systemd-cgtop -n 10
  # See CPU % and memory for all services

# Monitor for memory leaks
$ (for i in {1..100}; do \
    echo "$(date): $(systemctl show -p MemoryCurrent go-ble-orchestrator |cut -d= -f2)"; \
    sleep 60; \
  done) > memory_log.txt

$ tail memory_log.txt
  # Check if memory grows continuously
  # If yes → investigate memory leak in app
```

---

## Updating Your Deployment

### Update Binary Only (No Config Changes)

```bash
# Build new binary on your machine
$ go build -o go-ble-orchestrator

# Redeploy (will backup old binary, copy new one, restart)
$ ansible-playbook playbooks/deploy.yml \
    -i inventory/production.yml \
    -t orchestrator \
    --ask-vault-pass
  ✓ Binary updated
  ✓ Old backed up
  ✓ Service restarted
```

### Update Configuration Only (No Binary Change)

```bash
# Update vars (e.g., new Cassia domain)
$ ansible-playbook playbooks/configure.yml \
    -i inventory/production.yml \
    -e "cassia_domain=http://new-domain.com" \
    --ask-vault-pass
  ✓ Config updated
  ✓ Service restarted
  ✓ Ready to serve
```

### Rollback if Update Breaks Things

```bash
$ ansible-playbook playbooks/rollback.yml \
    -i inventory/production.yml \
    --ask-vault-pass
  ✓ Previous binary restored
  ✓ Previous config restored
  ✓ Service restarted
```

