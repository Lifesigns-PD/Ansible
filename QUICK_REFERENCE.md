# Ansible Deployment - Quick Reference

## Installation

```bash
# Install Ansible and dependencies
pip install -r requirements.txt

# Or individual packages
pip install ansible paramiko jinja2 pyyaml
```

## Initial Setup

```bash
# Run setup script
bash setup.sh

# Or manual setup
mkdir -p ansible/{roles,playbooks,inventory/group_vars/orchestrator_servers}

# Create vault for secrets
ansible-vault create inventory/group_vars/orchestrator_servers/vault.yml
ansible-vault edit inventory/group_vars/orchestrator_servers/vault.yml
```

## Build Binary

```bash
# Build Linux binary
cd /path/to/CassiaConnectionTest/Cassia
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o go-ble-orchestrator

# Verify binary
file go-ble-orchestrator
./go-ble-orchestrator --help
```

## SSH Key Setup

```bash
# Generate key (one time)
ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N ""

# Copy to all servers
for ip in 10.0.1.100 10.0.1.101; do
    ssh-copy-id -i ~/.ssh/id_rsa.pub ubuntu@$ip
done

# Test connectivity
ansible all -i inventory/production.yml -m ping --ask-vault-pass
```

## Deployment Commands

### Dry Run (Safe Preview)
```bash
ansible-playbook playbooks/deploy.yml --ask-vault-pass -C
```

### Full Deployment
```bash
ansible-playbook playbooks/deploy.yml --ask-vault-pass
```

### Deploy Single Server
```bash
ansible-playbook playbooks/deploy.yml -l prod-orchestrator-01 --ask-vault-pass
```

### Deploy Single Component
```bash
# Prerequisites only
ansible-playbook playbooks/deploy.yml -t prerequisites --ask-vault-pass

# MQTT only
ansible-playbook playbooks/deploy.yml -t mqtt --ask-vault-pass

# Orchestrator only
ansible-playbook playbooks/deploy.yml -t orchestrator --ask-vault-pass
```

### Update Configuration
```bash
# Update all config values
ansible-playbook playbooks/configure.yml --ask-vault-pass

# Update specific parameter
ansible-playbook playbooks/configure.yml \
  -e "cassia_domain=http://new-domain" \
  --ask-vault-pass
```

### Rollback
```bash
ansible-playbook playbooks/rollback.yml --ask-vault-pass
```

## Verification Commands

### Check Service Status
```bash
# All servers
ansible orchestrator_servers -m systemd_service \
  -a "name=go-ble-orchestrator" --ask-vault-pass

# Specific server
ansible prod-orchestrator-01 -m systemd_service \
  -a "name=go-ble-orchestrator" --ask-vault-pass
```

### Check MQTT Status
```bash
ansible orchestrator_servers -m systemd_service \
  -a "name=mosquitto" --ask-vault-pass
```

### View Logs
```bash
# Orchestrator logs
ansible orchestrator_servers -m shell \
  -a "sudo journalctl -u go-ble-orchestrator -n 50" \
  --ask-vault-pass

# MQTT logs
ansible orchestrator_servers -m shell \
  -a "sudo tail -f /var/log/mosquitto/mosquitto.log" \
  --ask-vault-pass
```

### Check Disk Space
```bash
ansible orchestrator_servers -m shell \
  -a "df -h" --ask-vault-pass
```

### Check Process
```bash
ansible orchestrator_servers -m shell \
  -a "ps aux | grep go-ble-orchestrator" \
  --ask-vault-pass
```

## Vault Management

### Create Vault File
```bash
ansible-vault create inventory/group_vars/orchestrator_servers/vault.yml
```

### Edit Vault File
```bash
ansible-vault edit inventory/group_vars/orchestrator_servers/vault.yml
```

### View Encrypted File (read-only)
```bash
ansible-vault view inventory/group_vars/orchestrator_servers/vault.yml
```

### Encrypt Existing File
```bash
ansible-vault encrypt existing_file.yml
```

### Decrypt for Editing
```bash
ansible-vault decrypt existing_file.yml
# edit...
ansible-vault encrypt existing_file.yml
```

## Troubleshooting Commands

### Validate Syntax
```bash
ansible-playbook playbooks/deploy.yml --syntax-check
ansible-playbook playbooks/configure.yml --syntax-check
```

### Run with Verbose Output
```bash
ansible-playbook playbooks/deploy.yml -vvv --ask-vault-pass
```

### Debug Specific Task
```bash
ansible-playbook playbooks/deploy.yml \
  -t orchestrator \
  -vvv \
  --ask-vault-pass
```

### SSH Directly (for testing)
```bash
ssh -i ~/.ssh/id_rsa ubuntu@10.0.1.100

# Check directories
ls -la /opt/orchestrator/

# Check service
sudo systemctl status go-ble-orchestrator

# View config
cat /opt/orchestrator/config/config.json | jq .
```

### Test MQTT Connection
```bash
# From control machine (if mosquitto-clients installed)
mosquitto_pub -h 10.0.1.100 -t "test" -m "hello"
mosquitto_sub -h 10.0.1.100 -t "test" -C 1

# From target server
nc -zv localhost 1883
```

## Advanced Usage

### Parallel Deployment (all servers at once)
```bash
ansible-playbook playbooks/deploy.yml \
  --ask-vault-pass \
  -f 10  # 10 parallel forks
```

### Rolling Deployment (one at a time)
```bash
ansible-playbook playbooks/deploy.yml \
  --ask-vault-pass \
  --serial=1
```

### List Hosts from Inventory
```bash
ansible-inventory -i inventory/production.yml --list
ansible-inventory -i inventory/production.yml --host prod-orchestrator-01
```

### Run Custom Command on All Servers
```bash
ansible orchestrator_servers -m shell \
  -a "df -h /opt/orchestrator" \
  --ask-vault-pass
```

### Generate Inventory Graph
```bash
ansible-inventory -i inventory/production.yml --graph
```

## File Management

### Copy File to Servers
```bash
ansible orchestrator_servers -m copy \
  -a "src=/local/path/file dest=/remote/path/" \
  --ask-vault-pass
```

### Fetch File from Servers
```bash
ansible orchestrator_servers -m fetch \
  -a "src=/remote/path/file dest=./backups/" \
  --ask-vault-pass
```

### Backup All Servers
```bash
ansible orchestrator_servers -m shell \
  -a "tar -czf /tmp/backup-$(date +%s).tar.gz /opt/orchestrator" \
  --ask-vault-pass
```

## Performance Tips

1. **Use fact caching** (already in ansible.cfg)
   ```ini
   fact_caching = jsonfile
   fact_caching_timeout = 86400
   ```

2. **Enable pipelining** (already in ansible.cfg)
   ```ini
   pipelining = true
   ```

3. **Increase parallelism** for large deployments
   ```bash
   ansible-playbook playbooks/deploy.yml -f 20
   ```

4. **Use gather_facts: no** in roles that don't need it
   ```yaml
   gather_facts: no
   ```

## Common Issues & Fixes

| Issue | Solution |
|-------|----------|
| Service won't start | Check: systemctl status go-ble-orchestrator; journalctl -n 50 |
| Config not updated | Run configure.yml; check file permissions |
| MQTT connection refused | Verify mosquitto is running; check port 1883 |
| SSH permission denied | ssh-copy-id; verify SSH key; check ~/.ssh/authorized_keys |
| Vault password wrong | Re-enter password; check caps lock |
| Service crashes | Check journalctl logs; verify config.json syntax with jq |

## Environment Variables

```bash
# Use vault password from file (for CI/CD)
ANSIBLE_VAULT_PASSWORD_FILE=~/.vault_pass ansible-playbook deploy.yml

# Control verbosity
ANSIBLE_VERBOSITY=3 ansible-playbook deploy.yml

# Skip fact gathering (faster)
ANSIBLE_GATHERING=explicit ansible-playbook deploy.yml

# Increase timeout
ANSIBLE_SSH_PIPELINING=true ANSIBLE_TIMEOUT=60 ansible-playbook deploy.yml
```

## Security Checklist

- [ ] Vault password is strong (20+ chars)
- [ ] SSH keys have proper permissions (600)
- [ ] Vault file is in .gitignore
- [ ] No plaintext secrets in logs
- [ ] Service runs as unprivileged user
- [ ] Firewall restricts SSH access
- [ ] Backups are encrypted

