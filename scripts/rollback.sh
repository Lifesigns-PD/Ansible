#!/bin/bash
# ============================================================
# ROLLBACK SCRIPT - Restore previous version
# Usage: ./scripts/rollback.sh [inventory_file] [host]
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
echo -e "${BLUE}║                    ROLLBACK OPERATION                           ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

INVENTORY="${1:-$PROJECT_DIR/inventory/production.yml}"
LIMIT="${2:-all}"

# Change to project directory
cd "$PROJECT_DIR"

# Confirm before proceeding
echo -e "${YELLOW}⚠️  WARNING: This will restore the previous backup!${NC}"
echo ""
echo -e "${CYAN}Target: $LIMIT${NC}"
echo -e "${CYAN}Inventory: $INVENTORY${NC}"
echo ""

read -p "Continue with rollback? (yes/no): " CONFIRM

if [[ "$CONFIRM" != "yes" ]]; then
    echo -e "${YELLOW}Rollback cancelled.${NC}"
    exit 0
fi

echo ""
echo -e "${YELLOW}🔄 Starting rollback...${NC}"
echo ""

# Run rollback playbook
ansible-playbook -i "$INVENTORY" playbooks/rollback.yml --limit "$LIMIT"

# Check result
if [[ $? -eq 0 ]]; then
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                  ROLLBACK SUCCESS!                            ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
else
    echo ""
    echo -e "${RED}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║                  ROLLBACK FAILED!                             ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════════════════════════════╝${NC}"
    exit 1
fi
