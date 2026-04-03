# Semaphore REST API Reference

Complete API documentation for Orchestrator Dashboard automation in Semaphore.

## 🔐 Authentication

All API requests require a Bearer token:

```bash
curl -H "Authorization: Bearer YOUR_API_TOKEN" https://semaphore.example.com/api/...
```

### Get API Token

1. **Semaphore UI** → Settings → API Tokens
2. Click **Create Token**
3. Set expiration & permissions
4. Copy token (shown only once)

```bash
# Save token for use
export SEMAPHORE_TOKEN="xxx_your_token_xxx"
export SEMAPHORE_URL="http://localhost:3000"  # or your IP
```

---

## 📋 Core Endpoints

### Base URL
```
http://localhost:3000/api/v2/
```

### Authentication Header
```
Authorization: Bearer <token>
Content-Type: application/json
```

---

## 🏢 Projects

### List All Projects
```bash
curl -X GET "$SEMAPHORE_URL/api/v2/projects" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN"
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "Orchestrator",
    "description": "Machine monitoring",
    "created": "2024-04-01T10:00:00Z"
  }
]
```

### Get Project by ID
```bash
curl -X GET "$SEMAPHORE_URL/api/v2/projects/1" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN"
```

### Create Project
```bash
curl -X POST "$SEMAPHORE_URL/api/v2/projects" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Orchestrator",
    "description": "Tailscale machine management"
  }'
```

---

## 🔑 Credentials

### List Credentials
```bash
curl -X GET "$SEMAPHORE_URL/api/v2/projects/1/credentials" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN"
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "Tailscale-API-Key",
    "type": "key",
    "created": "2024-04-01T10:00:00Z"
  },
  {
    "id": 2,
    "name": "Linux-SSH-Creds",
    "type": "login",
    "created": "2024-04-01T10:00:00Z"
  }
]
```

### Create API Key Credential
```bash
curl -X POST "$SEMAPHORE_URL/api/v2/projects/1/credentials" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Tailscale-API-Key",
    "type": "key",
    "value": "tskey-api-XXXXXXXXXX"
  }'
```

**Response:**
```json
{
  "id": 1,
  "name": "Tailscale-API-Key",
  "type": "key",
  "created": "2024-04-03T14:30:00Z"
}
```

### Create SSH Key Credential
```bash
curl -X POST "$SEMAPHORE_URL/api/v2/projects/1/credentials" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "SSH-Key",
    "type": "ssh_key",
    "secret": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
  }'
```

### Create Login Credential (Username/Password)
```bash
curl -X POST "$SEMAPHORE_URL/api/v2/projects/1/credentials" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Linux-SSH-Creds",
    "type": "login",
    "login": "ubuntu",
    "password": "your_password"
  }'
```

### Get Credential by ID
```bash
curl -X GET "$SEMAPHORE_URL/api/v2/projects/1/credentials/1" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN"
```

### Update Credential
```bash
curl -X PUT "$SEMAPHORE_URL/api/v2/projects/1/credentials/1" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Tailscale-API-Key",
    "type": "key",
    "value": "tskey-api-XXXXXXXX"
  }'
```

### Delete Credential
```bash
curl -X DELETE "$SEMAPHORE_URL/api/v2/projects/1/credentials/1" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN"
```

---

## 📦 Inventories

### List Inventories
```bash
curl -X GET "$SEMAPHORE_URL/api/v2/projects/1/inventories" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN"
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "Tailscale-Devices",
    "type": "static",
    "created": "2024-04-01T10:00:00Z"
  }
]
```

### Create Inventory (Static)
```bash
curl -X POST "$SEMAPHORE_URL/api/v2/projects/1/inventories" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Tailscale-Devices",
    "type": "static",
    "inventory": "all:\n  hosts:\n    machine1:\n      ansible_host: 100.x.x.x"
  }'
```

### Create Inventory (Dynamic Plugin)
```bash
curl -X POST "$SEMAPHORE_URL/api/v2/projects/1/inventories" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Tailscale-Devices",
    "type": "file",
    "inventory": "/ansible/inventory/tailscale_dynamic_inventory.py"
  }'
```

### Get Inventory by ID
```bash
curl -X GET "$SEMAPHORE_URL/api/v2/projects/1/inventories/1" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN"
```

### Update Inventory
```bash
curl -X PUT "$SEMAPHORE_URL/api/v2/projects/1/inventories/1" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Tailscale-Devices-Updated",
    "type": "static",
    "inventory": "..."
  }'
```

### Delete Inventory
```bash
curl -X DELETE "$SEMAPHORE_URL/api/v2/projects/1/inventories/1" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN"
```

---

## 🎬 Templates

### List Templates
```bash
curl -X GET "$SEMAPHORE_URL/api/v2/projects/1/templates" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN"
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "Orchestrator-Dashboard",
    "playbook": "playbooks/Dashboard-Orchestrator.yml",
    "inventory_id": 1,
    "created": "2024-04-01T10:00:00Z"
  }
]
```

### Create Template
```bash
curl -X POST "$SEMAPHORE_URL/api/v2/projects/1/templates" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Orchestrator-Dashboard",
    "description": "Discover machines and get system info",
    "type": "static",
    "project_id": 1,
    "inventory_id": 1,
    "playbook": "playbooks/Dashboard-Orchestrator.yml",
    "repository_id": 1,
    "allow_override_args_on_launch": false,
    "ask_inventory_on_launch": false,
    "ask_limit_on_launch": true,
    "ask_tags_on_launch": false,
    "ask_variables_on_launch": false,
    "ask_extra_on_launch": false,
    "suppress_success_alerts": false,
    "webhook": null,
    "execute_now": false,
    "vault_credential_id": null
  }'
```

### Create Template with SSH Key
```bash
curl -X POST "$SEMAPHORE_URL/api/v2/projects/1/templates" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Monitor-Machine-Health",
    "playbook": "playbooks/Monitor-Health.yml",
    "inventory_id": 1,
    "repository_id": 1,
    "ssh_key_id": 1,
    "ask_limit_on_launch": true,
    "ask_extra_on_launch": true
  }'
```

### Get Template by ID
```bash
curl -X GET "$SEMAPHORE_URL/api/v2/projects/1/templates/1" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN"
```

### Update Template
```bash
curl -X PUT "$SEMAPHORE_URL/api/v2/projects/1/templates/1" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Orchestrator-Dashboard-v2",
    "description": "Updated description",
    "playbook": "playbooks/Dashboard-Orchestrator.yml"
  }'
```

### Delete Template
```bash
curl -X DELETE "$SEMAPHORE_URL/api/v2/projects/1/templates/1" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN"
```

---

## 🚀 Task Execution

### Run Template
```bash
curl -X POST "$SEMAPHORE_URL/api/v2/projects/1/tasks" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "template_id": 1,
    "debug": false,
    "dry_run": false,
    "diff": false,
    "limit": "all",
    "extra": "",
    "tags": ""
  }'
```

**Response:**
```json
{
  "id": 42,
  "template_id": 1,
  "status": "running",
  "created": "2024-04-03T14:30:00Z",
  "started": "2024-04-03T14:30:02Z"
}
```

### Run Template with Extra Variables
```bash
curl -X POST "$SEMAPHORE_URL/api/v2/projects/1/tasks" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "template_id": 2,
    "extra": "{\"log_file\": \"app.log\", \"start_date\": \"2024-04-01\"}"
  }'
```

### Run Template on Specific Hosts
```bash
curl -X POST "$SEMAPHORE_URL/api/v2/projects/1/tasks" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "template_id": 2,
    "limit": "machine1,machine2"
  }'
```

### Get Task by ID
```bash
curl -X GET "$SEMAPHORE_URL/api/v2/projects/1/tasks/42" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN"
```

**Response:**
```json
{
  "id": 42,
  "template_id": 1,
  "status": "success",
  "created": "2024-04-03T14:30:00Z",
  "started": "2024-04-03T14:30:02Z",
  "finished": "2024-04-03T14:33:45Z"
}
```

### List Tasks
```bash
curl -X GET "$SEMAPHORE_URL/api/v2/projects/1/tasks" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN"
```

### Stop Running Task
```bash
curl -X DELETE "$SEMAPHORE_URL/api/v2/projects/1/tasks/42" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN"
```

### Get Task Output (Logs)
```bash
curl -X GET "$SEMAPHORE_URL/api/v2/projects/1/tasks/42/output" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN"
```

---

## 📝 Repositories

### List Repositories
```bash
curl -X GET "$SEMAPHORE_URL/api/v2/projects/1/repositories" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN"
```

### Create Repository
```bash
curl -X POST "$SEMAPHORE_URL/api/v2/projects/1/repositories" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Orchestrator-Ansible",
    "git_url": "https://github.com/you/orchestrator.git",
    "git_branch": "main",
    "ssh_key_id": 1
  }'
```

---

## 🔗 API Examples

### Complete Setup Automation Script

```bash
#!/bin/bash
# Fully automated Semaphore setup via API

SEMAPHORE_URL="http://localhost:3000"
SEMAPHORE_TOKEN="your_api_token"
PROJECT_ID=1

# ========================================================================
# 1. CREATE CREDENTIALS
# ========================================================================

echo "Creating credentials..."

# Tailscale API Key
CRED_API=$(curl -s -X POST "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/credentials" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Tailscale-API-Key",
    "type": "key",
    "value": "tskey-api-XXXXXXXXXXXXX"
  }' | jq -r '.id')

echo "✓ Created credential ID: $CRED_API"

# Linux SSH Login
CRED_SSH=$(curl -s -X POST "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/credentials" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Linux-SSH-Creds",
    "type": "login",
    "login": "ubuntu",
    "password": "your_password"
  }' | jq -r '.id')

echo "✓ Created credential ID: $CRED_SSH"

# ========================================================================
# 2. CREATE INVENTORY
# ========================================================================

echo "Creating inventory..."

INV_ID=$(curl -s -X POST "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/inventories" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Tailscale-Devices",
    "type": "file",
    "inventory": "/ansible/inventory/tailscale_dynamic_inventory.py"
  }' | jq -r '.id')

echo "✓ Created inventory ID: $INV_ID"

# ========================================================================
# 3. CREATE TEMPLATES
# ========================================================================

echo "Creating templates..."

# Template 1: Dashboard
TMPL_1=$(curl -s -X POST "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/templates" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Orchestrator-Dashboard",
    "description": "Discover machines and get system info",
    "playbook": "playbooks/Dashboard-Orchestrator.yml",
    "inventory_id": '$INV_ID',
    "repository_id": 1,
    "ask_limit_on_launch": true
  }' | jq -r '.id')

echo "✓ Created template ID: $TMPL_1"

# Template 2: Health Monitor
TMPL_2=$(curl -s -X POST "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/templates" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Monitor-Machine-Health",
    "description": "Get system metrics",
    "playbook": "playbooks/Monitor-Health.yml",
    "inventory_id": '$INV_ID',
    "repository_id": 1,
    "ask_limit_on_launch": true,
    "ask_extra_on_launch": true
  }' | jq -r '.id')

echo "✓ Created template ID: $TMPL_2"

# ========================================================================
# 4. TEST EXECUTION
# ========================================================================

echo "Testing template execution..."

TASK_ID=$(curl -s -X POST "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/tasks" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "template_id": '$TMPL_1'
  }' | jq -r '.id')

echo "✓ Started task ID: $TASK_ID"
echo ""
echo "Check progress at: $SEMAPHORE_URL/project/$PROJECT_ID/task/$TASK_ID/output"
```

### Run Playbook from Script

```bash
#!/bin/bash
# Run a template and wait for completion

SEMAPHORE_URL="http://localhost:3000"
SEMAPHORE_TOKEN="your_token"
PROJECT_ID=1
TEMPLATE_ID=1

# Start task
TASK_ID=$(curl -s -X POST "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/tasks" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"template_id": '$TEMPLATE_ID'}' | jq -r '.id')

echo "Started task $TASK_ID"

# Wait for completion
while true; do
  STATUS=$(curl -s -X GET "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/tasks/$TASK_ID" \
    -H "Authorization: Bearer $SEMAPHORE_TOKEN" | jq -r '.status')
  
  if [[ "$STATUS" == "success" ]]; then
    echo "✓ Task completed successfully"
    break
  elif [[ "$STATUS" == "failed" ]]; then
    echo "✗ Task failed"
    exit 1
  elif [[ "$STATUS" == "running" ]]; then
    echo "⏳ Task still running..."
    sleep 5
  fi
done

# Get output
curl -s -X GET "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/tasks/$TASK_ID/output" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN"
```

---

## 📊 Response Codes

| Code | Meaning |
|------|---------|
| 200 | OK - Request successful |
| 201 | Created - Resource created |
| 204 | No Content - Deletion successful |
| 400 | Bad Request - Invalid parameters |
| 401 | Unauthorized - Invalid/missing token |
| 403 | Forbidden - No permission |
| 404 | Not Found - Resource doesn't exist |
| 500 | Server Error - Internal error |

---

## 🔐 Credential Types

| Type | Fields | Use Case |
|------|--------|----------|
| `key` | `value` | API keys, tokens |
| `login` | `login`, `password` | SSH username/password |
| `ssh_key` | `secret` | SSH private key |
| `vault_key` | `secret` | Ansible vault password |
| `aws` | See docs | AWS credentials |

---

## 📈 Common Workflows

### 1. Setup New Project Completely

```bash
# 1. Create credentials
# 2. Create inventory
# 3. Create templates
# 4. Run template
# 5. Check status
```

See **Complete Setup Automation Script** above.

### 2. Trigger from CI/CD

```bash
#!/bin/bash
curl -X POST "https://semaphore.example.com/api/v2/projects/1/tasks" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "template_id": 1,
    "extra": "{\"version\": \"'$BUILD_VERSION'\"}"
  }'
```

### 3. Monitor-All-Hosts on Schedule

```bash
# Call via cron every 5 minutes
*/5 * * * * /usr/local/bin/run-orchestrator-dashboard.sh
```

### 4. Search Logs Programmatically

```bash
# Get yesterday's errors
YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)
TODAY=$(date +%Y-%m-%d)

curl -X POST "https://semaphore.example.com/api/v2/projects/1/tasks" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "template_id": 3,
    "extra": "{
      \"log_file\": \"app.log\",
      \"start_date\": \"'$YESTERDAY'\",
      \"start_time\": \"00:00:00\",
      \"end_date\": \"'$TODAY'\",
      \"end_time\": \"00:00:00\"
    }"
  }'
```

---

## 🧪 Testing with curl

### Get API Info
```bash
curl -X GET "$SEMAPHORE_URL/api/v2/user" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN"
```

### List Everything
```bash
# Projects
curl "$SEMAPHORE_URL/api/v2/projects" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" | jq

# Credentials
curl "$SEMAPHORE_URL/api/v2/projects/1/credentials" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" | jq

# Inventories
curl "$SEMAPHORE_URL/api/v2/projects/1/inventories" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" | jq

# Templates
curl "$SEMAPHORE_URL/api/v2/projects/1/templates" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" | jq

# Tasks
curl "$SEMAPHORE_URL/api/v2/projects/1/tasks" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" | jq
```

---

## 📚 Resources

- **Semaphore Docs**: https://semaphore.docs.io/api/
- **API Examples**: See setup scripts in `/ansible/`
- **Postman Collection**: Available from Semaphore downloads

## ✅ Quick Reference

```bash
# Save these
export SEMAPHORE_URL="http://localhost:3000"
export SEMAPHORE_TOKEN="your_token_here"
export PROJECT_ID=1

# Use in commands
curl -X GET "$SEMAPHORE_URL/api/v2/projects/$PROJECT_ID/templates" \
  -H "Authorization: Bearer $SEMAPHORE_TOKEN" | jq
```

---

**Last Updated**: 2024-04-03  
**API Version**: v2  
**Semaphore Version**: 2.8+
