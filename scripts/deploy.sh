#!/bin/bash
# ============================================================
# DEPLOY SCRIPT - Run via Semaphore or manually
# Usage: ./scripts/deploy.sh [inventory_file] [tags]
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="$SCRIPT_DIR/semaphore_config.env"

# Load configuration
if [[ -f "$CONFIG_FILE" ]]; then
    source "$CONFIG_FILE"
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║              DEPLOYING ORCHESTRATOR + GATEWAY                   ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Default values
INVENTORY="${1:-$PROJECT_DIR/inventory/production.yml}"
LIMIT="${2:-all}"
TAGS="${3:-}"

echo -e "${CYAN}📦 Configuration:${NC}"
echo "   Inventory: $INVENTORY"
echo "   Limit: $LIMIT"
echo "   Tags: ${TAGS:-all}"
echo ""

# Check if Ansible is available
if ! command -v ansible-playbook &> /dev/null; then
    echo -e "${RED}❌ Ansible not installed. Installing...${NC}"
    sudo apt-get update && sudo apt-get install -y ansible
fi

# Change to project directory
cd "$PROJECT_DIR"

# Run pre-flight checks
echo -e "${YELLOW}🔍 Running pre-flight checks...${NC}"
ansible all -i "$INVENTORY" -m ping --limit "$LIMIT" 2>/dev/null || true
echo ""

# Build ansible-playbook command
ANSIBLE_CMD="ansible-playbook -i $INVENTORY playbooks/deploy.yml --limit $LIMIT"

# Add tags if specified
if [[ -n "$TAGS" ]]; then
    ANSIBLE_CMD="$ANSIBLE_CMD --tags $TAGS"
fi

# Add verbosity for debugging (use -v, -vv, or -vvv)
if [[ "${DEBUG:-false}" == "true" ]]; then
    ANSIBLE_CMD="$ANSIBLE_CMD -vvv"
fi

echo -e "${GREEN}🚀 Starting deployment...${NC}"
echo "Command: $ANSIBLE_CMD"
echo ""

# Execute deployment
eval "$ANSIBLE_CMD"

# Check result
if [[ $? -eq 0 ]]; then
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                   DEPLOYMENT SUCCESS!                          ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
    
    # Show service status
    echo ""
    echo -e "${CYAN}📊 Service Status:${NC}"
    ansible all -i "$INVENTORY" -m shell -a "systemctl is-active go-ble-orchestrator gateway-dashboard" --limit "$LIMIT"
else
    echo ""
    echo -e "${RED}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║                   DEPLOYMENT FAILED!                           ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${YELLOW}💡 Debugging tips:${NC}"
    echo "   1. Check SSH connectivity: ssh $LINUX_USER@<target-ip>"
    echo "   2. Run with debug: DEBUG=true ./scripts/deploy.sh"
    echo "   3. Check logs: journalctl -u go-ble-orchestrator -f"
    exit 1
fi
