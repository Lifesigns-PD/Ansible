# Ansible Deployment Guide - BLE Orchestrator

## Overview

This Ansible deployment automates the installation and management of the BLE Orchestrator application across multiple Linux servers with Mosquitto MQTT broker integration.

## Prerequisites

### On Control Machine (your laptop/CI server)
```bash
# Install Ansible
pip install ansible boto3 botocore

# Generate SSH key (if needed)
ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa

# Build your Go binary first
cd /path/to/CassiaConnectionTest/Cassia
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o go-ble-orchestrator .
```

### On Target Servers
- Ubuntu 20.04+ or Debian 11+
- SSH access with sudo privileges
- Network access to Cassia AC and API endpoints

## Setup Instructions

### 1. **Prepare the Binary on Control Machine**

```bash
# From your workspace root
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o go-ble-orchestrator .

# Copy to ansible structure for deployment
mkdir -p ansible/binaries
cp go-ble-orchestrator ansible/binaries/
cp -r frontend ecg_metrics ansible/binaries/
```

### 2. **Configure Inventory**

Edit `inventory/production.yml`:
```yaml
prod-orchestrator-01:
  ansible_host: 10.0.1.100      # Your server IP
  app_version: "v1.1.4.1"

prod-orchestrator-02:
  ansible_host: 10.0.1.101
  app_version: "v1.1.4.1"
```

### 3. **Set Variables**

Edit `inventory/group_vars/orchestrator_servers/vars.yml`:
```yaml
app_home: "/opt/orchestrator"
binary_source_dir: "/path/to/CassiaConnectionTest/Cassia"
mqtt_broker: "tcp://localhost:1883"
```

### 4. **Secure Secrets with Vault**

```bash
# Create encrypted vault file
ansible-vault create inventory/group_vars/orchestrator_servers/vault.yml

# Edit it (will prompt for password)
ansible-vault edit inventory/group_vars/orchestrator_servers/vault.yml
```

Add these secrets:
```yaml
cassia_client_id: "lifesigns"
cassia_client_secret: "YOUR_SECRET_HERE"
config_password: "Config@2024"
api_endpoint: "https://nexus.api.lifesigns.us/gw/api/v1/public/external-device"
cassia_domain: "http://172.16.20.24"
```

### 5. **Set SSH Access**

```bash
# Copy your SSH key to target servers
ssh-copy-id -i ~/.ssh/id_rsa.pub ubuntu@10.0.1.100
ssh-copy-id -i ~/.ssh/id_rsa.pub ubuntu@10.0.1.101

# Test connectivity
ansible all -i inventory/production.yml -m ping --ask-vault-pass
```

## Deployment Commands

### **Initial Full Deployment**

```bash
# Dry run (test without making changes)
ansible-playbook playbooks/deploy.yml \
  -i inventory/production.yml \
  --ask-vault-pass \
  -C

# Actual deployment
ansible-playbook playbooks/deploy.yml \
  -i inventory/production.yml \
  --ask-vault-pass

# Deployment with verbose output
ansible-playbook playbooks/deploy.yml \
  -i inventory/production.yml \
  --ask-vault-pass \
  -vvv
```

### **Deploy Specific Server**

```bash
ansible-playbook playbooks/deploy.yml \
  -i inventory/production.yml \
  --ask-vault-pass \
  -l prod-orchestrator-01
```

### **Deploy Specific Component Only**

```bash
# Just prerequisites
ansible-playbook playbooks/deploy.yml \
  -i inventory/production.yml \
  --ask-vault-pass \
  -t prerequisites

# Just MQTT
ansible-playbook playbooks/deploy.yml \
  -i inventory/production.yml \
  --ask-vault-pass \
  -t mqtt

# Just orchestrator app
ansible-playbook playbooks/deploy.yml \
  -i inventory/production.yml \
  --ask-vault-pass \
  -t orchestrator
```

### **Update Configuration**

```bash
# Update config.json without redeploying binary
ansible-playbook playbooks/configure.yml \
  -i inventory/production.yml \
  --ask-vault-pass \
  -e "cassia_domain=http://new-domain"
```

### **Rollback to Previous Version**

```bash
# Rollback manually
ansible-playbook playbooks/rollback.yml \
  -i inventory/production.yml \
  --ask-vault-pass

# Rollback without confirmation prompt
ansible-playbook playbooks/rollback.yml \
  -i inventory/production.yml \
  --ask-vault-pass \
  -e "skip_confirm=true"
```

## Verification & Monitoring

### Check Service Status

```bash
# SSH into server
ssh ubuntu@10.0.1.100

# Check orchestrator service
sudo systemctl status go-ble-orchestrator

# Check MQTT broker
sudo systemctl status mosquitto

# View logs
sudo journalctl -u go-ble-orchestrator -f
sudo tail -f /var/log/mosquitto/mosquitto.log
```

### Health Checks

```bash
# Dashboard
curl http://10.0.1.100:8083/

# MQTT connectivity
mosquitto_sub -h 10.0.1.100 -t "ble/#" -C 1
```

### Verify with Ansible

```bash
# Ad-hoc service check
ansible orchestrator_servers -i inventory/production.yml -m systemd_service \
  -a "name=go-ble-orchestrator" --ask-vault-pass
```

## Directory Structure

```
ansible/
├── ansible.cfg              # Ansible configuration
├── inventory/
│   ├── production.yml       # Target hosts
│   └── group_vars/
│       └── orchestrator_servers/
│           ├── vars.yml     # Variables
│           └── vault.yml    # Encrypted secrets
├── roles/
│   ├── prerequisites/
│   │   └── tasks/main.yml
│   ├── orchestrator/
│   │   ├── tasks/main.yml
│   │   ├── handlers/main.yml
│   │   └── templates/
│   │       ├── config.json.j2
│   │       └── orchestrator.service.j2
│   └── mqtt/
│       ├── tasks/main.yml
│       └── templates/
│           └── mosquitto.conf.j2
├── playbooks/
│   ├── deploy.yml           # Initial deployment
│   ├── configure.yml        # Update config
│   └── rollback.yml         # Rollback version
└── binaries/                # Built Go binaries
    └── go-ble-orchestrator
```

## Troubleshooting

### Service won't start

```bash
# Check service logs
sudo journalctl -u go-ble-orchestrator -n 50

# Verify configuration
cat /opt/orchestrator/config/config.json | jq .

# Check permissions
ls -la /opt/orchestrator/
```

### MQTT connection issues

```bash
# Test MQTT broker
nc -zv 10.0.1.100 1883
mosquitto_pub -h 10.0.1.100 -t "test" -m "hello"

# Check broker logs
sudo tail -f /var/log/mosquitto/mosquitto.log
```

### Binary not found error

```bash
# Verify binary location on control machine
ls -la /path/to/CassiaConnectionTest/Cassia/go-ble-orchestrator

# Update binary_source_dir in vars.yml
# Use absolute path or relative to ansible directory
```

### Permission denied

```bash
# Ensure SSH key is added to agent
ssh-add ~/.ssh/id_rsa

# Verify sudo access
ansible all -i inventory/production.yml -m shell \
  -a "sudo whoami" --ask-vault-pass
```

## Advanced Usage

### Parallel Deployments

```bash
# Deploy to all servers simultaneously
ansible-playbook playbooks/deploy.yml \
  -i inventory/production.yml \
  --ask-vault-pass \
  -f 10  # forks=10
```

### Rolling Updates (One Server at a Time)

```bash
# Create a rolling deployment strategy
ansible-playbook playbooks/deploy.yml \
  -i inventory/production.yml \
  --ask-vault-pass \
  --serial=1
```

### Pre-deployment Checks

```bash
# Validate all playbooks
ansible-playbook playbooks/deploy.yml \
  --syntax-check

# Check connectivity
ansible all -i inventory/production.yml \
  -m ping --ask-vault-pass
```

### Generate Deployment Report

```bash
# Run with callback plugin for detailed report
ANSIBLE_STDOUT_CALLBACK=json \
ansible-playbook playbooks/deploy.yml \
  -i inventory/production.yml \
  --ask-vault-pass > deployment-report.json
```

## Security Considerations

1. **SSH Keys**: Use key-based authentication, not passwords
2. **Vault**: Always encrypt sensitive data with `ansible-vault`
3. **Firewall**: Restrict SSH (port 22) and MQTT (port 1883) to known IPs
4. **Service Hardening**: Systemd service runs as unprivileged user
5. **Audit Logs**: Check `ansible-deployment.log` for deployment history

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Deploy with Ansible
on: [push]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-go@v2
      - run: CGO_ENABLED=0 GOOS=linux go build -o go-ble-orchestrator
      - run: ansible-playbook playbooks/deploy.yml -i inventory/production.yml
```

## Quick Commands Reference

| Task | Command |
|------|---------|
| Deploy (dry-run) | `ansible-playbook playbooks/deploy.yml -C` |
| Deploy (real) | `ansible-playbook playbooks/deploy.yml` |
| Update config | `ansible-playbook playbooks/configure.yml` |
| Rollback | `ansible-playbook playbooks/rollback.yml` |
| Check status | `ansible orchestrator_servers -m systemd_service` |
| View logs | `ansible orchestrator_servers -m shell -a "journalctl -u go-ble-orchestrator"` |

