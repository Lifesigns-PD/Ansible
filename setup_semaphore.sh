#!/bin/bash
# Semaphore Orchestrator Dashboard - Quick Start
# This script helps setup the Semaphore integration

set -e

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║    Semaphore Orchestrator Integration - Quick Setup            ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# ============================================================================
# CONFIGURATION - Load from .env if exists
# ============================================================================

echo "📋 Step 1: Environment Configuration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Try to load from .env file
ENV_FILE="scripts/.env"
if [[ -f "$ENV_FILE" ]]; then
    echo "✓ Found .env file. Loading credentials..."
    TAILSCALE_API_KEY=$(grep -E "Tailscale-tailnet-apikey|TAILSCALE_API_KEY" "$ENV_FILE" | cut -d= -f2 | tr -d ' ')
    TAILSCALE_TENANT_NAME=$(grep -E "Tailscale-tailnet-name|TAILSCALE_TENANT_NAME" "$ENV_FILE" | cut -d= -f2 | tr -d ' ')
    LINUX_PASS=$(grep -E "linux_user_pass|LINUX_PASS" "$ENV_FILE" | cut -d= -f2 | tr -d ' ')
    echo "✓ Loaded Tailscale API Key"
    echo "✓ Loaded Tailscale Tenant Name"
    echo "✓ Loaded Linux Password"
    echo ""
else
    echo "⚠️  .env file not found. You'll need to enter credentials manually."
    echo ""
fi

echo "Please provide Semaphore configuration:"
echo ""

read -p "📌 Semaphore API URL (e.g., http://localhost:8085): " SEMAPHORE_URL
read -p "🔑 Semaphore API Token (from Settings): " SEMAPHORE_TOKEN
read -p "📞 Semaphore Project ID (usually 1): " PROJECT_ID

# Ask for Tailscale credentials only if not loaded from .env
if [[ -z "$TAILSCALE_API_KEY" ]]; then
    read -p "🌐 Tailscale API Key: " TAILSCALE_API_KEY
fi
if [[ -z "$TAILSCALE_TENANT_NAME" ]]; then
    read -p "📛 Tailscale Tenant Name: " TAILSCALE_TENANT_NAME
fi

# Ask for Linux credentials only if not loaded from .env
read -p "👤 Linux Username (default: ubuntu): " LINUX_USER
LINUX_USER=${LINUX_USER:-ubuntu}
if [[ -z "$LINUX_PASS" ]]; then
    read -sp "🔐 Linux Password: " LINUX_PASS
    echo ""
fi
echo ""

# ============================================================================
# VALIDATE INPUTS
# ============================================================================

echo "✓ Configuration received. Validating..."
echo ""

if [[ -z "$SEMAPHORE_URL" ]] || [[ -z "$SEMAPHORE_TOKEN" ]] || [[ -z "$PROJECT_ID" ]]; then
    echo "❌ Error: Semaphore configuration is required"
    exit 1
fi

if [[ -z "$TAILSCALE_API_KEY" ]] || [[ -z "$TAILSCALE_TENANT_NAME" ]]; then
    echo "❌ Error: Tailscale configuration is required"
    exit 1
fi

echo ""
echo "✓ All inputs validated"
echo ""

# ============================================================================
# CREATE CREDENTIALS VIA API
# ============================================================================

echo "📝 Step 2: Creating Semaphore Credentials"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Credential 1: Tailscale API Key
echo "  Creating: Tailscale-API-Key..."
CRED_1=$(curl -s -X POST "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/credentials" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Tailscale-API-Key",
    "type": "key",
    "value": "'"$TAILSCALE_API_KEY"'"
  }' | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)

if [[ -z "$CRED_1" ]]; then
    echo "  ⚠️  Could not create Tailscale API Key credential (may already exist)"
else
    echo "  ✓ Created with ID: $CRED_1"
fi

# Credential 2: Tailscale Tenant
echo "  Creating: Tailscale-Tenant..."
CRED_2=$(curl -s -X POST "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/credentials" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Tailscale-Tenant",
    "type": "key",
    "value": "'"$TAILSCALE_TENANT_NAME"'"
  }' | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)

if [[ -z "$CRED_2" ]]; then
    echo "  ⚠️  Could not create Tailscale Tenant credential (may already exist)"
else
    echo "  ✓ Created with ID: $CRED_2"
fi

# Credential 3: Linux SSH
echo "  Creating: Linux-SSH-Credentials..."
CRED_3=$(curl -s -X POST "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/credentials" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Linux-SSH-Credentials",
    "type": "login",
    "login": "'"$LINUX_USER"'",
    "password": "'"$LINUX_PASS"'"
  }' | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)

if [[ -z "$CRED_3" ]]; then
    echo "  ⚠️  Could not create Linux SSH credential (may already exist)"
else
    echo "  ✓ Created with ID: $CRED_3"
fi

echo ""

# ============================================================================
# SUMMARY & NEXT STEPS
# ============================================================================

echo "✅ Step 3: Setup Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📋 CREDENTIALS CREATED:"
echo "  • Tailscale-API-Key"
echo "  • Tailscale-Tenant"
echo "  • Linux-SSH-Credentials"
echo ""
echo "📚 NEXT STEPS:"
echo ""
echo "1. Add Dynamic Inventory:"
echo "   → Semaphore UI → Project → Inventories → New"
echo "   → Name: Tailscale-Devices"
echo "   → Type: Inventory Plugin (Python Script)"
echo "   → Copy contents from: inventory/tailscale_dynamic_inventory.py"
echo ""
echo "2. Create Task Templates:"
echo "   → Semaphore UI → Project → Templates → New"
echo "   → Use these playbooks:"
echo "     • playbooks/Dashboard-Orchestrator.yml (Discovery)"
echo "     • playbooks/LogViewer-JSON.yml (Log Search)"
echo "     • playbooks/Monitor-Health.yml (Health Check)"
echo ""
echo "3. Configure Environment Variables:"
echo "   → Semaphore UI → Project → Environment Variables"
echo "   → Add:"
echo "     TAILSCALE_API_KEY=<value>"
echo "     TAILSCALE_TENANT_NAME=<value>"
echo "     LINUX_USER=$LINUX_USER"
echo "     LINUX_PASS=<value>"
echo "     ANSIBLE_HOST_KEY_CHECKING=False"
echo ""
echo "4. Test:"
echo "   → Select Orchestrator-Dashboard template"
echo "   → Click Run Template"
echo "   → Check output for discovered machines"
echo ""
echo "📖 For detailed setup, see: SEMAPHORE_SETUP_GUIDE.md"
echo ""
echo "🚀 Ready to use Semaphore for Orchestrator management!"
echo ""
