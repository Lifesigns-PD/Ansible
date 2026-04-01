#!/bin/bash
# Quick setup script for Ansible deployment

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== BLE Orchestrator Ansible Setup ===${NC}"

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Python3 is required but not installed.${NC}"
    exit 1
fi

# Check if Ansible is installed
if ! command -v ansible &> /dev/null; then
    echo -e "${YELLOW}Installing Ansible...${NC}"
    pip install ansible
fi

# Check if ansible-vault is available
if ! command -v ansible-vault &> /dev/null; then
    echo -e "${RED}Ansible vault not found.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Ansible is installed${NC}"

# Create necessary directories
mkdir -p inventory/group_vars/orchestrator_servers
mkdir -p roles/{prerequisites,orchestrator,mqtt}/{tasks,templates,handlers}
mkdir -p playbooks
mkdir -p binaries

echo -e "${GREEN}✓ Directory structure created${NC}"

# Check if vault file exists
if [ ! -f "inventory/group_vars/orchestrator_servers/vault.yml" ]; then
    echo -e "${YELLOW}Creating vault file for secrets...${NC}"
    ansible-vault create inventory/group_vars/orchestrator_servers/vault.yml
fi

echo -e "${GREEN}✓ Vault file ready${NC}"

# Test connectivity
read -p "Enter target server IPs (comma-separated): " server_ips
IFS=',' read -ra servers <<< "$server_ips"

echo -e "${YELLOW}Testing connectivity...${NC}"
for server in "${servers[@]}"; do
    server=${server// /}  # Remove spaces
    if ansible "$server" -i "inventory/production.yml" -m ping --ask-vault-pass 2>/dev/null; then
        echo -e "${GREEN}✓ Connected to $server${NC}"
    else
        echo -e "${RED}✗ Failed to connect to $server${NC}"
    fi
done

# Validate playbooks
echo -e "${YELLOW}Validating playbooks...${NC}"
ansible-playbook playbooks/deploy.yml --syntax-check
ansible-playbook playbooks/configure.yml --syntax-check
ansible-playbook playbooks/rollback.yml --syntax-check

echo -e "${GREEN}✓ All playbooks are valid${NC}"

echo -e "${GREEN}=== Setup Complete ===${NC}"
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Update inventory/production.yml with your server IPs"
echo "2. Update inventory/group_vars/orchestrator_servers/vars.yml"
echo "3. Add secrets to inventory/group_vars/orchestrator_servers/vault.yml"
echo "4. Build your binary: CGO_ENABLED=0 GOOS=linux go build -o go-ble-orchestrator"
echo "5. Run deployment: ansible-playbook playbooks/deploy.yml --ask-vault-pass"
