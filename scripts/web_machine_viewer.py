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
                
                if full_name and '.' in full_name:
                    base_name = full_name.split('.')[0]
                else:
                    base_name = dev.get('hostname', 'Unknown')
                
                if device_id:
                    unique_suffix = device_id[-8:]
                    display_name = f"{base_name}-{unique_suffix}"
                else:
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
            err = stderr.read().decode('utf-8')
            out = stdout.read().decode('utf-8')
            return out or None, err
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
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
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
        
        .container { max-width: 1400px; margin: 0 auto; }
        
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
        
        .nav-bar h1 { font-size: 20px; color: var(--color-primary); }
        .nav-links { display: flex; gap: 10px; flex-wrap: wrap; }
        
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
        .nav-btn:hover { border-color: var(--color-primary); color: var(--color-primary); }
        
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
        .header h2 { font-size: 24px; color: var(--color-primary); }
        .header-stats { display: flex; gap: 20px; }
        .stat { display: flex; flex-direction: column; align-items: center; }
        .stat-value { font-size: 24px; font-weight: 700; color: var(--color-primary); }
        .stat-label { font-size: 12px; color: var(--color-text-muted); }
        
        .controls { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
        
        .search-box {
            flex: 1;
            min-width: 200px;
            padding: 12px;
            background: var(--color-card);
            border: 1px solid var(--color-border);
            border-radius: 8px;
            color: var(--color-text);
        }
        .search-box:focus { outline: none; border-color: var(--color-primary); }
        
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
        .filter-btn:hover { border-color: var(--color-primary); color: var(--color-primary); }
        .filter-btn.active { background: var(--color-primary); color: var(--color-bg-dark); }
        
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
        .status-indicator { width: 8px; height: 8px; border-radius: 50%; }
        .status-online .status-indicator { background: var(--color-success); box-shadow: 0 0 4px var(--color-success); }
        .status-offline .status-indicator { background: var(--color-danger); }
        .status-online { color: var(--color-success); }
        .status-offline { color: var(--color-danger); }
        
        .machine-hostname { font-size: 18px; font-weight: 700; margin-bottom: 8px; }
        
        .detail-row { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 6px; }
        .detail-label { color: var(--color-text-muted); }
        .detail-value { color: var(--color-primary); font-family: monospace; font-weight: 600; }
        
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
        .action-btn:hover { background: rgba(0, 215, 255, 0.2); }
        
        .log-container {
            background: var(--color-card);
            border: 1px solid var(--color-border);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .log-container h3 { margin-bottom: 15px; color: var(--color-primary); }
        
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
        .log-item:hover { background: rgba(0, 215, 255, 0.2); transform: translateY(-2px); }
        
        pre {
            background: #11111b;
            color: #a6adc8;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
            max-height: 700px;
            overflow-y: auto;
            border: 1px solid var(--color-border);
            margin-bottom: 20px;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            line-height: 1.6;
            white-space: pre-wrap;
            word-break: break-all;
        }
        
        .alert { padding: 15px; margin-bottom: 20px; border-radius: 6px; border: 1px solid; }
        .alert-success { background: rgba(16, 185, 129, 0.1); border-color: var(--color-success); color: var(--color-success); }
        
        .back-link {
            display: inline-block;
            margin-bottom: 20px;
            margin-right: 10px;
            padding: 8px 14px;
            background: var(--color-card);
            border: 1px solid var(--color-border);
            color: var(--color-text);
            border-radius: 6px;
            text-decoration: none;
            font-weight: 500;
            transition: all 0.3s ease;
        }
        .back-link:hover { border-color: var(--color-primary); color: var(--color-primary); }
        
        input[type="datetime-local"] {
            color-scheme: dark;
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

# ============================================================================
# MACHINES TEMPLATE
# ============================================================================

MACHINES_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', """
<div id="loginModal" style="display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 1000; align-items: center; justify-content: center;">
    <div style="background: var(--color-card); border: 2px solid var(--color-primary); border-radius: 12px; padding: 30px; max-width: 400px; width: 90%;">
        <h3 style="color: var(--color-primary); margin-bottom: 20px;">🔐 SSH Login</h3>
        <div id="loginForm">
            <input type="hidden" id="modalIp" name="ip">
            <input type="hidden" id="modalHostname" name="hostname">
            <div style="margin-bottom: 15px;">
                <label style="color: var(--color-text-muted); font-size: 12px;">Username</label>
                <input type="text" id="modalUsername" placeholder="ubuntu" style="width: 100%; padding: 10px; background: var(--color-bg-dark); border: 1px solid var(--color-border); color: var(--color-text); border-radius: 6px; margin-top: 5px;">
            </div>
            <div style="margin-bottom: 20px;">
                <label style="color: var(--color-text-muted); font-size: 12px;">Password</label>
                <input type="password" id="modalPassword" placeholder="••••••••" style="width: 100%; padding: 10px; background: var(--color-bg-dark); border: 1px solid var(--color-border); color: var(--color-text); border-radius: 6px; margin-top: 5px;">
            </div>
            <div style="display: flex; gap: 10px;">
                <button onclick="submitLogin()" class="action-btn" style="flex: 1; padding: 10px;">✓ Connect</button>
                <button onclick="closeModal()" class="action-btn" style="flex: 1; padding: 10px; border-color: #ef4444; color: #ef4444;">✕ Cancel</button>
            </div>
        </div>
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
    <button class="filter-btn active" onclick="filterMachines('all', this)">All</button>
    <button class="filter-btn" onclick="filterMachines('online', this)">Online</button>
    <button class="filter-btn" onclick="filterMachines('offline', this)">Offline</button>
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
    function filterMachines(status, btn) {
        document.querySelectorAll('.machine-card').forEach(card => {
            if (status === 'all') card.style.display = '';
            else if (status === 'online') card.style.display = card.classList.contains('online') ? '' : 'none';
            else card.style.display = card.classList.contains('offline') ? '' : 'none';
        });
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        if (btn) btn.classList.add('active');
    }
    
    function searchMachines() {
        const query = document.getElementById('searchBox').value.toLowerCase();
        document.querySelectorAll('.machine-card').forEach(card => {
            card.style.display = card.textContent.toLowerCase().includes(query) ? '' : 'none';
        });
    }
    
    function openLoginModal(ip, hostname) {
        document.getElementById('modalIp').value = ip;
        document.getElementById('modalHostname').value = hostname;
        document.getElementById('modalUsername').value = '';
        document.getElementById('modalPassword').value = '';
        document.getElementById('loginModal').style.display = 'flex';
        setTimeout(() => document.getElementById('modalUsername').focus(), 100);
    }
    
    function closeModal() {
        document.getElementById('loginModal').style.display = 'none';
    }
    
    function closeMessageModal() {
        document.getElementById('messageModal').style.display = 'none';
    }
    
    function showMessage(icon, title, text, isSuccess) {
        document.getElementById('messageIcon').textContent = icon;
        document.getElementById('messageTitle').textContent = title;
        document.getElementById('messageTitle').style.color = isSuccess ? '#10b981' : '#ef4444';
        document.getElementById('messageText').textContent = text;
        document.getElementById('messageModal').style.display = 'flex';
    }
    
    async function submitLogin() {
        const ip = document.getElementById('modalIp').value;
        const username = document.getElementById('modalUsername').value;
        const password = document.getElementById('modalPassword').value;
        
        if (!username) { alert('Username is required'); return; }
        
        const response = await fetch('/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: `ip=${encodeURIComponent(ip)}&username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`
        });
        
        const result = await response.json();
        closeModal();
        if (result.success) {
            showMessage('✓', 'Connected!', `Successfully logged into ${ip}`, true);
            setTimeout(() => window.location.href = '/dashboard', 1500);
        } else {
            showMessage('✗', 'Connection Failed', result.error || 'Check credentials and try again', false);
        }
    }
    
    // Allow Enter key in password field
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && document.getElementById('loginModal').style.display === 'flex') {
            submitLogin();
        }
    });
</script>
""")

# ============================================================================
# DASHBOARD TEMPLATE
# ============================================================================

DASHBOARD_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', """
<div class="header">
    <div>
        <h2>📁 Orchestrator Logs & Monitoring</h2>
        <p style="color: var(--color-text-muted); margin-top: 5px;">Connected to: <strong>{{ target_ip }}</strong></p>
    </div>
</div>

<!-- Ansible Setup -->
<div class="log-container">
    <h3>⚙️ Setup Ansible & Playbooks</h3>
    <p style="color: var(--color-text-muted); font-size: 12px; margin-bottom: 15px;">Prepare the target machine: install Ansible and copy playbooks to /tmp/ansible_deploy</p>
    
    <div style="display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap;">
        <button type="button" onclick="checkStatus()" class="action-btn" style="padding: 10px 20px; min-width: 140px;">🔍 Check Status</button>
        <button type="button" onclick="setupMachine()" class="action-btn" style="padding: 10px 20px; min-width: 140px;">📦 Copy & Install</button>
    </div>
    
    <div id="setupStatus" style="background: rgba(0, 215, 255, 0.05); padding: 12px; border-radius: 6px; border: 1px solid var(--color-border); margin-bottom: 15px; display: none;">
        <div id="statusLine" style="font-size: 12px; color: var(--color-text-muted);">Checking...</div>
    </div>
    
    <div id="setupOutput" style="display: none;">
        <h4 style="color: var(--color-primary); margin-bottom: 10px;">📊 Setup Output</h4>
        <pre id="setupLog" style="height: 300px;">⏳ Waiting...</pre>
    </div>
</div>

<!-- Ansible Playbook Runner -->
<div class="log-container">
    <h3>🚀 Deploy with Ansible</h3>
    <p style="color: var(--color-text-muted); font-size: 12px; margin-bottom: 15px;">Select and run Ansible playbooks to deploy and configure the orchestrator</p>
    <div style="display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap;">
        <select id="playbookSelect" style="flex: 1; min-width: 150px; padding: 10px; background: var(--color-bg-dark); border: 1px solid var(--color-border); color: var(--color-text); border-radius: 6px;">
            <option value="">📋 Select Playbook...</option>
            {% for playbook in playbooks %}
                <option value="{{ playbook.name }}">{{ playbook.name }}</option>
            {% endfor %}
        </select>
        <button onclick="runPlaybook()" class="action-btn" style="padding: 10px 20px; min-width: 120px;">▶️ Run Playbook</button>
    </div>
    
    <div id="ansibleOutput" style="display: none;">
        <h4 style="color: var(--color-primary); margin-bottom: 10px;">📊 Execution Output</h4>
        <pre id="outputLog" style="height: 500px;">⏳ Waiting to execute...</pre>
        <div style="display: flex; gap: 10px; align-items: center; margin-top: 10px;">
            <span id="statusIndicator" style="width: 12px; height: 12px; background: #6b7280; border-radius: 50%;"></span>
            <span id="statusText" style="color: var(--color-text-muted);">Ready</span>
        </div>
    </div>
</div>

<!-- Standard Logs -->
<div class="log-container">
    <h3>📄 Standard Logs</h3>
    <p style="color: var(--color-text-muted); font-size: 12px; margin-bottom: 12px;">
        Click to view last 1000 lines &nbsp;|&nbsp; Click 📺 icon for live tail
    </p>
    {% if logs %}
    <ul class="log-list">
        {% for log in logs %}
            <li style="display: flex; gap: 6px;">
                <a href="{{ url_for('view_file', filename=log) }}" class="log-item" style="flex: 1;">📄 {{ log }}</a>
                <a href="{{ url_for('live_tail', filename=log) }}" class="log-item" style="flex: 0; min-width: 44px; padding: 12px 8px;" title="Live Tail">📺</a>
            </li>
        {% endfor %}
    </ul>
    {% else %}
    <p style="color: var(--color-text-muted); text-align: center; padding: 20px;">ℹ️ No .log files found in {{ log_dir }}</p>
    {% endif %}
</div>

<!-- JSON / Gateway Logs -->
<div class="log-container">
    <h3>📊 Gateway JSON Logs (json_logs/)</h3>
    <p style="color: var(--color-text-muted); font-size: 12px; margin-bottom: 12px;">Search by time range (epoch-based) or stream live</p>
    {% if gateway_files %}
    <ul class="log-list">
        {% for file in gateway_files %}
            <li style="display: flex; gap: 6px;">
                <a href="{{ url_for('view_gateway_file', filename=file) }}" class="log-item" style="flex: 1;">📊 {{ file }}</a>
                <a href="{{ url_for('live_tail', filename='json_logs/' + file) }}" class="log-item" style="flex: 0; min-width: 44px; padding: 12px 8px;" title="Live Tail">📺</a>
            </li>
        {% endfor %}
    </ul>
    {% else %}
    <p style="color: var(--color-text-muted); text-align: center; padding: 20px;">ℹ️ No log files found in json_logs/</p>
    {% endif %}
</div>

<style>
    @keyframes pulse-yellow { 0%, 100% { box-shadow: 0 0 6px #f59e0b; } 50% { box-shadow: 0 0 12px #f59e0b; } }
    #statusIndicator.running { background: #f59e0b; animation: pulse-yellow 1s infinite; }
    #statusIndicator.success { background: #10b981; box-shadow: 0 0 6px #10b981; }
    #statusIndicator.failed { background: #ef4444; box-shadow: 0 0 6px #ef4444; }
</style>

<script>
    function escapeHtml(text) {
        return text.replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
    }

    async function runPlaybook() {
        const playbook = document.getElementById('playbookSelect').value;
        if (!playbook) { alert('Please select a playbook first'); return; }
        
        const outputDiv = document.getElementById('ansibleOutput');
        const outputLog = document.getElementById('outputLog');
        const indicator = document.getElementById('statusIndicator');
        const statusText = document.getElementById('statusText');
        
        outputDiv.style.display = 'block';
        outputLog.innerHTML = '';
        indicator.className = 'running';
        statusText.textContent = 'Running...';
        
        try {
            const response = await fetch('/ansible/stream', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: `playbook=${encodeURIComponent(playbook)}`
            });
            
            if (!response.ok) {
                outputLog.innerHTML = `<span style="color:#ef4444">HTTP Error: ${response.status}</span>`;
                indicator.className = 'failed';
                statusText.textContent = 'Request failed';
                return;
            }
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let fullOutput = '';
            
            while (true) {
                const {done, value} = await reader.read();
                if (done) break;
                const chunk = decoder.decode(value, {stream: true});
                fullOutput += chunk;
                
                chunk.split('\\n').forEach(line => {
                    if (!line) return;
                    let styled = escapeHtml(line);
                    if (line.includes('FAILED') || line.includes('fatal') || line.includes('[✗')) {
                        styled = `<span style="color:#ef4444;font-weight:bold">${styled}</span>`;
                        indicator.className = 'failed';
                    } else if (line.includes('changed') || line.includes('ok:') || line.includes('[✓')) {
                        styled = `<span style="color:#10b981">${styled}</span>`;
                    } else if (line.includes('TASK') || line.includes('PLAY')) {
                        styled = `<span style="color:#00d7ff;font-weight:bold">${styled}</span>`;
                    } else if (line.includes('[INFO]')) {
                        styled = `<span style="color:#f59e0b">${styled}</span>`;
                    }
                    outputLog.innerHTML += styled + '\\n';
                    outputLog.scrollTop = outputLog.scrollHeight;
                });
            }
            
            if (fullOutput.includes('[✓ SUCCESS]')) {
                indicator.className = 'success'; statusText.textContent = '✓ Completed Successfully';
            } else if (fullOutput.includes('[✗ FAILED]') || fullOutput.includes('exit code: 1')) {
                indicator.className = 'failed'; statusText.textContent = '✗ Playbook Failed';
            } else {
                indicator.className = 'success'; statusText.textContent = '✓ Done';
            }
        } catch (err) {
            outputLog.innerHTML += `\\n<span style="color:#ef4444">[ERROR] ${escapeHtml(err.message)}</span>`;
            indicator.className = 'failed';
            statusText.textContent = '✗ Failed';
        }
    }
    
    async function checkStatus() {
        const statusDiv = document.getElementById('setupStatus');
        const statusLine = document.getElementById('statusLine');
        statusDiv.style.display = 'block';
        statusLine.textContent = 'Checking...';
        
        try {
            const res = await fetch('/ansible/status');
            const data = await res.json();
            if (data.success) {
                statusLine.innerHTML = `
                    <strong>Ansible:</strong> ${data.ansible_installed ? '✓ Installed' : '✗ Not installed'}<br>
                    <strong>Playbooks:</strong> ${data.playbooks_copied ? '✓ Copied to /tmp/ansible_deploy' : '✗ Not copied yet'}
                `;
            } else {
                statusLine.innerHTML = `<span style="color:#ef4444">${escapeHtml(data.error)}</span>`;
            }
        } catch (err) {
            statusLine.innerHTML = `<span style="color:#ef4444">Error: ${escapeHtml(err.message)}</span>`;
        }
    }
    
    async function setupMachine() {
        const setupOutput = document.getElementById('setupOutput');
        const setupLog = document.getElementById('setupLog');
        setupOutput.style.display = 'block';
        setupLog.innerHTML = '⏳ Starting setup...\\n';
        
        try {
            const response = await fetch('/ansible/setup', { method: 'POST' });
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            
            while (true) {
                const {done, value} = await reader.read();
                if (done) break;
                const chunk = decoder.decode(value, {stream: true});
                chunk.split('\\n').forEach(line => {
                    if (!line) return;
                    let styled = escapeHtml(line);
                    if (line.includes('✓') || line.includes('[✓')) styled = `<span style="color:#10b981">${styled}</span>`;
                    else if (line.includes('✗') || line.includes('[ERROR]')) styled = `<span style="color:#ef4444">${styled}</span>`;
                    else if (line.includes('⚠️') || line.includes('[INFO]')) styled = `<span style="color:#f59e0b">${styled}</span>`;
                    setupLog.innerHTML += styled + '\\n';
                    setupLog.scrollTop = setupLog.scrollHeight;
                });
            }
            setTimeout(checkStatus, 500);
        } catch (err) {
            setupLog.innerHTML += `\\n<span style="color:#ef4444">[ERROR] ${escapeHtml(err.message)}</span>`;
        }
    }
</script>
""")

# ============================================================================
# VIEWER TEMPLATE (standard logs)
# ============================================================================

VIEWER_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', """
<a href="{{ url_for('dashboard') }}" class="back-link">← Back to Dashboard</a>
<a href="{{ url_for('live_tail', filename=filename) }}" class="back-link" style="border-color: var(--color-primary); color: var(--color-primary);">📺 Live Tail</a>

<div class="log-container">
    <h3>📄 {{ filename }}</h3>
    <div style="background: rgba(0, 215, 255, 0.05); padding: 12px; border-radius: 6px; margin-bottom: 15px; border: 1px solid var(--color-border); font-size: 12px; color: var(--color-text-muted);">
        Showing last 1000 lines &nbsp;|&nbsp; Path: <code style="background: #11111b; padding: 2px 6px; border-radius: 3px; color: #10b981;">{{ log_dir }}/{{ filename }}</code>
    </div>
    {% if error %}
        <div class="alert" style="border-color: var(--color-danger); background: rgba(239,68,68,0.1); color: var(--color-danger);">
            ⚠️ {{ error }}
        </div>
    {% endif %}
    <pre id="logContent">{{ content }}</pre>
</div>

<script>
    // Auto scroll to bottom
    const el = document.getElementById('logContent');
    if (el) el.scrollTop = el.scrollHeight;
</script>
""")

# ============================================================================
# GATEWAY / JSON LOG TEMPLATE
# ============================================================================

GATEWAY_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', """
<a href="{{ url_for('dashboard') }}" class="back-link">← Back to Dashboard</a>
<a href="{{ url_for('live_tail', filename='json_logs/' + filename) }}" class="back-link" style="border-color: var(--color-primary); color: var(--color-primary);">📺 Live Tail</a>

<div class="log-container">
    <h3>📊 Gateway Log: {{ filename }}</h3>
    <p style="color: var(--color-text-muted); margin-bottom: 20px; font-size: 12px;">
        Path: <code style="background: #11111b; padding: 4px 8px; border-radius: 4px;">{{ log_dir }}/json_logs/{{ filename }}</code>
    </p>
    
    <!-- Time Range Search -->
    <div style="background: rgba(0, 215, 255, 0.05); padding: 20px; border-radius: 8px; border: 1px solid var(--color-border); margin-bottom: 20px;">
        <h4 style="color: var(--color-primary); margin-bottom: 15px;">🕐 Search by Time Range</h4>
        <p style="color: var(--color-text-muted); font-size: 12px; margin-bottom: 15px;">
            Searches the <code style="background: #11111b; padding: 2px 4px; border-radius: 3px;">timestamp</code> field (milliseconds epoch) in each JSON line.
        </p>
        
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 15px;">
            <div>
                <label style="color: var(--color-text-muted); font-size: 12px; display: block; margin-bottom: 6px;">📅 From (local time)</label>
                <input type="datetime-local" id="fromTime" style="width: 100%; padding: 10px; background: var(--color-bg-dark); border: 1px solid var(--color-border); color: var(--color-text); border-radius: 6px;">
            </div>
            <div>
                <label style="color: var(--color-text-muted); font-size: 12px; display: block; margin-bottom: 6px;">📅 To (local time)</label>
                <input type="datetime-local" id="toTime" style="width: 100%; padding: 10px; background: var(--color-bg-dark); border: 1px solid var(--color-border); color: var(--color-text); border-radius: 6px;">
            </div>
        </div>
        
        <div id="epochPreview" style="font-size: 11px; color: var(--color-text-muted); margin-bottom: 15px; font-family: monospace; min-height: 18px;"></div>
        
        <div style="display: flex; gap: 10px; flex-wrap: wrap;">
            <button onclick="searchByTimeRange()" class="action-btn" style="padding: 10px 24px; min-width: 140px;">🔍 Search</button>
            <button onclick="setLastN(15)" class="action-btn" style="padding: 10px 16px; min-width: 100px;">Last 15 min</button>
            <button onclick="setLastN(60)" class="action-btn" style="padding: 10px 16px; min-width: 100px;">Last 1 hour</button>
            <button onclick="setLastN(360)" class="action-btn" style="padding: 10px 16px; min-width: 100px;">Last 6 hours</button>
        </div>
    </div>
    
    <!-- Results -->
    <div id="searchResults" style="display: none;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
            <h4 style="color: var(--color-primary);">📋 Results <span id="resultCount" style="font-size: 12px; color: var(--color-text-muted);"></span></h4>
            <label style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--color-text-muted); cursor: pointer;">
                <input type="checkbox" id="prettyJson" onchange="togglePretty()"> Pretty-print JSON
            </label>
        </div>
        <pre id="resultsLog" style="height: 600px;"></pre>
    </div>
    
    <div id="searchLoading" style="display: none; text-align: center; padding: 30px; color: var(--color-text-muted);">
        <div style="font-size: 32px; margin-bottom: 10px;">⏳</div>
        <div>Searching logs...</div>
    </div>
</div>

<script>
    const filename = {{ filename | tojson }};
    let rawLines = [];
    
    // Update epoch preview when times change
    ['fromTime', 'toTime'].forEach(id => {
        document.getElementById(id).addEventListener('change', updateEpochPreview);
    });
    
    function updateEpochPreview() {
        const from = document.getElementById('fromTime').value;
        const to = document.getElementById('toTime').value;
        const preview = document.getElementById('epochPreview');
        if (from && to) {
            const fromEpoch = new Date(from).getTime();
            const toEpoch = new Date(to).getTime();
            preview.textContent = `Epoch range: ${fromEpoch} ms → ${toEpoch} ms`;
        } else if (from) {
            preview.textContent = `From epoch: ${new Date(from).getTime()} ms`;
        } else {
            preview.textContent = '';
        }
    }
    
    function setLastN(minutes) {
        const now = new Date();
        const past = new Date(now.getTime() - minutes * 60 * 1000);
        // Format for datetime-local input (YYYY-MM-DDTHH:mm)
        document.getElementById('fromTime').value = toLocalInputValue(past);
        document.getElementById('toTime').value = toLocalInputValue(now);
        updateEpochPreview();
    }
    
    function toLocalInputValue(date) {
        // datetime-local needs local time without timezone offset
        const off = date.getTimezoneOffset() * 60000;
        return new Date(date.getTime() - off).toISOString().slice(0, 16);
    }
    
    async function searchByTimeRange() {
        const from = document.getElementById('fromTime').value;
        const to = document.getElementById('toTime').value;
        
        if (!from || !to) { alert('Please select both From and To times'); return; }
        
        const fromEpoch = new Date(from).getTime();
        const toEpoch = new Date(to).getTime();
        
        if (fromEpoch >= toEpoch) { alert('From time must be before To time'); return; }
        
        document.getElementById('searchLoading').style.display = 'block';
        document.getElementById('searchResults').style.display = 'none';
        
        try {
            const res = await fetch(`/gateway/${encodeURIComponent(filename)}/search`, {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: `from_epoch=${fromEpoch}&to_epoch=${toEpoch}`
            });
            const data = await res.json();
            
            document.getElementById('searchLoading').style.display = 'none';
            document.getElementById('searchResults').style.display = 'block';
            
            if (data.error) {
                document.getElementById('resultsLog').innerHTML = `<span style="color:#ef4444">${escapeHtml(data.error)}</span>`;
                document.getElementById('resultCount').textContent = '';
                return;
            }
            
            rawLines = data.lines || [];
            document.getElementById('resultCount').textContent = `(${rawLines.length} records found)`;
            renderResults();
            
        } catch (err) {
            document.getElementById('searchLoading').style.display = 'none';
            document.getElementById('searchResults').style.display = 'block';
            document.getElementById('resultsLog').innerHTML = `<span style="color:#ef4444">Error: ${escapeHtml(err.message)}</span>`;
        }
    }
    
    function togglePretty() {
        renderResults();
    }
    
    function renderResults() {
        const pretty = document.getElementById('prettyJson').checked;
        const el = document.getElementById('resultsLog');
        
        if (rawLines.length === 0) {
            el.innerHTML = '<span style="color: var(--color-text-muted);">No records found in this time range.</span>';
            return;
        }
        
        let html = '';
        rawLines.forEach((line, i) => {
            if (!line.trim()) return;
            if (pretty) {
                try {
                    const obj = JSON.parse(line);
                    const ts = obj.timestamp || obj.timestamp1;
                    const tsDisplay = ts ? new Date(ts > 1e12 ? ts : ts * 1000).toLocaleString() : '';
                    html += `<span style="color:#4b5563; font-size:11px;">─── Record ${i+1}${tsDisplay ? ' · ' + tsDisplay : ''} ───</span>\\n`;
                    html += escapeHtml(JSON.stringify(obj, null, 2)) + '\\n\\n';
                } catch {
                    html += escapeHtml(line) + '\\n';
                }
            } else {
                html += escapeHtml(line) + '\\n';
            }
        });
        
        el.innerHTML = html;
        el.scrollTop = 0;
    }
    
    function escapeHtml(text) {
        return String(text).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
    }
</script>
""")

# ============================================================================
# LIVE TAIL TEMPLATE
# ============================================================================

LIVE_TAIL_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', """
<a href="{{ url_for('dashboard') }}" class="back-link">← Back to Dashboard</a>

<div class="log-container">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
        <h3>📺 Live Tail: {{ filename }}</h3>
        <div style="display: flex; align-items: center; gap: 10px;">
            <span id="liveIndicator" style="width: 12px; height: 12px; background: #f59e0b; border-radius: 50%;"></span>
            <span id="liveStatus" style="color: var(--color-text-muted); font-size: 12px;">Connecting...</span>
            <button onclick="clearLog()" class="action-btn" style="padding: 4px 10px; font-size: 11px;">🗑 Clear</button>
            <button onclick="togglePause()" id="pauseBtn" class="action-btn" style="padding: 4px 10px; font-size: 11px;">⏸ Pause</button>
        </div>
    </div>
    
    <div style="font-size: 11px; color: var(--color-text-muted); margin-bottom: 10px;">
        Lines received: <span id="lineCount">0</span> &nbsp;|&nbsp; 
        Path: <code style="background: #11111b; padding: 2px 4px; border-radius: 3px;">{{ log_dir }}/{{ filename }}</code>
    </div>
    
    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">
        <label style="font-size: 12px; color: var(--color-text-muted);">
            <input type="checkbox" id="prettyJson" onchange="togglePretty()"> Pretty-print JSON
        </label>
        <label style="font-size: 12px; color: var(--color-text-muted);">
            <input type="checkbox" id="autoScroll" checked> Auto-scroll
        </label>
        <input type="text" id="filterInput" placeholder="Filter lines..." 
               style="padding: 4px 10px; background: var(--color-bg-dark); border: 1px solid var(--color-border); color: var(--color-text); border-radius: 4px; font-size: 12px;"
               oninput="applyFilter()">
    </div>
    
    <pre id="logOutput" style="height: 650px;">⏳ Connecting to live stream...</pre>
</div>

<style>
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
    #liveIndicator.live { background: #10b981; box-shadow: 0 0 6px #10b981; animation: pulse 2s infinite; }
    #liveIndicator.error { background: #ef4444; box-shadow: 0 0 6px #ef4444; }
    #liveIndicator.paused { background: #f59e0b; box-shadow: 0 0 6px #f59e0b; }
</style>

<script>
    const logOutput = document.getElementById('logOutput');
    const indicator = document.getElementById('liveIndicator');
    const liveStatus = document.getElementById('liveStatus');
    const lineCountEl = document.getElementById('lineCount');
    
    let lineCount = 0;
    let paused = false;
    let allLines = [];
    let filterText = '';
    let isPretty = false;
    
    const evtSource = new EventSource("{{ url_for('stream_tail', filename=filename) }}");
    
    evtSource.onopen = () => {
        logOutput.innerHTML = '';
        indicator.className = 'live';
        liveStatus.textContent = 'Live';
    };
    
    evtSource.onmessage = e => {
        if (paused) return;
        const line = e.data;
        allLines.push(line);
        lineCount++;
        lineCountEl.textContent = lineCount;
        
        if (!filterText || line.toLowerCase().includes(filterText)) {
            appendLine(line);
        }
        
        if (document.getElementById('autoScroll').checked) {
            logOutput.scrollTop = logOutput.scrollHeight;
        }
    };
    
    evtSource.onerror = () => {
        indicator.className = 'error';
        liveStatus.textContent = 'Disconnected';
        logOutput.innerHTML += '\\n\\n[Stream closed. Total lines: ' + lineCount + ']';
        evtSource.close();
    };
    
    function appendLine(line) {
        if (isPretty) {
            try {
                const obj = JSON.parse(line);
                const ts = obj.timestamp || obj.timestamp1;
                const tsStr = ts ? new Date(ts > 1e12 ? ts : ts * 1000).toLocaleTimeString() : '';
                logOutput.innerHTML += `<span style="color:#4b5563;font-size:10px;">──── ${tsStr} ────</span>\\n`;
                logOutput.innerHTML += escapeHtml(JSON.stringify(obj, null, 2)) + '\\n\\n';
            } catch {
                logOutput.innerHTML += escapeHtml(line) + '\\n';
            }
        } else {
            logOutput.innerHTML += escapeHtml(line) + '\\n';
        }
    }
    
    function clearLog() {
        logOutput.innerHTML = '';
        allLines = [];
        lineCount = 0;
        lineCountEl.textContent = '0';
    }
    
    function togglePause() {
        paused = !paused;
        const btn = document.getElementById('pauseBtn');
        if (paused) {
            btn.textContent = '▶ Resume';
            indicator.className = 'paused';
            liveStatus.textContent = 'Paused';
        } else {
            btn.textContent = '⏸ Pause';
            indicator.className = 'live';
            liveStatus.textContent = 'Live';
        }
    }
    
    function togglePretty() {
        isPretty = document.getElementById('prettyJson').checked;
        // Re-render all lines
        logOutput.innerHTML = '';
        allLines.forEach(line => {
            if (!filterText || line.toLowerCase().includes(filterText)) appendLine(line);
        });
    }
    
    function applyFilter() {
        filterText = document.getElementById('filterInput').value.toLowerCase();
        logOutput.innerHTML = '';
        allLines.forEach(line => {
            if (!filterText || line.toLowerCase().includes(filterText)) appendLine(line);
        });
    }
    
    function escapeHtml(text) {
        return String(text).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
    }
    
    window.addEventListener('beforeunload', () => evtSource.close());
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
    ip = request.form.get('ip', '')
    username = request.form.get('username', '')
    password = request.form.get('password', '')

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        if password:
            client.connect(hostname=ip, username=username, password=password, timeout=10)
        else:
            client.connect(hostname=ip, username=username, timeout=10, look_for_keys=True)
            
        session_id = str(uuid.uuid4())
        active_ssh_sessions[session_id] = client
        session['ssh_id'] = session_id
        session['target_ip'] = ip
        return jsonify({"success": True, "message": f"Connected to {ip}"})
    except paramiko.AuthenticationException:
        return jsonify({"success": False, "error": "Authentication failed. Check credentials or SSH key authorization."})
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

    playbooks = get_playbooks()
    
    # Get standard .log files
    out_base, err_base = execute_ssh(f"ls -1 {LOG_DIR}/*.log 2>/dev/null")
    target_logs = []
    if out_base:
        target_logs = [f.strip().split('/')[-1] for f in out_base.split('\n') if f.strip().endswith('.log')]

    # Get json_logs files
    out_json, err_json = execute_ssh(f"ls -1 {LOG_DIR}/json_logs/*.log 2>/dev/null || ls -1 {LOG_DIR}/json_logs/*.json 2>/dev/null")
    gateway_files = []
    if out_json:
        gateway_files = [f.strip().split('/')[-1] for f in out_json.split('\n') if f.strip()]

    return render_template_string(
        DASHBOARD_TEMPLATE,
        target_ip=session.get('target_ip'),
        logs=target_logs,
        gateway_files=gateway_files,
        playbooks=playbooks,
        log_dir=LOG_DIR
    )

@app.route('/view/<path:filename>')
def view_file(filename):
    if 'ssh_id' not in session:
        return redirect(url_for('machines'))
    
    # Sanitize filename to prevent path traversal
    safe_filename = filename.replace('..', '').lstrip('/')
    full_path = f"{LOG_DIR}/{safe_filename}"
    
    out, err = execute_ssh(f"tail -n 1000 {full_path} 2>&1")
    
    return render_template_string(
        VIEWER_TEMPLATE,
        filename=safe_filename,
        content=out or '',
        error=err if not out else None,
        log_dir=LOG_DIR
    )

@app.route('/gateway/<filename>')
def view_gateway_file(filename):
    if 'ssh_id' not in session:
        return redirect(url_for('machines'))
    return render_template_string(GATEWAY_TEMPLATE, filename=filename, log_dir=LOG_DIR)

@app.route('/gateway/<filename>/search', methods=['POST'])
def search_gateway_json(filename):
    """Search JSON log by epoch time range. JSON lines must have a 'timestamp' field in ms."""
    if 'ssh_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    try:
        from_epoch = int(request.form.get('from_epoch', 0))
        to_epoch = int(request.form.get('to_epoch', 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid epoch values"}), 400
    
    if from_epoch <= 0 or to_epoch <= 0 or from_epoch >= to_epoch:
        return jsonify({"error": "Invalid time range"}), 400
    
    safe_filename = filename.replace('..', '').lstrip('/')
    log_path = f"{LOG_DIR}/json_logs/{safe_filename}"
    
    # Python one-liner on the remote machine:
    # Read each line, parse JSON, check if timestamp (ms) is in range, print matching lines.
    # Handles both ms-epoch (>1e12) and s-epoch fields.
    python_cmd = (
        f"python3 -c \""
        f"import sys, json; "
        f"f=open('{log_path}'); "
        f"[print(l.rstrip()) for l in f "
        f"if (lambda t: t is not None and {from_epoch} <= (t if t > 1e12 else t*1000) <= {to_epoch})"
        f"((lambda o: o.get('timestamp') or o.get('timestamp1'))"
        f"(json.loads(l) if l.strip() else {{}}))"
        f"] ; f.close()"
        f"\" 2>&1 || echo 'ERROR: Could not read file'"
    )
    
    out, err = execute_ssh(python_cmd)
    
    if err and not out:
        return jsonify({"error": f"SSH error: {err}"}), 500
    
    lines = [l for l in (out or '').split('\n') if l.strip()]
    
    # Check for error output
    if len(lines) == 1 and lines[0].startswith('ERROR:'):
        return jsonify({"error": lines[0]}), 500
    
    return jsonify({
        "lines": lines,
        "count": len(lines),
        "from_epoch": from_epoch,
        "to_epoch": to_epoch
    })

@app.route('/live_tail/<path:filename>')
def live_tail(filename):
    if 'ssh_id' not in session:
        return redirect(url_for('machines'))
    return render_template_string(LIVE_TAIL_TEMPLATE, filename=filename, log_dir=LOG_DIR)

@app.route('/stream/<path:filename>')
def stream_tail(filename):
    """SSE endpoint: streams tail -f output as server-sent events."""
    session_id = session.get('ssh_id')
    client = active_ssh_sessions.get(session_id)
    
    safe_filename = filename.replace('..', '').lstrip('/')
    full_path = f"{LOG_DIR}/{safe_filename}"

    def generate():
        if not client:
            yield "data: [ERROR] Session expired. Please reconnect.\n\n"
            return
        try:
            # First send last 50 lines, then follow
            stdin, stdout, stderr = client.exec_command(
                f"tail -n 50 -f {full_path} 2>&1",
                get_pty=True
            )
            for line in iter(stdout.readline, ""):
                if line:
                    yield f"data: {line.rstrip()}\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

# ============================================================================
# ANSIBLE ROUTES
# ============================================================================

@app.route('/ansible/stream', methods=['POST'])
def ansible_stream():
    playbook = request.form.get('playbook', '')
    session_id = session.get('ssh_id', '')
    
    if not playbook or not session_id:
        return Response("ERROR: Missing playbook or SSH session\n", mimetype='text/plain')
    
    if session_id not in active_ssh_sessions:
        return Response("ERROR: SSH session not found. Please log back in.\n", mimetype='text/plain')
    
    client = active_ssh_sessions.get(session_id)
    
    def generate():
        try:
            yield f"[INFO] Checking for playbook: {playbook}.yml in /tmp/ansible_deploy...\n"
            stdin, stdout, stderr = client.exec_command(f'ls /tmp/ansible_deploy/{playbook}.yml 2>/dev/null')
            check_code = stdout.channel.recv_exit_status()
            
            if check_code != 0:
                yield f"[✗ ERROR] Playbook '{playbook}.yml' not found in /tmp/ansible_deploy\n"
                yield "[INFO] Use 'Copy & Install' button to transfer playbooks first.\n"
                return
            
            yield "[✓ OK] Playbook found\n\n"
            
            yield "[INFO] Checking Ansible...\n"
            stdin, stdout, stderr = client.exec_command('which ansible-playbook')
            if stdout.channel.recv_exit_status() != 0:
                yield "[⚠️  WARNING] Ansible not installed. Installing...\n"
                stdin, stdout, stderr = client.exec_command(
                    'sudo apt-get update -qq && sudo apt-get install -y ansible', get_pty=True)
                for line in iter(stdout.readline, ''):
                    if line: yield line
                if stdout.channel.recv_exit_status() != 0:
                    yield "[✗ ERROR] Failed to install Ansible\n"
                    return
                yield "[✓ SUCCESS] Ansible installed\n\n"
            else:
                yield "[✓ OK] Ansible is installed\n\n"
            
            yield "─" * 70 + "\n"
            yield f"[INFO] Running: {playbook}.yml\n"
            yield "─" * 70 + "\n\n"
            
            cmd = f"cd /tmp/ansible_deploy && PYTHONWARNINGS=ignore ANSIBLE_PYTHON_INTERPRETER=/usr/bin/python3 ansible-playbook {playbook}.yml -i localhost, -c local -v 2>&1"
            yield f"[INFO] Command: {cmd}\n\n"
            
            stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
            for line in iter(stdout.readline, ''):
                if line: yield line
            
            exit_code = stdout.channel.recv_exit_status()
            yield "\n" + "─" * 70 + "\n"
            if exit_code == 0:
                yield "[✓ SUCCESS] Playbook completed successfully\n"
            else:
                yield f"[✗ FAILED] Playbook failed with exit code: {exit_code}\n"
        
        except Exception as e:
            yield f"\n[ERROR] Exception: {str(e)}\n"
            import traceback
            yield traceback.format_exc()
    
    return Response(generate(), mimetype='text/plain')

@app.route('/ansible/status', methods=['GET'])
def ansible_status():
    session_id = session.get('ssh_id')
    if not session_id or session_id not in active_ssh_sessions:
        return jsonify({"success": False, "error": "SSH session not found"})
    
    client = active_ssh_sessions.get(session_id)
    try:
        return jsonify({
            "success": True,
            "ansible_installed": check_ansible_on_target(client),
            "playbooks_copied": check_playbooks_on_target(client)
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/ansible/setup', methods=['POST'])
def ansible_setup():
    session_id = session.get('ssh_id')
    if not session_id or session_id not in active_ssh_sessions:
        return Response("ERROR: SSH session not found\n", mimetype='text/plain')
    
    client = active_ssh_sessions.get(session_id)
    
    def generate():
        try:
            yield "[INFO] Creating /tmp/ansible_deploy...\n"
            client.exec_command('mkdir -p /tmp/ansible_deploy')
            
            yield "[INFO] Copying playbooks via SFTP...\n"
            sftp = client.open_sftp()
            copied = 0
            
            if PLAYBOOKS_DIR.exists():
                for f in PLAYBOOKS_DIR.glob("*.yml"):
                    try:
                        sftp.put(str(f), f"/tmp/ansible_deploy/{f.name}")
                        yield f"  ✓ Copied {f.name}\n"
                        copied += 1
                    except Exception as e:
                        yield f"  ✗ Failed {f.name}: {e}\n"
            
            inv_dir = ANSIBLE_DIR / "inventory"
            if inv_dir.exists():
                client.exec_command('mkdir -p /tmp/ansible_deploy/inventory')
                for f in inv_dir.glob("*.yml"):
                    try:
                        sftp.put(str(f), f"/tmp/ansible_deploy/inventory/{f.name}")
                        yield f"  ✓ Copied inventory/{f.name}\n"
                    except Exception as e:
                        yield f"  ⚠️  inventory/{f.name}: {e}\n"
            
            sftp.close()
            
            if copied == 0:
                yield "[✗ ERROR] No playbooks were copied\n"
                return
            
            yield f"[✓ OK] {copied} playbooks copied\n\n"
            
            yield "[INFO] Checking Ansible...\n"
            stdin, stdout, stderr = client.exec_command('which ansible-playbook')
            if stdout.channel.recv_exit_status() != 0:
                yield "[⚠️  WARNING] Installing Ansible...\n"
                stdin, stdout, stderr = client.exec_command(
                    'sudo apt-get update -qq && sudo apt-get install -y ansible', get_pty=True)
                for line in iter(stdout.readline, ''):
                    if line: yield line
                yield "[✓ SUCCESS] Ansible installed\n\n"
            else:
                yield "[✓ OK] Ansible already installed\n\n"
            
            yield "[INFO] Verifying...\n"
            stdin, stdout, stderr = client.exec_command('ls /tmp/ansible_deploy/')
            yield stdout.read().decode('utf-8') + "\n"
            yield "[✓ SUCCESS] Target machine is ready!\n"
        
        except Exception as e:
            yield f"\n[ERROR] Setup failed: {str(e)}\n"
            import traceback
            yield traceback.format_exc()
    
    return Response(generate(), mimetype='text/plain')

if __name__ == '__main__':
    print("""
    ╔════════════════════════════════════════════════════╗
    ║   Orchestrator Manager - Full Integration         ║
    ╚════════════════════════════════════════════════════╝
    
    🌐 http://localhost:5005
    
    Features:
    ✓ Tailscale machine discovery
    ✓ SSH login (password or key)
    ✓ Browse orchestrator logs (tail -n 1000)
    ✓ Live tail with pretty-print & filter
    ✓ JSON log search by epoch time range
    ✓ Run Ansible playbooks with streaming output
    """)
    
    app.run(host='127.0.0.1', port=5005, debug=True, use_reloader=False)