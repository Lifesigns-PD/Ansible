#!/usr/bin/env python3
"""
Enhanced Tailscale Machine Viewer + Orchestrator Node Manager
Combines web UI for machine discovery with SSH access, log browsing, and real-time monitoring
"""

import os
import json
import uuid
import subprocess
import paramiko
import shlex
from pathlib import Path
from flask import Flask, render_template_string, jsonify, request, session, redirect, url_for, flash, Response
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configuration
TAILSCALE_API_KEY = os.getenv("TAILSCALE_API_KEY")
LOG_DIR = "/opt/go-ble-orchestrator/logs"
ANSIBLE_DIR = Path(__file__).parent.parent  # Points to /ansible directory
PLAYBOOKS_DIR = ANSIBLE_DIR / "playbooks"
INVENTORY_FILE = ANSIBLE_DIR / "inventory" / "production.yml"

# In-memory storage for active SSH sessions
active_ssh_sessions = {}

# ============================================================================
# TAILSCALE INTEGRATION
# ============================================================================

def get_tailscale_machines_api():
    """Get machines from Tailscale API + local client for real-time status"""
    api_key = os.getenv("TAILSCALE_API_KEY")
    
    machines_by_ip = {}
    try:
        result = subprocess.run(
            ['tailscale', 'status', '--json'],
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        data = json.loads(result.stdout)
        peers = data.get('Peer', {})
        
        for peer_id, peer_data in peers.items():
            if peer_data.get('TailscaleIPs'):
                ip = peer_data['TailscaleIPs'][0]
                machines_by_ip[ip] = {
                    'online': peer_data.get('Online', False),
                    'last_seen': peer_data.get('LastSeen', ''),
                    'os': peer_data.get('OS', 'Unknown')
                }
    except Exception as e:
        print(f"Local Tailscale client unavailable: {e}")
    
    if not api_key:
        print("TAILSCALE_API_KEY not set, using local client only")
        return get_tailscale_machines_local()

    url = "https://api.tailscale.com/api/v2/tailnet/-/devices"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json"
    }
    
    try:
        import requests
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        devices = response.json().get('devices', [])
        machines = []
        
        for dev in devices:
            if dev.get('addresses'):
                full_name = dev.get('name', '')
                ip = dev['addresses'][0].split('/')[0]
                device_id = dev.get('id', '')
                
                # Create unique display name using hostname + last IP octet or device ID
                if full_name and '.' in full_name:
                    base_name = full_name.split('.')[0]
                else:
                    base_name = dev.get('hostname', 'Unknown')
                
                # Make it unique by appending last IP octet or short device ID
                if device_id:
                    # Use last 8 chars of device ID for uniqueness
                    unique_suffix = device_id[-8:]
                    display_name = f"{base_name}-{unique_suffix}"
                else:
                    # Fallback: use last IP octet
                    ip_last = ip.split('.')[-1] if ip else 'unknown'
                    display_name = f"{base_name}-{ip_last}"
                
                local_status = machines_by_ip.get(ip, {})
                
                machines.append({
                    'hostname': display_name,
                    'ip': ip,
                    'online': local_status.get('online', dev.get('online', False)),
                    'os': local_status.get('os', dev.get('os', 'Unknown')),
                    'device_id': dev.get('id'),
                    'last_seen': local_status.get('last_seen', '')
                })
        
        if not machines:
            return get_tailscale_machines_local()
        
        return sorted(machines, key=lambda x: (not x['online'], x['hostname']))
        
    except Exception as e:
        print(f"API Error: {e}")
        return get_tailscale_machines_local()

def get_tailscale_machines_local():
    """Fallback: Get machines from local Tailscale client"""
    try:
        result = subprocess.run(
            ['tailscale', 'status', '--json'],
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        data = json.loads(result.stdout)
        
        machines = []
        peers = data.get('Peer', {})
        
        for peer_id, peer_data in peers.items():
            if peer_data.get('TailscaleIPs'):
                machines.append({
                    'hostname': peer_data.get('HostName', 'Unknown'),
                    'ip': peer_data['TailscaleIPs'][0],
                    'online': peer_data.get('Online', False),
                    'peer_id': peer_id,
                    'os': peer_data.get('OS', 'Unknown'),
                    'last_seen': peer_data.get('LastSeen', '')
                })
        
        return sorted(machines, key=lambda x: (not x['online'], x['hostname']))
        
    except Exception as e:
        print(f"Error: {e}")
        return []

# ============================================================================
# SSH EXECUTION HELPERS
# ============================================================================

def execute_ssh(command):
    """Execute command over active SSH session"""
    session_id = session.get('ssh_id')
    if not session_id or session_id not in active_ssh_sessions:
        return None, "Session expired. Please reconnect."
    
    client = active_ssh_sessions[session_id]
    try:
        stdin, stdout, stderr = client.exec_command(command)
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            return None, stderr.read().decode('utf-8')
        return stdout.read().decode('utf-8'), None
    except Exception as e:
        active_ssh_sessions.pop(session_id, None)
        session.pop('ssh_id', None)
        return None, f"SSH Error: {str(e)}"

# ============================================================================
# ANSIBLE INTEGRATION
# ============================================================================

def get_playbooks():
    """List all available Ansible playbooks"""
    playbooks = []
    try:
        if PLAYBOOKS_DIR.exists():
            for file in PLAYBOOKS_DIR.glob("*.yml"):
                playbooks.append({
                    'name': file.stem,
                    'filename': file.name,
                    'path': str(file)
                })
    except Exception as e:
        print(f"Error reading playbooks: {e}")
    return sorted(playbooks, key=lambda x: x['name'])

def get_playbook_vars(playbook_name):
    """Extract variables and tags from a playbook"""
    try:
        playbook_path = PLAYBOOKS_DIR / f"{playbook_name}.yml"
        with open(playbook_path, 'r') as f:
            content = f.read()
            # Look for common variable names and tags
            vars_found = []
            if 'cassia_domain' in content:
                vars_found.append('cassia_domain')
            if 'mqtt_broker' in content:
                vars_found.append('mqtt_broker')
            if 'config_password' in content:
                vars_found.append('config_password')
            return vars_found
    except Exception as e:
        print(f"Error reading playbook: {e}")
    return []

def check_ansible_on_target(client):
    """Check if Ansible is installed on target"""
    try:
        stdin, stdout, stderr = client.exec_command('which ansible-playbook')
        return stdout.channel.recv_exit_status() == 0
    except:
        return False

def check_playbooks_on_target(client):
    """Check if playbooks exist on target"""
    try:
        stdin, stdout, stderr = client.exec_command('ls -1 /tmp/ansible_deploy/*.yml 2>/dev/null | wc -l')
        count_str = stdout.read().decode('utf-8').strip()
        return int(count_str) > 0
    except:
        return False

def execute_ansible_playbook(playbook_name, target_host, extra_vars=None):
    """Execute Ansible playbook via SSH on target machine"""
    try:
        # Get the SSH client for the current session
        session_id = session.get('ssh_id')
        if not session_id or session_id not in active_ssh_sessions:
            return None
        
        client = active_ssh_sessions[session_id]
        
        # Build the Ansible command to run on the target machine
        # This assumes Ansible is installed on the target machine
        cmd = f"cd /opt/go-ble-orchestrator && \
                ansible-playbook -i inventory/production.yml \
                playbooks/{playbook_name}.yml \
                -l {target_host} -v"
        
        if extra_vars:
            for key, value in extra_vars.items():
                cmd += f" -e '{key}={value}'"
        
        print(f"[ANSIBLE] Executing via SSH: {cmd}")
        
        # Execute synchronously first to check if Ansible is available
        test_cmd = "which ansible-playbook"
        stdin, stdout, stderr = client.exec_command(test_cmd)
        exit_code = stdout.channel.recv_exit_status()
        
        if exit_code != 0:
            # Ansible not found on target machine, try running from control node
            return None
        
        # Execute the actual playbook
        stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
        return stdout
        
    except Exception as e:
        print(f"Error executing playbook: {e}")
        return None

# ============================================================================
# HTML TEMPLATES
# ============================================================================

BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Orchestrator Manager</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        :root {
            --color-bg-dark: #0f0f1e;
            --color-bg-darker: #06060b;
            --color-card: #1a1a2e;
            --color-border: #2a2a3e;
            --color-text: #e0e0e0;
            --color-text-muted: #a0a0b0;
            --color-primary: #00d7ff;
            --color-success: #10b981;
            --color-danger: #ef4444;
        }
        
        body {
            background: linear-gradient(135deg, var(--color-bg-darker) 0%, var(--color-bg-dark) 100%);
            color: var(--color-text);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        .nav-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding: 15px 20px;
            background: rgba(0, 215, 255, 0.05);
            border: 1px solid var(--color-border);
            border-radius: 12px;
        }
        
        .nav-bar h1 {
            font-size: 20px;
            color: var(--color-primary);
        }
        
        .nav-links {
            display: flex;
            gap: 10px;
        }
        
        .nav-btn {
            padding: 8px 14px;
            background: var(--color-card);
            border: 1px solid var(--color-border);
            color: var(--color-text);
            border-radius: 6px;
            cursor: pointer;
            text-decoration: none;
            transition: all 0.3s ease;
            font-size: 12px;
            font-weight: 500;
        }
        
        .nav-btn:hover {
            border-color: var(--color-primary);
            color: var(--color-primary);
        }
        
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            padding: 20px;
            background: rgba(0, 215, 255, 0.05);
            border: 1px solid var(--color-border);
            border-radius: 12px;
        }
        
        .header h2 {
            font-size: 24px;
            color: var(--color-primary);
        }
        
        .header-stats {
            display: flex;
            gap: 20px;
        }
        
        .stat {
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        
        .stat-value {
            font-size: 24px;
            font-weight: 700;
            color: var(--color-primary);
        }
        
        .stat-label {
            font-size: 12px;
            color: var(--color-text-muted);
        }
        
        .controls {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        
        .search-box {
            flex: 1;
            min-width: 200px;
            padding: 12px;
            background: var(--color-card);
            border: 1px solid var(--color-border);
            border-radius: 8px;
            color: var(--color-text);
        }
        
        .search-box:focus {
            outline: none;
            border-color: var(--color-primary);
        }
        
        .filter-btn {
            padding: 10px 14px;
            background: var(--color-card);
            border: 1px solid var(--color-border);
            border-radius: 8px;
            color: var(--color-text);
            cursor: pointer;
            transition: all 0.3s ease;
            font-weight: 500;
            font-size: 12px;
        }
        
        .filter-btn:hover {
            border-color: var(--color-primary);
            color: var(--color-primary);
        }
        
        .filter-btn.active {
            background: var(--color-primary);
            color: var(--color-bg-dark);
        }
        
        .machines-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 16px;
            margin-bottom: 30px;
        }
        
        .machine-card {
            background: var(--color-card);
            border: 1px solid var(--color-border);
            border-radius: 12px;
            padding: 20px;
            transition: all 0.3s ease;
        }
        
        .machine-card:hover {
            border-color: var(--color-primary);
            transform: translateY(-4px);
            box-shadow: 0 8px 32px rgba(0, 215, 255, 0.15);
        }
        
        .machine-status {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            margin-bottom: 12px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .status-indicator {
            width: 8px;
            height: 8px;
            border-radius: 50%;
        }
        
        .status-online .status-indicator {
            background: var(--color-success);
            box-shadow: 0 0 4px var(--color-success);
        }
        
        .status-offline .status-indicator {
            background: var(--color-danger);
        }
        
        .status-online {
            color: var(--color-success);
        }
        
        .status-offline {
            color: var(--color-danger);
        }
        
        .machine-hostname {
            font-size: 18px;
            font-weight: 700;
            margin-bottom: 8px;
        }
        
        .detail-row {
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            margin-bottom: 6px;
        }
        
        .detail-label {
            color: var(--color-text-muted);
        }
        
        .detail-value {
            color: var(--color-primary);
            font-family: monospace;
            font-weight: 600;
        }
        
        .machine-actions {
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid var(--color-border);
            display: flex;
            gap: 8px;
        }
        
        .action-btn {
            flex: 1;
            padding: 8px 12px;
            background: rgba(0, 215, 255, 0.1);
            border: 1px solid var(--color-primary);
            color: var(--color-primary);
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 600;
            transition: all 0.3s ease;
            text-decoration: none;
            text-align: center;
        }
        
        .action-btn:hover {
            background: rgba(0, 215, 255, 0.2);
        }
        
        .log-container {
            background: var(--color-card);
            border: 1px solid var(--color-border);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }
        
        .log-container h3 {
            margin-bottom: 15px;
            color: var(--color-primary);
        }
        
        .log-list {
            list-style: none;
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 10px;
        }
        
        .log-item {
            padding: 12px;
            background: rgba(0, 215, 255, 0.1);
            border: 1px solid var(--color-primary);
            border-radius: 6px;
            cursor: pointer;
            text-decoration: none;
            color: var(--color-primary);
            font-weight: 600;
            text-align: center;
            transition: all 0.3s ease;
            display: block;
        }
        
        .log-item:hover {
            background: rgba(0, 215, 255, 0.2);
            transform: translateY(-2px);
        }
        
        pre {
            background: #11111b;
            color: #a6adc8;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
            max-height: 700px;
            border: 1px solid var(--color-border);
            margin-bottom: 20px;
        }
        
        .alert {
            padding: 15px;
            margin-bottom: 20px;
            border-radius: 6px;
            border: 1px solid;
        }
        
        .alert-success {
            background: rgba(16, 185, 129, 0.1);
            border-color: var(--color-success);
            color: var(--color-success);
        }
        
        .back-link {
            display: inline-block;
            margin-bottom: 20px;
            padding: 8px 14px;
            background: var(--color-card);
            border: 1px solid var(--color-border);
            color: var(--color-text);
            border-radius: 6px;
            text-decoration: none;
            font-weight: 500;
            transition: all 0.3s ease;
        }
        
        .back-link:hover {
            border-color: var(--color-primary);
            color: var(--color-primary);
        }
    </style>
</head>
<body>
    <div class="container">
        {% if session.get('target_ip') %}
        <div class="nav-bar">
            <h1>🌐 Orchestrator Manager</h1>
            <div class="nav-links">
                <a href="{{ url_for('machines') }}" class="nav-btn">🏠 Machines</a>
                <a href="{{ url_for('dashboard') }}" class="nav-btn">📁 Logs</a>
                <span class="nav-btn">📍 {{ session.get('target_ip') }}</span>
                <a href="{{ url_for('logout') }}" class="nav-btn">🚪 Logout</a>
            </div>
        </div>
        {% endif %}
        
        {% with messages = get_flashed_messages() %}
            {% if messages %}
                {% for message in messages %}
                    <div class="alert alert-success">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        {% block content %}{% endblock %}
    </div>
</body>
</html>
"""

MACHINES_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', """
<div id="loginModal" style="display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 1000; align-items: center; justify-content: center;">
    <div style="background: var(--color-card); border: 2px solid var(--color-primary); border-radius: 12px; padding: 30px; max-width: 400px; width: 90%;">
        <h3 style="color: var(--color-primary); margin-bottom: 20px;">🔐 SSH Login</h3>
        <form id="loginForm">
            <input type="hidden" id="modalIp" name="ip">
            <input type="hidden" id="modalHostname" name="hostname">
            <div style="margin-bottom: 15px;">
                <label style="color: var(--color-text-muted); font-size: 12px;">Username</label>
                <input type="text" id="modalUsername" name="username" placeholder="ubuntu" required style="width: 100%; padding: 10px; background: var(--color-bg-dark); border: 1px solid var(--color-border); color: var(--color-text); border-radius: 6px; margin-top: 5px;">
            </div>
            <div style="margin-bottom: 20px;">
                <label style="color: var(--color-text-muted); font-size: 12px;">Password</label>
                <input type="password" id="modalPassword" name="password" placeholder="••••••••" required style="width: 100%; padding: 10px; background: var(--color-bg-dark); border: 1px solid var(--color-border); color: var(--color-text); border-radius: 6px; margin-top: 5px;">
            </div>
            <div style="display: flex; gap: 10px;">
                <button type="submit" class="action-btn" style="flex: 1; padding: 10px;">✓ Connect</button>
                <button type="button" onclick="closeModal()" class="action-btn" style="flex: 1; padding: 10px; border-color: #ef4444; color: #ef4444;">✕ Cancel</button>
            </div>
        </form>
    </div>
</div>

<div id="messageModal" style="display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 1001; align-items: center; justify-content: center;">
    <div style="background: var(--color-card); border: 2px solid var(--color-primary); border-radius: 12px; padding: 30px; max-width: 400px; width: 90%; text-align: center;">
        <div id="messageIcon" style="font-size: 48px; margin-bottom: 15px;">✓</div>
        <h3 id="messageTitle" style="color: var(--color-primary); margin-bottom: 10px;">Success</h3>
        <p id="messageText" style="color: var(--color-text-muted); margin-bottom: 20px;">Connected successfully</p>
        <button onclick="closeMessageModal()" class="action-btn" style="width: 100%; padding: 10px;">OK</button>
    </div>
</div>

<div class="header">
    <div>
        <h2>🌐 Tailscale Machines</h2>
    </div>
    <div class="header-stats">
        <div class="stat">
            <div class="stat-value">{{ total }}</div>
            <div class="stat-label">Total</div>
        </div>
        <div class="stat">
            <div class="stat-value" style="color: #10b981;">{{ online }}</div>
            <div class="stat-label">Online</div>
        </div>
        <div class="stat">
            <div class="stat-value" style="color: #ef4444;">{{ offline }}</div>
            <div class="stat-label">Offline</div>
        </div>
    </div>
</div>

<div class="controls">
    <input type="text" id="searchBox" class="search-box" placeholder="🔍 Search..." onkeyup="searchMachines()">
    <button class="filter-btn active" onclick="filterMachines('all')">All</button>
    <button class="filter-btn" onclick="filterMachines('online')">Online</button>
    <button class="filter-btn" onclick="filterMachines('offline')">Offline</button>
    <button class="filter-btn" onclick="location.reload()">🔄 Refresh</button>
</div>

<div class="machines-grid">
    {% if machines %}
        {% for machine in machines %}
            <div class="machine-card {% if machine.online %}online{% else %}offline{% endif %}">
                <div class="machine-status {% if machine.online %}status-online{% else %}status-offline{% endif %}">
                    <span class="status-indicator"></span>
                    {% if machine.online %}Online{% else %}Offline{% endif %}
                </div>
                
                <div class="machine-hostname">{{ machine.hostname }}</div>
                
                <div class="machine-details">
                    <div class="detail-row">
                        <span class="detail-label">IP:</span>
                        <span class="detail-value">{{ machine.ip }}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">OS:</span>
                        <span class="detail-value">{{ machine.os }}</span>
                    </div>
                </div>
                
                <div class="machine-actions">
                    <button onclick="openLoginModal('{{ machine.ip }}', '{{ machine.hostname }}')" class="action-btn">🔐 Login</button>
                </div>
            </div>
        {% endfor %}
    {% else %}
        <div style="grid-column: 1/-1; text-align: center; padding: 60px 20px; color: var(--color-text-muted);">
            <div style="font-size: 48px; margin-bottom: 20px;">⚠️</div>
            <div>No machines found. Ensure Tailscale is running.</div>
        </div>
    {% endif %}
</div>

<script>
    function filterMachines(status) {
        document.querySelectorAll('.machine-card').forEach(card => {
            if (status === 'all') card.style.display = '';
            else if (status === 'online') card.style.display = card.classList.contains('online') ? '' : 'none';
            else if (status === 'offline') card.style.display = card.classList.contains('offline') ? '' : 'none';
        });
        document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
        event.target.classList.add('active');
    }
    
    function searchMachines() {
        const query = document.getElementById('searchBox').value.toLowerCase();
        document.querySelectorAll('.machine-card').forEach(card => {
            const text = card.textContent.toLowerCase();
            card.style.display = text.includes(query) ? '' : 'none';
        });
    }
    
    function openLoginModal(ip, hostname) {
        document.getElementById('modalIp').value = ip;
        document.getElementById('modalHostname').value = hostname;
        document.getElementById('modalUsername').value = '';
        document.getElementById('modalPassword').value = '';
        document.getElementById('loginModal').style.display = 'flex';
    }
    
    function closeModal() {
        document.getElementById('loginModal').style.display = 'none';
    }
    
    function closeMessageModal() {
        document.getElementById('messageModal').style.display = 'none';
    }
    
    function showMessage(icon, title, text, isSuccess = false) {
        document.getElementById('messageIcon').textContent = icon;
        document.getElementById('messageTitle').textContent = title;
        document.getElementById('messageText').textContent = text;
        if (isSuccess) {
            document.getElementById('messageTitle').style.color = '#10b981';
        } else {
            document.getElementById('messageTitle').style.color = '#ef4444';
        }
        document.getElementById('messageModal').style.display = 'flex';
    }
    
    document.getElementById('loginForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const ip = document.getElementById('modalIp').value;
        const username = document.getElementById('modalUsername').value;
        const password = document.getElementById('modalPassword').value;
        
        const response = await fetch('/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: `ip=${ip}&username=${username}&password=${password}`
        });
        
        const result = await response.json();
        if (result.success) {
            showMessage('✓', 'Connected!', `Successfully logged into ${ip}`, true);
            setTimeout(() => window.location.href = '/dashboard', 2000);
        } else {
            showMessage('✗', 'Connection Failed', result.error || 'Check credentials and try again', false);
        }
    });
</script>
""")

DASHBOARD_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', """
<div class="header">
    <div>
        <h2>📁 Orchestrator Logs & Monitoring</h2>
        <p style="color: var(--color-text-muted); margin-top: 5px;">Connected to: <strong>{{ target_ip }}</strong></p>
    </div>
</div>

<div class="log-container">
    <h3>⚙️ Setup Ansible & Playbooks</h3>
    <p style="color: var(--color-text-muted); font-size: 12px; margin-bottom: 15px;">Prepare the target machine: install Ansible and copy playbooks to /tmp/ansible_deploy</p>
    
    <div style="display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap;">
        <button type="button" onclick="checkStatus()" class="action-btn" style="padding: 10px 20px; min-width: 140px;">🔍 Check Status</button>
        <button type="button" onclick="setupMachine()" class="action-btn" style="padding: 10px 20px; min-width: 140px;">📦 Copy & Install</button>
    </div>
    
    <div id="setupStatus" style="background: rgba(0, 215, 255, 0.05); padding: 12px; border-radius: 6px; border: 1px solid var(--color-border); margin-bottom: 15px; display: none;">
        <div style="font-size: 12px; color: var(--color-text-muted);">
            <div id="statusLine" style="margin: 8px 0;">Checking status...</div>
        </div>
    </div>
    
    <div id="setupOutput" style="display: none;">
        <h4 style="color: var(--color-primary); margin-bottom: 10px;">📊 Setup Output</h4>
        <pre id="setupLog" style="height: 300px; margin-bottom: 15px; overflow-y: auto;">⏳ Waiting...</pre>
    </div>
</div>

<div class="log-container">
    <h3>� Deploy with Ansible</h3>
    <p style="color: var(--color-text-muted); font-size: 12px; margin-bottom: 15px;">Select and run Ansible playbooks to deploy and configure the orchestrator</p>
    <form id="ansibleForm" style="display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap;">
        <select id="playbookSelect" required style="flex: 1; min-width: 150px; padding: 10px; background: var(--color-bg-dark); border: 1px solid var(--color-border); color: var(--color-text); border-radius: 6px;">
            <option value="">📋 Select Playbook...</option>
            {% for playbook in playbooks %}
                <option value="{{ playbook.name }}">{{ playbook.name }}</option>
            {% endfor %}
        </select>
        <button type="submit" class="action-btn" style="padding: 10px 20px; min-width: 120px;">▶️ Run Playbook</button>
    </form>
    
    <div id="ansibleOutput" style="display: none;">
        <h4 style="color: var(--color-primary); margin-bottom: 10px;">📊 Execution Output</h4>
        <pre id="outputLog" style="height: 500px; margin-bottom: 15px;">⏳ Waiting to execute...</pre>
        <div id="ansibleStatus" style="display: flex; gap: 10px; align-items: center; margin-bottom: 10px;">
            <span id="statusIndicator" style="width: 12px; height: 12px; background: #f59e0b; border-radius: 50%; box-shadow: 0 0 6px #f59e0b;"></span>
            <span id="statusText" style="color: var(--color-text-muted);">Ready</span>
        </div>
    </div>
</div>

<div class="log-container">
    <h3>📊 Standard Logs</h3>
    <p style="color: var(--color-text-muted); font-size: 12px; margin-bottom: 12px;">View the last 1000 lines using <code style="background: #11111b; padding: 2px 6px; border-radius: 3px;">tail -n 1000</code></p>
    <ul class="log-list">
        {% for log in logs %}
            <li><a href="{{ url_for('view_file', filename=log) }}" class="log-item">📄 {{ log }}</a></li>
        {% endfor %}
    </ul>
</div>

<div class="log-container">
    <h3>📊 Gateway JSON Logs (json_logs/)</h3>
    <p style="color: var(--color-text-muted); font-size: 12px; margin-bottom: 12px;">Search logs by date/time or stream in real-time</p>
    {% if gateway_files %}
        <ul class="log-list">
            {% for file in gateway_files %}
                <li><a href="{{ url_for('view_gateway_file', filename=file) }}" class="log-item">📊 {{ file }}</a></li>
            {% endfor %}
        </ul>
    {% else %}
        <p style="color: var(--color-text-muted); text-align: center; padding: 20px;">ℹ️ No log files found in json_logs/</p>
    {% endif %}
</div>

<style>
    @keyframes pulse-yellow {
        0%, 100% { box-shadow: 0 0 6px #f59e0b; }
        50% { box-shadow: 0 0 12px #f59e0b; }
    }
    #statusIndicator.running {
        background: #f59e0b;
        animation: pulse-yellow 1s infinite;
    }
    #statusIndicator.success {
        background: #10b981;
        box-shadow: 0 0 6px #10b981;
    }
    #statusIndicator.failed {
        background: #ef4444;
        box-shadow: 0 0 6px #ef4444;
    }
</style>

<script>
    // Initialize form handlers - check if elements exist before using them
    const playbookSelect = document.getElementById('playbookSelect');
    const ansibleForm = document.getElementById('ansibleForm');
    const ansibleOutput = document.getElementById('ansibleOutput');
    const outputLog = document.getElementById('outputLog');
    const statusIndicator = document.getElementById('statusIndicator');
    const statusText = document.getElementById('statusText');
    
    // Only attach event listener if form exists
    if (ansibleForm) {
        ansibleForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const playbook = playbookSelect.value;
            console.log('[FORM] Submitted with playbook:', playbook);
            
            if (!playbook) {
                console.warn('[WARNING] No playbook selected');
                alert('Please select a playbook first');
                return;
            }
            
            // Verify output element exists
            if (!ansibleOutput || !outputLog || !statusIndicator || !statusText) {
                console.error('[ERROR] Missing output elements:', {ansibleOutput, outputLog, statusIndicator, statusText});
                alert('Error: Output elements not found');
                return;
            }
            
            // Disable submit button while running
            const submitBtn = ansibleForm.querySelector('button[type="submit"]');
            if (!submitBtn) {
                console.error('[ERROR] Submit button not found');
                return;
            }
            const originalText = submitBtn.innerHTML;
            submitBtn.disabled = true;
            
            ansibleOutput.style.display = 'block';
            outputLog.innerHTML = '';
            statusIndicator.className = 'running';
            statusText.textContent = 'Initializing...';
            console.log('[STREAM] Initiating stream to /ansible/stream');
            
            try {
                const response = await fetch('/ansible/stream', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body: `playbook=${playbook}`,
                    credentials: 'same-origin'
                });
                console.log('[STREAM] Got response:', response.status, response.statusText);
            while (true) {
                const {done, value} = await reader.read();
                if (done) break;
                
                const chunk = decoder.decode(value, {stream: true});
                fullOutput += chunk;
                
                // Stream output line by line
                const lines = chunk.split('\\n');
                for (const line of lines) {
                    if (line) {
                        // Color code output based on content
                        let styledLine = escapeHtml(line);
                        
                        if (line.includes('FAILED') || line.includes('fatal') || line.includes('[✗')) {
                            outputLog.innerHTML += '<span style="color: #ef4444; font-weight: bold;">' + styledLine + '</span>\\n';
                            statusIndicator.className = 'failed';
                            statusText.textContent = 'Error detected...';
                        } else if (line.includes('changed') || line.includes('ok:') || line.includes('[✓')) {
                            outputLog.innerHTML += '<span style="color: #10b981;">' + styledLine + '</span>\\n';
                        } else if (line.includes('TASK') || line.includes('PLAY')) {
                            outputLog.innerHTML += '<span style="color: #00d7ff; font-weight: bold;">' + styledLine + '</span>\\n';
                        } else if (line.includes('[INFO]')) {
                            outputLog.innerHTML += '<span style="color: #f59e0b;">' + styledLine + '</span>\\n';
                        } else if (line.includes('─')) {
                            outputLog.innerHTML += '<span style="color: #4b5563;">' + styledLine + '</span>\\n';
                        } else {
                            outputLog.innerHTML += styledLine + '\\n';
                        }
                        outputLog.scrollTop = outputLog.scrollHeight;
                    }
                }
            }
            
            // Determine final status
            if (fullOutput.includes('[✓ SUCCESS]')) {
                statusIndicator.className = 'success';
                statusText.textContent = '✓ Completed Successfully';
            } else if (fullOutput.includes('[✗ FAILED]') || fullOutput.includes('exit code: 1')) {
                statusIndicator.className = 'failed';
                statusText.textContent = '✗ Playbook Failed';
            } else if (fullOutput.includes('[ERROR]')) {
                statusIndicator.className = 'failed';
                statusText.textContent = '✗ Error Occurred';
            } else {
                statusIndicator.className = 'success';
                statusText.textContent = '✓ Completed';
            }
        } catch (error) {
            outputLog.innerHTML += '\\n<span style="color: #ef4444;">[CLIENT ERROR] ' + escapeHtml(error.message) + '</span>';
            statusIndicator.className = 'failed';
            statusText.textContent = '✗ Execution Failed';
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalText;
        }
    });
    } else {
        console.warn('[WARNING] ansibleForm element not found');
    }
    
    function escapeHtml(text) {
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return text.replace(/[&<>"']/g, m => map[m]);
    }
    
    async function checkStatus() {
        console.log('checkStatus() called');
        const statusDiv = document.getElementById('setupStatus');
        const statusLine = document.getElementById('statusLine');
        
        if (!statusDiv || !statusLine) {
            console.error('[ERROR] Setup status elements not found');
            return;
        }
        
        statusDiv.style.display = 'block';
        statusLine.textContent = 'Checking status...';
        
        try {
            const response = await fetch('/ansible/status', {
                method: 'GET',
                credentials: 'same-origin'
            });
            console.log('Fetch response status:', response.status);
            const result = await response.json();
            console.log('Status result:', result);
            
            if (result.success) {
                const ansible = result.ansible_installed ? '✓ Installed' : '✗ Not installed';
                const playbooks = result.playbooks_copied ? '✓ Copied' : '✗ Not copied';
                statusLine.innerHTML = `
                    <strong>Ansible:</strong> ${ansible}<br>
                    <strong>Playbooks:</strong> ${playbooks}<br>
                    <strong>Location:</strong> /tmp/ansible_deploy
                `;
            } else {
                statusLine.innerHTML = '<span style="color: #ef4444;">' + escapeHtml(result.error) + '</span>';
            }
        } catch (error) {
            statusLine.innerHTML = '<span style="color: #ef4444;">Error checking status: ' + escapeHtml(error.message) + '</span>';
        }
    }
    
    async function setupMachine() {
        console.log('setupMachine() called');
        const setupOutput = document.getElementById('setupOutput');
        const setupLog = document.getElementById('setupLog');
        const statusDiv = document.getElementById('setupStatus');
        
        if (!setupOutput || !setupLog || !statusDiv) {
            console.error('[ERROR] Setup output elements not found');
            alert('Error: Setup UI elements not found. Refresh page and try again.');
            return;
        }
        
        setupOutput.style.display = 'block';
        statusDiv.style.display = 'none';
        setupLog.innerHTML = '⏳ Starting setup...\n';
        
        try {
            const response = await fetch('/ansible/setup', { 
                method: 'POST',
                credentials: 'same-origin'
            });
            console.log('Setup response started, status:', response.status);
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let fullOutput = '';
            
            while (true) {
                const {done, value} = await reader.read();
                if (done) break;
                
                const chunk = decoder.decode(value, {stream: true});
                fullOutput += chunk;
                
                const lines = chunk.split('\n');
                for (const line of lines) {
                    if (line) {
                        let styledLine = escapeHtml(line);
                        
                        if (line.includes('[✓') || line.includes('✓')) {
                            setupLog.innerHTML += '<span style="color: #10b981;">' + styledLine + '</span>\n';
                        } else if (line.includes('[✗') || line.includes('[ERROR]')) {
                            setupLog.innerHTML += '<span style="color: #ef4444;">' + styledLine + '</span>\n';
                        } else if (line.includes('[⚠️')) {
                            setupLog.innerHTML += '<span style="color: #f59e0b;">' + styledLine + '</span>\n';
                        } else if (line.includes('[INFO]')) {
                            setupLog.innerHTML += '<span style="color: #f59e0b;">' + styledLine + '</span>\n';
                        } else if (line.includes('Copied') || line.includes('Installed')) {
                            setupLog.innerHTML += '<span style="color: #10b981;">' + styledLine + '</span>\n';
                        } else if (line.includes('Contents')) {
                            setupLog.innerHTML += '<span style="color: #a0a0b0; font-size: 11px;">' + styledLine + '</span>\n';
                        } else {
                            setupLog.innerHTML += styledLine + '\n';
                        }
                        setupLog.scrollTop = setupLog.scrollHeight;
                    }
                }
            }
            
            // Auto-check status after setup
            setTimeout(() => {
                setupLog.innerHTML += '\n<span style="color: #f59e0b;">Checking final status...</span>\n';
                checkStatus();
            }, 1000);
            
        } catch (error) {
            setupLog.innerHTML += '\n<span style="color: #ef4444;">[ERROR] Setup failed: ' + escapeHtml(error.message) + '</span>';
        }
    }
</script>
""")

VIEWER_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', """
<a href="{{ url_for('machines') }}" class="back-link">← Back to Machines</a>
<a href="{{ url_for('dashboard') }}" class="back-link">← Back to Logs</a>

<div class="log-container">
    <h3>📄 {{ title }}</h3>
    <div style="background: rgba(0, 215, 255, 0.05); padding: 12px; border-radius: 6px; margin-bottom: 15px; border: 1px solid var(--color-border);">
        <span style="color: var(--color-text-muted); font-size: 12px;">📍 Command: </span>
        <code style="background: #11111b; padding: 4px 8px; border-radius: 4px; color: #10b981; font-family: monospace;">cat {{ title }}</code>
    </div>
    <pre>{{ content }}</pre>
</div>
""")

GATEWAY_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', """
<a href="{{ url_for('dashboard') }}" class="back-link">← Back to Dashboard</a>

<div class="log-container">
    <h3>📊 Gateway Log: {{ filename }}</h3>
    <p style="color: var(--color-text-muted); margin-bottom: 20px;">Path: <code style="background: #11111b; padding: 4px 8px; border-radius: 4px;">{{ log_dir }}/json_logs/{{ filename }}</code></p>
    
    <form method="GET" action="{{ url_for('view_json_timestamp', filename=filename) }}" style="display: flex; flex-direction: column; gap: 15px; margin-bottom: 20px;">
        <div style="display: flex; gap: 10px; flex-wrap: wrap;">
            <div style="flex: 1; min-width: 200px;">
                <label style="color: var(--color-text-muted); font-size: 12px; display: block; margin-bottom: 8px;">📅 Select Date & Time</label>
                <input type="datetime-local" name="timestamp" required style="width: 100%; padding: 12px; background: var(--color-bg-dark); border: 1px solid var(--color-border); color: var(--color-text); border-radius: 6px; font-size: 14px;">
            </div>
            <div style="display: flex; gap: 10px; align-items: flex-end;">
                <button type="submit" class="action-btn" style="padding: 10px 20px; min-width: 120px;">🔍 Search Logs</button>
                <a href="{{ url_for('live_tail', filename='json_logs/' + filename) }}" class="action-btn" style="padding: 10px 20px; min-width: 120px; text-align: center; text-decoration: none;">📺 Live Tail</a>
            </div>
        </div>
    </form>
</div>
""")


LIVE_TAIL_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', """
<a href="{{ url_for('dashboard') }}" class="back-link">← Back to Logs</a>

<div class="log-container">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
        <h3>📺 Live Tail: {{ title }}</h3>
        <div style="display: flex; align-items: center; gap: 10px;">
            <span id="liveIndicator" style="width: 12px; height: 12px; background: #10b981; border-radius: 50%; box-shadow: 0 0 6px #10b981;"></span>
            <span style="color: var(--color-text-muted); font-size: 12px;">Live Streaming</span>
        </div>
    </div>
    <pre id="logOutput" style="height: 600px; overflow-y: auto;">⏳ Connecting to live stream...</pre>
</div>

<style>
    @keyframes pulse {
        0%, 100% { box-shadow: 0 0 6px #10b981; }
        50% { box-shadow: 0 0 12px #10b981; }
    }
    #liveIndicator.connecting {
        animation: pulse 1s infinite;
    }
    #liveIndicator.error {
        background: #ef4444;
        box-shadow: 0 0 6px #ef4444;
    }
</style>

<script>
    const logWindow = document.getElementById("logOutput");
    const liveIndicator = document.getElementById("liveIndicator");
    let lineCount = 0;
    
    const evtSource = new EventSource("{{ url_for('stream_tail', filename=filename) }}");
    
    evtSource.onopen = () => {
        logWindow.innerHTML = '';
        liveIndicator.classList.remove('connecting', 'error');
        liveIndicator.classList.add('connecting');
    };
    
    evtSource.onmessage = e => {
        liveIndicator.classList.remove('connecting', 'error');
        logWindow.innerHTML += e.data + "\\n";
        logWindow.scrollTop = logWindow.scrollHeight;
        lineCount++;
    };
    
    evtSource.onerror = () => {
        liveIndicator.classList.remove('connecting');
        liveIndicator.classList.add('error');
        logWindow.innerHTML += "\\n\\n[Stream Closed] Total lines received: " + lineCount;
        evtSource.close();
    };
    
    window.addEventListener('beforeunload', () => {
        evtSource.close();
    });
</script>
""")

# ============================================================================
# ROUTES
# ============================================================================

@app.route('/')
def index():
    return redirect(url_for('machines'))

@app.route('/machines')
def machines():
    machines_list = get_tailscale_machines_api()
    return render_template_string(
        MACHINES_TEMPLATE,
        machines=machines_list,
        total=len(machines_list),
        online=sum(1 for m in machines_list if m['online']),
        offline=sum(1 for m in machines_list if not m['online'])
    )

@app.route('/login', methods=['POST'])
def login():
    ip = request.form['ip']
    username = request.form['username']
    password = request.form['password']

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        if password:
            # Try password first if the user typed one
            client.connect(hostname=ip, username=username, password=password, timeout=10)
        else:
            # If no password, tell Paramiko to use your local ~/.ssh/ keys
            client.connect(hostname=ip, username=username, timeout=10, look_for_keys=True)
            
        session_id = str(uuid.uuid4())
        active_ssh_sessions[session_id] = client
        session['ssh_id'] = session_id
        session['target_ip'] = ip
        return jsonify({"success": True, "message": f"Connected to {ip}"})
    except paramiko.AuthenticationException:
        return jsonify({"success": False, "error": "Authentication failed. Check password or ensure your SSH key is authorized on the node."})
    except Exception as e:
        return jsonify({"success": False, "error": f"SSH failed: {str(e)}"})

@app.route('/logout')
def logout():
    session_id = session.get('ssh_id')
    if session_id and session_id in active_ssh_sessions:
        try:
            active_ssh_sessions[session_id].close()
        except:
            pass
        active_ssh_sessions.pop(session_id, None)
    session.clear()
    return redirect(url_for('machines'))

@app.route('/dashboard')
def dashboard():
    if 'ssh_id' not in session:
        flash("Please login first")
        return redirect(url_for('machines'))

    # Get available playbooks
    playbooks = get_playbooks()
    
    # DYNAMICALLY fetch the main logs (no more hardcoding)
    out_base, err_base = execute_ssh(f"ls -1 {LOG_DIR}/*.log 2>/dev/null")
    target_logs = [f.strip().split('/')[-1] for f in (out_base or '').split('\n') if f.strip().endswith('.log')]

    # Fetch the json_logs
    out_json, err_json = execute_ssh(f"ls -1 {LOG_DIR}/json_logs/*.log 2>/dev/null")
    gateway_files = [f.strip().split('/')[-1] for f in (out_json or '').split('\n') if f.strip().endswith('.log')]

    return render_template_string(DASHBOARD_TEMPLATE, target_ip=session.get('target_ip'), logs=target_logs, gateway_files=gateway_files, playbooks=playbooks)
@app.route('/view/<path:filename>')
def view_file(filename):
    if 'ssh_id' not in session:
        return redirect(url_for('machines'))
    out, err = execute_ssh(f"tail -n 1000 {LOG_DIR}/{filename}")
    return render_template_string(VIEWER_TEMPLATE, title=filename, content=out or err or "No logs")

@app.route('/gateway/<filename>')
def view_gateway_file(filename):
    if 'ssh_id' not in session:
        return redirect(url_for('machines'))
    return render_template_string(GATEWAY_TEMPLATE, filename=filename, log_dir=LOG_DIR)

@app.route('/gateway/<filename>/search')
def view_json_timestamp(filename):
    if 'ssh_id' not in session:
        return redirect(url_for('machines'))
    timestamp_raw = request.args.get('timestamp', '').replace('T', ' ')
    
    # Use grep to find lines with timestamp, then use awk to extract context
    # This searches for the timestamp in various common log formats
    cmd = f"grep -n '{timestamp_raw}' {LOG_DIR}/json_logs/{filename} | head -50 || echo 'No matches found for timestamp: {timestamp_raw}'"
    
    out, err = execute_ssh(cmd)
    return render_template_string(VIEWER_TEMPLATE, title=f"{filename} @ {timestamp_raw}", content=out or err or "No logs found for this timestamp")

@app.route('/live_tail/<path:filename>')
def live_tail(filename):
    if 'ssh_id' not in session:
        return redirect(url_for('machines'))
    return render_template_string(LIVE_TAIL_TEMPLATE, title=filename, filename=filename)

@app.route('/stream/<path:filename>')
def stream_tail(filename):
    # Capture session values now to avoid referencing Flask `session` in generator
    session_id = session.get('ssh_id')
    client = active_ssh_sessions.get(session_id)

    def generate():
        if not client:
            yield "data: [ERROR] Session expired. Please reconnect.\n\n"
            return
        try:
            # Use tail -f to stream real-time logs
            stdin, stdout, stderr = client.exec_command(f"tail -n 50 -f {LOG_DIR}/{filename}", get_pty=True)
            for line in iter(stdout.readline, ""):
                if line:
                    yield f"data: {line.rstrip()}\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"

    return Response(generate(), mimetype='text/event-stream')

@app.route('/ansible/stream', methods=['POST'])
def ansible_stream():
    """Execute Ansible playbook via SSH on target machine and stream output"""
    playbook = request.form.get('playbook', '')
    target_ip = session.get('target_ip', '')
    session_id = session.get('ssh_id', '')
    
    if not playbook or not target_ip or not session_id:
        return Response("ERROR: Missing playbook, target IP, or SSH session\n", mimetype='text/plain')
    
    # Verify SSH session exists and capture client NOW
    if session_id not in active_ssh_sessions:
        return Response("ERROR: SSH session not found. Please log back in.\n", mimetype='text/plain')
    
    client = active_ssh_sessions.get(session_id)
    if not client:
        return Response("ERROR: Cannot access SSH client\n", mimetype='text/plain')
    
    def generate():
        try:
            # Step 1: Check if playbook file exists in /tmp/ansible_deploy
            yield "[INFO] Checking for playbooks in /tmp/ansible_deploy...\n"
            stdin, stdout, stderr = client.exec_command(f'ls /tmp/ansible_deploy/{playbook}.yml 2>/dev/null')
            check_code = stdout.channel.recv_exit_status()
            
            if check_code != 0:
                yield "[✗ ERROR] Playbook '{playbook}.yml' not found in /tmp/ansible_deploy\n"
                yield "[INFO] Please use 'Copy Playbooks' button to transfer them to this machine first.\n"
                return
            
            yield "[✓ OK] Playbook found locally\n\n"
            
            # Step 2: Check if Ansible is installed
            yield "[INFO] Checking Ansible installation...\n"
            stdin, stdout, stderr = client.exec_command('which ansible-playbook', get_pty=True)
            check_code = stdout.channel.recv_exit_status()
            
            if check_code != 0:
                yield "[⚠️  WARNING] Ansible not installed. Attempting to install...\n"
                yield "[INFO] Running: sudo apt-get update && sudo apt-get install -y ansible\n\n"
                
                # Install Ansible
                stdin, stdout, stderr = client.exec_command(
                    'sudo apt-get update && sudo apt-get install -y ansible',
                    get_pty=True
                )
                install_code = stdout.channel.recv_exit_status()
                
                # Stream install output
                for line in iter(stdout.readline, ''):
                    if line:
                        yield line
                
                if install_code != 0:
                    yield "[✗ ERROR] Failed to install Ansible\n"
                    return
                
                yield "[✓ SUCCESS] Ansible installed successfully\n\n"
            else:
                yield "[✓ OK] Ansible is installed\n\n"
            
            # Step 3: Run the playbook from /tmp
            yield "─" * 70 + "\n"
            yield f"[INFO] Running playbook: {playbook}\n"
            yield "─" * 70 + "\n\n"
            
            # Use inline inventory to avoid host matching issues
            cmd = (
                "cd /tmp/ansible_deploy && "
                "ansible-playbook "
                f"  {playbook}.yml "
                "  -i localhost, "
                "  -c local "
                "  -v"
            )
            
            yield f"[INFO] Command: {cmd}\n\n"
            
            # Execute playbook
            stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
            
            # Stream output
            for line in iter(stdout.readline, ''):
                if line:
                    yield line
            
            # Get exit status
            exit_code = stdout.channel.recv_exit_status()
            
            # Stream stderr if any
            for line in iter(stderr.readline, ''):
                if line:
                    yield f"[STDERR] {line}"
            
            yield "\n" + "─" * 70 + "\n"
            if exit_code == 0:
                yield f"[✓ SUCCESS] Playbook completed successfully\n"
            else:
                yield f"[✗ FAILED] Playbook failed with exit code: {exit_code}\n"
        
        except Exception as e:
            yield f"\n[ERROR] Exception: {str(e)}\n"
            import traceback
            yield f"{traceback.format_exc()}\n"
    
    return Response(generate(), mimetype='text/plain')

@app.route('/ansible/status', methods=['GET'])
def ansible_status():
    """Check Ansible and playbooks status on target"""
    session_id = session.get('ssh_id')
    
    if not session_id or session_id not in active_ssh_sessions:
        return jsonify({"success": False, "error": "SSH session not found"})
    
    client = active_ssh_sessions.get(session_id)
    
    try:
        ansible_ok = check_ansible_on_target(client)
        playbooks_ok = check_playbooks_on_target(client)
        
        return jsonify({
            "success": True,
            "ansible_installed": ansible_ok,
            "playbooks_copied": playbooks_ok,
            "message": f"Ansible: {'✓ Installed' if ansible_ok else '✗ Not installed'} | Playbooks: {'✓ Copied' if playbooks_ok else '✗ Not copied'}"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/ansible/setup', methods=['POST'])
def ansible_setup():
    """Setup Ansible and copy playbooks to target"""
    session_id = session.get('ssh_id')
    
    if not session_id or session_id not in active_ssh_sessions:
        return jsonify({"success": False, "error": "SSH session not found"})
    
    client = active_ssh_sessions.get(session_id)
    
    def generate():
        try:
            # Step 0: Create working directory
            yield "[INFO] Creating working directory: /tmp/ansible_deploy\n"
            client.exec_command('mkdir -p /tmp/ansible_deploy')
            
            # Step 1: Copy playbooks via SFTP
            yield "[INFO] Copying playbooks to target...\n"
            sftp = client.open_sftp()
            
            # Copy all playbook files
            local_playbooks_dir = PLAYBOOKS_DIR
            playbooks_copied = 0
            if local_playbooks_dir.exists():
                for playbook_file in local_playbooks_dir.glob("*.yml"):
                    try:
                        remote_path = f"/tmp/ansible_deploy/{playbook_file.name}"
                        sftp.put(str(playbook_file), remote_path)
                        yield f"  ✓ Copied {playbook_file.name}\n"
                        playbooks_copied += 1
                    except Exception as e:
                        yield f"  ✗ Failed to copy {playbook_file.name}: {str(e)}\n"
            
            # Copy inventory directory if exists
            if (ANSIBLE_DIR / "inventory").exists():
                client.exec_command('mkdir -p /tmp/ansible_deploy/inventory')
                for inv_file in (ANSIBLE_DIR / "inventory").glob("*.yml"):
                    try:
                        remote_path = f"/tmp/ansible_deploy/inventory/{inv_file.name}"
                        sftp.put(str(inv_file), remote_path)
                        yield f"  ✓ Copied inventory/{inv_file.name}\n"
                    except Exception as e:
                        yield f"  ⚠️  Failed to copy inventory/{inv_file.name}: {str(e)}\n"
            
            # Copy group_vars if exists
            group_vars_path = ANSIBLE_DIR / "inventory" / "group_vars"
            if group_vars_path.exists():
                client.exec_command('mkdir -p /tmp/ansible_deploy/inventory/group_vars')
                for gv_dir in group_vars_path.iterdir():
                    if gv_dir.is_dir():
                        client.exec_command(f'mkdir -p /tmp/ansible_deploy/inventory/group_vars/{gv_dir.name}')
                        for gv_file in gv_dir.glob("*"):
                            if gv_file.is_file():
                                try:
                                    remote_path = f"/tmp/ansible_deploy/inventory/group_vars/{gv_dir.name}/{gv_file.name}"
                                    sftp.put(str(gv_file), remote_path)
                                except:
                                    pass
            
            sftp.close()
            
            if playbooks_copied == 0:
                yield "[✗ ERROR] No playbooks were copied\n"
                return
            
            yield f"[✓ OK] {playbooks_copied} playbooks copied successfully\n\n"
            
            # Step 2: Install Ansible if not present
            yield "[INFO] Checking Ansible installation...\n"
            stdin, stdout, stderr = client.exec_command('which ansible-playbook')
            check_code = stdout.channel.recv_exit_status()
            
            if check_code != 0:
                yield "[⚠️  WARNING] Ansible not installed. Installing...\n"
                yield "[INFO] Running: sudo apt-get update && sudo apt-get install -y ansible\n"
                
                # Update package list
                stdin, stdout, stderr = client.exec_command('sudo apt-get update', get_pty=True)
                update_code = stdout.channel.recv_exit_status()
                for line in iter(stdout.readline, ''):
                    if line and ('Hit:' in line or 'Get:' in line or 'Reading' in line):
                        yield f"  {line.rstrip()}\n"
                
                # Install Ansible
                stdin, stdout, stderr = client.exec_command('sudo apt-get install -y ansible', get_pty=True)
                install_code = stdout.channel.recv_exit_status()
                
                for line in iter(stdout.readline, ''):
                    if line:
                        yield line
                
                if install_code != 0:
                    yield "[✗ ERROR] Failed to install Ansible\n"
                    return
                
                yield "[✓ SUCCESS] Ansible installed successfully\n\n"
            else:
                yield "[✓ OK] Ansible is already installed\n\n"
            
            # Step 3: Verify setup
            yield "[INFO] Verifying setup...\n"
            stdin, stdout, stderr = client.exec_command(r'ls -la /tmp/ansible_deploy | grep -E "\.yml|inventory"')
            output = stdout.read().decode('utf-8')
            yield f"  Contents of /tmp/ansible_deploy:\n{output}\n"
            
            yield "[✓ SUCCESS] Target machine is ready!\n"
            yield "[INFO] You can now run Ansible playbooks from the dashboard.\n"
        
        except Exception as e:
            yield f"\n[ERROR] Setup failed: {str(e)}\n"
            import traceback
            yield f"{traceback.format_exc()}\n"
    
    return Response(generate(), mimetype='text/plain')

if __name__ == '__main__':
    print("""
    ╔════════════════════════════════════════════════════╗
    ║   Orchestrator Manager - Full Integration         ║
    ╚════════════════════════════════════════════════════╝
    
    🌐 http://localhost:5005
    
    Features:
    ✓ Tailscale machine discovery
    ✓ SSH login to machines
    ✓ Browse orchestrator logs
    ✓ Live tail log streams
    ✓ Search logs by timestamp
    ✓ Run Ansible playbooks
    ✓ Real-time deployment output
    """)
    
    app.run(host='127.0.0.1', port=5005, debug=True, use_reloader=False)
