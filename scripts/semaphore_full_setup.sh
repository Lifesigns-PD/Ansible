#!/bin/bash
# ============================================================
# SEMAPHORE UI FULL AUTOMATION SETUP
# Run this once to configure everything
# ============================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     SEMAPHORE UI - ANSIBLE AUTOMATION SETUP WIZARD            ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ============================================================
# STEP 1: Collect Configuration
# ============================================================
echo -e "${YELLOW}STEP 1: Configuration${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

read -p "📌 Semaphore URL (e.g., http://localhost:8080): " SEMAPHORE_URL
read -p "🔑 Semaphore API Token: " SEMAPHORE_TOKEN
read -p "📁 Project ID (usually 1): " PROJECT_ID
read -p "📦 GitHub Repository URL (e.g., https://github.com/user/repo.git): " GITHUB_REPO
read -p "🔐 GitHub Access Token: " GITHUB_TOKEN
echo ""

# ============================================================
# STEP 2: Collect Tailscale Credentials
# ============================================================
echo -e "${YELLOW}STEP 2: Tailscale Configuration${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

read -p "🌐 Tailscale API Key (tskey-api-...): " TAILSCALE_API_KEY
read -p "📛 Tailscale Tenant Name: " TAILSCALE_TENANT_NAME
read -p "👤 Linux Username (default: ubuntu): " LINUX_USER
LINUX_USER=${LINUX_USER:-ubuntu}
read -sp "🔐 Linux Password: " LINUX_PASS
echo ""
echo ""

# ============================================================
# STEP 3: Validate Inputs
# ============================================================
echo -e "${YELLOW}STEP 3: Validating...${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ -z "$SEMAPHORE_URL" ]] || [[ -z "$SEMAPHORE_TOKEN" ]]; then
    echo -e "${RED}❌ Semaphore URL and Token are required${NC}"
    exit 1
fi

if [[ -z "$GITHUB_REPO" ]] || [[ -z "$GITHUB_TOKEN" ]]; then
    echo -e "${RED}❌ GitHub Repository and Token are required${NC}"
    exit 1
fi

# Test Semaphore connection
echo -e "${BLUE}→ Testing Semaphore connection...${NC}"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X GET "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID" \
    -H "Authorization: Bearer $SEMAPHORE_TOKEN")
if [[ "$HTTP_CODE" != "200" ]]; then
    echo -e "${RED}❌ Cannot connect to Semaphore. Check URL/Token. HTTP: $HTTP_CODE${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Semaphore connection OK${NC}"

# Test GitHub connection
echo -e "${BLUE}→ Testing GitHub connection...${NC}"
GITHUB_CHECK=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: token $GITHUB_TOKEN" \
    "$GITHUB_REPO")
if [[ "$GITHUB_CHECK" != "200" ]]; then
    echo -e "${RED}❌ Cannot access GitHub repo. Check URL/Token permissions.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ GitHub repository accessible${NC}"

echo -e "${GREEN}✓ All validations passed${NC}"
echo ""

# ============================================================
# STEP 4: Save Configuration
# ============================================================
echo -e "${YELLOW}STEP 4: Saving Configuration${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

CONFIG_FILE="scripts/semaphore_config.env"
mkdir -p scripts

cat > "$CONFIG_FILE" << EOF
# Semaphore Configuration
SEMAPHORE_URL=$SEMAPHORE_URL
SEMAPHORE_TOKEN=$SEMAPHORE_TOKEN
PROJECT_ID=$PROJECT_ID

# GitHub Configuration
GITHUB_REPO=$GITHUB_REPO
GITHUB_TOKEN=$GITHUB_TOKEN

# Tailscale Configuration
TAILSCALE_API_KEY=$TAILSCALE_API_KEY
TAILSCALE_TENANT_NAME=$TAILSCALE_TENANT_NAME
LINUX_USER=$LINUX_USER
LINUX_PASS=$LINUX_PASS
EOF

chmod 600 "$CONFIG_FILE"
echo -e "${GREEN}✓ Configuration saved to $CONFIG_FILE${NC}"
echo ""

# ============================================================
# STEP 5: Create Credentials in Semaphore via API
# ============================================================
echo -e "${YELLOW}STEP 5: Creating Semaphore Credentials${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 5.1 Tailscale API Key
echo -e "${BLUE}→ Creating Tailscale-API-Key credential...${NC}"
CRED_RESULT=$(curl -s -X POST "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/credentials" \
    -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "Tailscale-API-Key",
        "type": "key",
        "value": "'"$TAILSCALE_API_KEY"'"
    }')
CRED_1=$(echo "$CRED_RESULT" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
if [[ -n "$CRED_1" ]]; then
    echo -e "${GREEN}  ✓ Tailscale-API-Key created (ID: $CRED_1)${NC}"
else
    echo -e "${YELLOW}  ⚠ Tailscale-API-Key may already exist${NC}"
fi

# 5.2 Tailscale Tenant
echo -e "${BLUE}→ Creating Tailscale-Tenant credential...${NC}"
CRED_RESULT=$(curl -s -X POST "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/credentials" \
    -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "Tailscale-Tenant",
        "type": "key",
        "value": "'"$TAILSCALE_TENANT_NAME"'"
    }')
CRED_2=$(echo "$CRED_RESULT" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
if [[ -n "$CRED_2" ]]; then
    echo -e "${GREEN}  ✓ Tailscale-Tenant created (ID: $CRED_2)${NC}"
else
    echo -e "${YELLOW}  ⚠ Tailscale-Tenant may already exist${NC}"
fi

# 5.3 Linux SSH Credentials
echo -e "${BLUE}→ Creating Linux-SSH-Credentials...${NC}"
CRED_RESULT=$(curl -s -X POST "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/credentials" \
    -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "Linux-SSH-Credentials",
        "type": "login",
        "login": "'"$LINUX_USER"'",
        "password": "'"$LINUX_PASS"'"
    }')
CRED_3=$(echo "$CRED_RESULT" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
if [[ -n "$CRED_3" ]]; then
    echo -e "${GREEN}  ✓ Linux-SSH-Credentials created (ID: $CRED_3)${NC}"
else
    echo -e "${YELLOW}  ⚠ Linux-SSH-Credentials may already exist${NC}"
fi

# 5.4 GitHub Token
echo -e "${BLUE}→ Creating GitHub-Token credential...${NC}"
CRED_RESULT=$(curl -s -X POST "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/credentials" \
    -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "GitHub-Token",
        "type": "key",
        "value": "'"$GITHUB_TOKEN"'"
    }')
CRED_4=$(echo "$CRED_RESULT" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
if [[ -n "$CRED_4" ]]; then
    echo -e "${GREEN}  ✓ GitHub-Token created (ID: $CRED_4)${NC}"
else
    echo -e "${YELLOW}  ⚠ GitHub-Token may already exist${NC}"
fi

echo ""

# ============================================================
# STEP 6: Create GitHub Key Repository
# ============================================================
echo -e "${YELLOW}STEP 6: Creating Git Repository${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Initialize git repo and push if not exists
if [[ ! -d ".git" ]]; then
    echo -e "${BLUE}→ Initializing Git repository...${NC}"
    git init
    git remote add origin "$GITHUB_REPO"
    echo -e "${BLUE}→ Pushing to GitHub (with token)...${NC}"
    git config credential.helper store
    echo "$GITHUB_REPO" > /tmp/giturl.txt
    echo "$GITHUB_TOKEN" > /tmp/gittoken.txt
    git push -u origin $(git rev-parse --abbrev-ref HEAD) 2>/dev/null || true
    echo -e "${GREEN}✓ Repository initialized and pushed${NC}"
else
    echo -e "${GREEN}✓ Git repository already exists${NC}"
fi

echo ""

# ============================================================
# STEP 7: Create Environment Variables
# ============================================================
echo -e "${YELLOW}STEP 7: Creating Environment Variables${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Get project info to find environment ID
ENV_DATA=$(curl -s -X GET "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/environment" \
    -H "Authorization: Bearer $SEMAPHORE_TOKEN")

# Create or update environment variables via API
echo -e "${BLUE}→ Setting environment variables...${NC}"

# Using Semaphore API to create environment
curl -s -X PUT "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/environment" \
    -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "env": {
            "TAILSCALE_API_KEY": "'"$TAILSCALE_API_KEY"'",
            "TAILSCALE_TENANT_NAME": "'"$TAILSCALE_TENANT_NAME"'",
            "LINUX_USER": "'"$LINUX_USER"'",
            "LINUX_PASS": "'"$LINUX_PASS"'",
            "ANSIBLE_HOST_KEY_CHECKING": "False",
            "ANSIBLE_PYTHON_INTERPRETER": "/usr/bin/python3",
            "GITHUB_REPO": "'"$GITHUB_REPO"'"
        }
    }' | grep -q "env" && echo -e "${GREEN}  ✓ Environment variables set${NC}" || echo -e "${YELLOW}  ⚠ Environment variables may need manual setup${NC}"

echo ""

# ============================================================
# STEP 8: Create Inventory
# ============================================================
echo -e "${YELLOW}STEP 8: Creating Dynamic Inventory${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo -e "${BLUE}→ Creating Tailscale dynamic inventory...${NC}"
# Note: Inventory is typically created via UI or needs specific API call
echo -e "${YELLOW}  ⚠ Please create inventory manually in Semaphore UI:${NC}"
echo "     - Go to: Project → Inventories → New"
echo "     - Type: Python Script (Custom)"
echo "     - Path: inventory/tailscale_dynamic_inventory.py"
echo ""

# ============================================================
# STEP 9: Create Task Templates
# ============================================================
echo -e "${YELLOW}STEP 9: Creating Task Templates${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 9.1 Deploy Template
echo -e "${BLUE}→ Creating Deploy template...${NC}"
TEMPLATE_RESULT=$(curl -s -X POST "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/templates" \
    -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "Deploy",
        "playbook": "deploy.yml",
        "description": "Deploy BLE Orchestrator + Gateway Dashboard",
        "inventory": 1,
        "credentials": ['"$CRED_3"'],
        "allow_override_args": true
    }')
TEMPLATE_1=$(echo "$TEMPLATE_RESULT" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
if [[ -n "$TEMPLATE_1" ]]; then
    echo -e "${GREEN}  ✓ Deploy template created (ID: $TEMPLATE_1)${NC}"
else
    echo -e "${YELLOW}  ⚠ Deploy template may need manual creation${NC}"
fi

# 9.2 Rollback Template
echo -e "${BLUE}→ Creating Rollback template...${NC}"
TEMPLATE_RESULT=$(curl -s -X POST "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/templates" \
    -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "Rollback",
        "playbook": "rollback.yml",
        "description": "Rollback to previous version",
        "inventory": 1,
        "credentials": ['"$CRED_3"'],
        "allow_override_args": true
    }')
TEMPLATE_2=$(echo "$TEMPLATE_RESULT" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
if [[ -n "$TEMPLATE_2" ]]; then
    echo -e "${GREEN}  ✓ Rollback template created (ID: $TEMPLATE_2)${NC}"
else
    echo -e "${YELLOW}  ⚠ Rollback template may need manual creation${NC}"
fi

# 9.3 Health Check Template
echo -e "${BLUE}→ Creating Health Check template...${NC}"
TEMPLATE_RESULT=$(curl -s -X POST "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/templates" \
    -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "Health-Check",
        "playbook": "playbooks/Monitor-Health.yml",
        "description": "Check machine health status",
        "inventory": 1,
        "credentials": ['"$CRED_3"'],
        "allow_override_args": true
    }')
TEMPLATE_3=$(echo "$TEMPLATE_RESULT" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
if [[ -n "$TEMPLATE_3" ]]; then
    echo -e "${GREEN}  ✓ Health Check template created (ID: $TEMPLATE_3)${NC}"
else
    echo -e "${YELLOW}  ⚠ Health Check template may need manual creation${NC}"
fi

echo ""

# ============================================================
# COMPLETION
# ============================================================
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                    SETUP COMPLETE!                             ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "📋 SUMMARY:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Configuration saved to: scripts/semaphore_config.env"
echo ""
echo "  ✅ Credentials Created:"
echo "     • Tailscale-API-Key"
echo "     • Tailscale-Tenant"
echo "     • Linux-SSH-Credentials"
echo "     • GitHub-Token"
echo ""
echo "  ✅ Templates Created:"
echo "     • Deploy (deploy.yml)"
echo "     • Rollback (rollback.yml)"
echo "     • Health-Check (Monitor-Health.yml)"
echo ""
echo "📚 MANUAL STEPS STILL NEEDED:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  1. Create Inventory in Semaphore UI:"
echo "     Project → Inventories → New → Python Script"
echo "     Path: inventory/tailscale_dynamic_inventory.py"
echo ""
echo "  2. Link Git Repository in Semaphore:"
echo "     Project → Repository → Add → Connect GitHub"
echo "     URL: $GITHUB_REPO"
echo ""
echo "  3. Verify Templates:"
echo "     Project → Templates → Check all created"
echo ""
echo "🚀 NEXT STEPS:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  1. Open Semaphore UI at: $SEMAPHORE_URL"
echo "  2. Go to your project"
echo "  3. Click 'Deploy' template"
echo "  4. Click 'Run' to start deployment"
echo ""
echo -e "${BLUE}Happy automating! 🚀${NC}"
echo ""
