#!/usr/bin/env python3
"""
Enhanced Tailscale Machine Viewer + Orchestrator Node Manager
Updates: MagicDNS, SQLite persistence, dual-location standard/JSON logs,
3-second buffered live tailing, performance monitoring, and JSON timestamp1 range extraction.
"""

import os
import json
import uuid
import subprocess
import paramiko
import socket
import threading
import time
import queue
import sqlite3
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template_string, jsonify, request, session, redirect, url_for, flash, Response, send_file
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configuration
LINUX_USER = os.getenv("LINUX_USER", "mpr")
BASE_PATH = "/opt/go-ble-orchestrator"
LOG_DIRS = [f"{BASE_PATH}/logs", BASE_PATH]
JSON_LOG_DIRS = [f"{BASE_PATH}/logs/json_logs", f"{BASE_PATH}/json_logs"]
DB_PATH = Path(__file__).parent / "orchestrator_nodes.db"

# ============================================================================
# DATABASE LOGIC
# ============================================================================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS known_nodes 
                 (magic_dns TEXT PRIMARY KEY, last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def save_node_to_db(magic_dns):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO known_nodes (magic_dns, last_seen) VALUES (?, CURRENT_TIMESTAMP)", (magic_dns,))
    conn.commit()
    conn.close()

def get_stored_nodes():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT magic_dns FROM known_nodes")
    nodes = [row[0] for row in c.fetchall()]
    conn.close()
    return nodes

# ============================================================================
# UTILITIES
# ============================================================================

def parse_datetime_to_epoch(dt_str):
    """Parse 'YYYY-MM-DDTHH:MM' string from browser input to epoch seconds."""
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M")
        return int(dt.timestamp())
    except Exception:
        return None

# ============================================================================
# SSH & BUFFERED STREAMING LOGIC
# ============================================================================

active_ssh_sessions = {}

class BufferedTailStreamer:
    """Handles 3-second chunked data loading in the background."""
    def __init__(self, client, full_path):
        self.client = client
        self.full_path = full_path
        self.queue = queue.Queue(maxsize=10)
        self.stop_event = threading.Event()

    def _worker(self):
        """Pre-fetches data every 3 seconds."""
        # Initial burst: last 50 lines
        stdin, stdout, stderr = self.client.exec_command(f"tail -n 50 {self.full_path}")
        self.queue.put(stdout.read().decode('utf-8', errors='ignore'))

        while not self.stop_event.is_set():
            time.sleep(3)
            # Fetch what's new (using a simple tail for the chunk)
            stdin, stdout, stderr = self.client.exec_command(f"tail -n 20 {self.full_path}")
            data = stdout.read().decode('utf-8', errors='ignore')
            if data:
                self.queue.put(data)

    def stream(self):
        thread = threading.Thread(target=self._worker, daemon=True)
        thread.start()
        try:
            while not self.stop_event.is_set():
                try:
                    chunk = self.queue.get(timeout=5)
                    yield f"data: {chunk}\n\n"
                except queue.Empty:
                    yield "data: ...waiting for data...\n\n"
        finally:
            self.stop_event.set()

def execute_ssh(command, timeout=30):
    session_id = session.get('ssh_id')
    if not session_id or session_id not in active_ssh_sessions:
        return None, "Session expired."
    client = active_ssh_sessions[session_id]
    try:
        stdin, stdout, stderr = client.exec_command(command)
        stdout.channel.settimeout(timeout)
        exit_status = stdout.channel.recv_exit_status()
        out = stdout.read().decode('utf-8', errors='ignore')
        err = stderr.read().decode('utf-8', errors='ignore')
        return out if exit_status == 0 else (out or None), err if exit_status != 0 else None
    except Exception as e:
        return None, str(e)

# ============================================================================
# TAILSCALE POWERSHELL INTEGRATION
# ============================================================================

def get_machines_via_powershell():
    try:
        result = subprocess.run(["powershell", "-Command", "tailscale status --json"], 
                                capture_output=True, text=True, check=True, timeout=10)
        data = json.loads(result.stdout)
        peers = data.get('Peer', {})
        stored_dns = get_stored_nodes()
        machines = []
        for p_id, p_data in peers.items():
            dns = p_data.get('DNSName', '').rstrip('.')
            if not dns: continue
            online = p_data.get('Online', False)
            if online and dns not in stored_dns: save_node_to_db(dns)
            machines.append({
                'magic_dns': dns, 'ip': p_data.get('TailscaleIPs', ['Unknown'])[0],
                'online': online, 'os': p_data.get('OS', 'Unknown')
            })
        return sorted(machines, key=lambda x: (not x['online'], x['magic_dns']))
    except:
        return [{'magic_dns': d, 'online': False} for d in get_stored_nodes()]

# ============================================================================
# TEMPLATES
# ============================================================================

BASE_UI = """
<!DOCTYPE html>
<html>
<head>
    <title>MagicDNS Orchestrator</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background: #0f172a; color: #f8fafc; font-family: ui-sans-serif, system-ui; }
        .card { background: #1e293b; border: 1px solid #334155; border-radius: 0.75rem; }
        .btn-cyan { background: #0891b2; transition: 0.2s; }
        .btn-cyan:hover { background: #06b6d4; }
        .status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
        .online { background: #10b981; box-shadow: 0 0 8px #10b981; }
        .offline { background: #ef4444; }
        pre { background: #020617; padding: 1rem; border-radius: 0.5rem; overflow: auto; color: #94a3b8; font-size: 12px; line-height: 1.5; }
        .loader { border: 2px solid #f3f3f3; border-top: 2px solid #22d3ee; border-radius: 50%; width: 14px; height: 14px; animation: spin 1s linear infinite; display: inline-block; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        input[type="datetime-local"], select { color-scheme: dark; }
    </style>
</head>
<body class="p-6">
    <div class="max-w-6xl mx-auto">
        <header class="flex justify-between items-center mb-8 pb-4 border-b border-slate-800">
            <h1 class="text-2xl font-bold text-cyan-400">🌐 Node Orchestrator</h1>
            <div class="flex gap-4">
                {% if session.get('target_dns') %}
                <span class="bg-slate-800 px-3 py-1 rounded text-sm border border-slate-700">📍 {{ session.target_dns }}</span>
                <a href="/logout" class="text-red-400 hover:text-red-300 text-sm font-bold">Logout</a>
                {% endif %}
                <button onclick="location.reload()" class="bg-slate-800 hover:bg-slate-700 px-4 py-1 rounded text-sm border border-slate-700">Refresh</button>
            </div>
        </header>

        {% with messages = get_flashed_messages() %}{% if messages %}
            {% for m in messages %}<div class="bg-blue-900/30 border border-blue-500 p-4 rounded mb-6 text-blue-200">{{ m }}</div>{% endfor %}
        {% endif %}{% endwith %}

        {% block content %}{% endblock %}
    </div>

    <!-- Login Modal -->
    <div id="loginModal" class="hidden fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4">
        <div class="bg-slate-900 border-2 border-cyan-500 p-8 rounded-2xl w-full max-sm shadow-2xl">
            <h3 class="text-xl font-bold text-cyan-400 mb-2">🔐 SSH Login</h3>
            <p id="modalDnsDisplay" class="text-xs text-slate-500 mb-6 font-mono"></p>
            <input type="hidden" id="modalDnsInput">
            <div class="space-y-4">
                <div>
                    <label class="block text-[10px] uppercase font-bold text-slate-500 mb-1">Username</label>
                    <input type="text" id="modalUser" value="{{ default_user }}" class="w-full bg-slate-800 border border-slate-700 p-2.5 rounded-lg text-white focus:ring-1 focus:ring-cyan-500 outline-none">
                </div>
                <div>
                    <label class="block text-[10px] uppercase font-bold text-slate-500 mb-1">Password</label>
                    <input type="password" id="modalPass" placeholder="••••••••" class="w-full bg-slate-800 border border-slate-700 p-2.5 rounded-lg text-white focus:ring-1 focus:ring-cyan-500 outline-none">
                </div>
                <div class="flex gap-3 pt-2">
                    <button id="loginBtn" onclick="submitLogin()" class="flex-1 bg-cyan-600 py-2.5 rounded-lg font-bold hover:bg-cyan-500 text-sm">Connect</button>
                    <button onclick="document.getElementById('loginModal').classList.add('hidden')" class="flex-1 bg-slate-800 py-2.5 rounded-lg font-bold hover:bg-slate-700 text-sm text-slate-400">Cancel</button>
                </div>
            </div>
            <div id="loginError" class="mt-4 text-xs text-red-400 hidden text-center"></div>
        </div>
    </div>

    <script>
        function openLogin(dns) {
            document.getElementById('modalDnsInput').value = dns;
            document.getElementById('modalDnsDisplay').innerText = dns;
            document.getElementById('loginModal').classList.remove('hidden');
            document.getElementById('modalPass').focus();
        }
        async function submitLogin() {
            const dns = document.getElementById('modalDnsInput').value;
            const user = document.getElementById('modalUser').value;
            const pass = document.getElementById('modalPass').value;
            const btn = document.getElementById('loginBtn');
            btn.disabled = true; btn.innerText = 'Connecting...';
            const res = await fetch('/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: `magic_dns=${encodeURIComponent(dns)}&username=${encodeURIComponent(user)}&password=${encodeURIComponent(pass)}`
            });
            const data = await res.json();
            if(data.success) { window.location.href = '/dashboard'; }
            else { alert(data.error); btn.disabled = false; btn.innerText = 'Connect'; }
        }
    </script>
</body>
</html>
"""

# ============================================================================
# ROUTES
# ============================================================================

@app.route('/')
def index():
    machines = get_machines_via_powershell()
    html = """
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {% for m in machines %}
        <div class="card p-6 flex flex-col justify-between">
            <div>
                <div class="flex justify-between items-center mb-4">
                    <span class="status-dot {% if m.online %}online{% else %}offline{% endif %}"></span>
                    <span class="text-[10px] font-mono text-slate-500">{{ m.ip }}</span>
                </div>
                <h3 class="text-md font-bold truncate mb-1">{{ m.magic_dns }}</h3>
                <p class="text-xs text-slate-500">{{ m.os }}</p>
            </div>
            <button onclick="openLogin('{{ m.magic_dns }}')" class="mt-6 w-full bg-cyan-600/10 hover:bg-cyan-600 border border-cyan-600/30 py-2 rounded-lg text-xs font-bold transition-all">SSH Access</button>
        </div>
        {% endfor %}
    </div>
    """
    return render_template_string(BASE_UI.replace('{% block content %}{% endblock %}', html), machines=machines, default_user=LINUX_USER)

@app.route('/login', methods=['POST'])
def login():
    dns, user, pw = request.form.get('magic_dns'), request.form.get('username'), request.form.get('password')
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(hostname=dns, username=user, password=pw, timeout=8)
        save_node_to_db(dns)
        sid = str(uuid.uuid4())
        active_ssh_sessions[sid] = client
        session['ssh_id'], session['target_dns'] = sid, dns
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/dashboard')
def dashboard():
    if 'ssh_id' not in session: return redirect('/')
    
    # Get Standard Logs
    std_logs = []
    for d in LOG_DIRS:
        out, _ = execute_ssh(f"ls -1 {d}/*.log 2>/dev/null")
        if out: std_logs.extend([f.split('/')[-1] for f in out.split('\n') if f.strip()])
    
    # Get JSON Logs
    json_logs = []
    for d in JSON_LOG_DIRS:
        out, _ = execute_ssh(f"ls -1 {d}/*.log 2>/dev/null")
        if out: json_logs.extend([f.split('/')[-1] for f in out.split('\n') if f.strip()])

    unique_json_logs = sorted(list(set(json_logs)))

    html = """
    <div class="mb-6 flex gap-4"><a href="/" class="text-cyan-400 text-sm">← Machine List</a></div>
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <div class="space-y-8">
            <div class="card p-6">
                <h3 class="text-lg font-bold mb-4 text-cyan-400">📄 System Logs</h3>
                <div class="grid grid-cols-1 gap-2">
                    {% for log in std_logs|unique|sort %}
                    <div class="flex justify-between items-center bg-slate-800/40 p-3 rounded-lg border border-slate-700">
                        <span class="text-xs font-mono">{{ log }}</span>
                        <div class="flex gap-2">
                            <a href="/view/{{ log }}" class="text-[10px] bg-slate-700 px-2 py-1 rounded">View</a>
                            <a href="/tail/{{ log }}" class="text-[10px] bg-cyan-900/50 text-cyan-400 px-2 py-1 rounded">Live</a>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
            <div class="card p-6 border-emerald-500/30">
                <h3 class="text-lg font-bold mb-4 text-emerald-400">📊 JSON Log Browser</h3>
                <div class="grid grid-cols-1 gap-2 mb-6">
                    {% for log in json_logs %}
                    <div class="flex justify-between items-center bg-slate-800/40 p-3 rounded-lg border border-slate-700">
                        <span class="text-xs font-mono">{{ log }}</span>
                        <div class="flex gap-2">
                            <a href="/view/{{ log }}?type=json" class="text-[10px] bg-slate-700 px-2 py-1 rounded">View</a>
                            <a href="/tail/{{ log }}?type=json" class="text-[10px] bg-emerald-900/50 text-emerald-400 px-2 py-1 rounded">Live</a>
                        </div>
                    </div>
                    {% endfor %}
                </div>

                <div class="pt-6 border-t border-slate-700">
                    <h4 class="text-sm font-bold mb-3 text-emerald-400">📥 Download JSON Data by Time</h4>
                    <p class="text-[10px] text-slate-500 mb-3">Searches the <code class="bg-black p-0.5 rounded text-emerald-500 font-mono">timestamp1</code> field.</p>
                    <form action="/api/collect_json" method="POST" class="space-y-3">
                        <div>
                            <label class="block text-[10px] uppercase font-bold text-slate-500 mb-1">Select File</label>
                            <select name="log_file" class="w-full bg-slate-900 border border-slate-700 p-2 rounded text-xs outline-none focus:border-emerald-500">
                                <option value="all">All JSON Logs</option>
                                {% for log in json_logs %}
                                <option value="{{ log }}">{{ log }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div class="grid grid-cols-2 gap-3">
                            <div>
                                <label class="block text-[10px] uppercase font-bold text-slate-500 mb-1">From</label>
                                <input type="datetime-local" name="from_time" required class="w-full bg-slate-900 border border-slate-700 p-2 rounded text-xs outline-none focus:border-emerald-500">
                            </div>
                            <div>
                                <label class="block text-[10px] uppercase font-bold text-slate-500 mb-1">To</label>
                                <input type="datetime-local" name="to_time" required class="w-full bg-slate-900 border border-slate-700 p-2 rounded text-xs outline-none focus:border-emerald-500">
                            </div>
                        </div>
                        <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-2 rounded text-xs transition">Collect & Download</button>
                    </form>
                </div>
            </div>
        </div>
        <div class="card p-6 h-fit">
            <h3 class="text-lg font-bold mb-4 text-amber-400">🛠 Performance & Monitoring</h3>
            <div class="grid grid-cols-2 gap-3">
                <button onclick="runCmd('top -b -n 1 | head -n 20')" class="bg-slate-800 p-3 rounded-lg border border-slate-700 text-xs text-left hover:border-amber-500">Standard Top</button>
                <button onclick="runCmd('btop --one-out || htop --version && echo \"Running htop snapshot...\" && htop -C -n 1')" class="bg-slate-800 p-3 rounded-lg border border-slate-700 text-xs text-left hover:border-amber-500">btop/htop Snapshot</button>
                <button onclick="runCmd('df -h')" class="bg-slate-800 p-3 rounded-lg border border-slate-700 text-xs text-left hover:border-amber-500">Disk Space</button>
                <button onclick="runCmd('uptime')" class="bg-slate-800 p-3 rounded-lg border border-slate-700 text-xs text-left hover:border-amber-500">System Uptime</button>
            </div>
            <div id="cmdOutput" class="hidden mt-6 pt-6 border-t border-slate-800">
                <pre id="cmdResult" class="text-[10px] h-64"></pre>
            </div>
        </div>
    </div>
    <script>
        async function runCmd(c) {
            const out = document.getElementById('cmdOutput');
            const res = document.getElementById('cmdResult');
            out.classList.remove('hidden'); res.innerText = 'Executing...';
            const resp = await fetch('/api/exec', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: `cmd=${encodeURIComponent(c)}`
            });
            const data = await resp.json();
            res.innerText = data.output || data.error;
        }
    </script>
    """
    return render_template_string(BASE_UI.replace('{% block content %}{% endblock %}', html), std_logs=std_logs, json_logs=unique_json_logs)

@app.route('/api/exec', methods=['POST'])
def api_exec():
    cmd = request.form.get('cmd')
    out, err = execute_ssh(cmd)
    return jsonify({"output": out, "error": err})

@app.route('/api/collect_json', methods=['POST'])
def collect_json():
    """Collect JSON log entries by timestamp1 epoch and stream for download."""
    if 'ssh_id' not in session: return redirect('/')
    
    start_ts = parse_datetime_to_epoch(request.form.get('from_time'))
    end_ts = parse_datetime_to_epoch(request.form.get('to_time'))
    selected_file = request.form.get('log_file')
    
    if not start_ts or not end_ts:
        flash("Invalid time range provided.")
        return redirect(url_for('dashboard'))

    # Build awk command to search across selected file(s)
    if selected_file == 'all':
        patterns = " ".join([f"{d}/*.log" for d in (LOG_DIRS + JSON_LOG_DIRS)])
    else:
        patterns = " ".join([f"{d}/{selected_file}" for d in (LOG_DIRS + JSON_LOG_DIRS)])
    
    # Updated command targets 'timestamp1' instead of 'timestamp'
    # Field separator (-F) matches the key name including quotes and colon
    # split($2, a, "[,}]") extracts the value after the separator until a delimiter
    search_cmd = (
        f"grep -h '\"timestamp1\"' {patterns} 2>/dev/null | "
        f"awk -F'\"timestamp1\":' '{{ split($2, a, \"[,}}]\"); ts=a[1]; "
        f"if (ts >= {start_ts} && ts <= {end_ts}) print $0 }}'"
    )
    
    out, err = execute_ssh(search_cmd, timeout=60)
    
    if (err and not out) or not out or not out.strip():
        flash("No data found for the selected file and time range.")
        return redirect(url_for('dashboard'))

    file_label = selected_file.replace('.log', '') if selected_file != 'all' else 'all'
    filename = f"logs_{file_label}_{start_ts}_{end_ts}.json"
    return Response(
        out,
        mimetype="application/json",
        headers={"Content-disposition": f"attachment; filename={filename}"}
    )

@app.route('/view/<filename>')
def view_log(filename):
    if 'ssh_id' not in session: return redirect('/')
    is_json = request.args.get('type') == 'json'
    targets = JSON_LOG_DIRS if is_json else LOG_DIRS
    find_cmd = f"for d in {' '.join(targets)}; do if [ -f \"$d/{filename}\" ]; then tail -n 500 \"$d/{filename}\"; exit 0; fi; done; exit 1"
    out, err = execute_ssh(find_cmd)
    html = """
    <div class="mb-4 flex justify-between items-center"><a href="/dashboard" class="text-cyan-400 text-sm">← Dashboard</a><h2 class="text-xs font-mono">{{ filename }}</h2></div>
    <pre class="h-[70vh]">{{ content }}</pre>
    """
    return render_template_string(BASE_UI.replace('{% block content %}{% endblock %}', html), content=out or err, filename=filename)

@app.route('/tail/<filename>')
def tail_view(filename):
    if 'ssh_id' not in session: return redirect('/')
    is_json = request.args.get('type') == 'json'
    html = f"""
    <div class="mb-4 flex justify-between items-center"><a href="/dashboard" class="text-cyan-400 text-sm">← Dashboard</a><h2 class="text-xs font-mono">{filename} [Buffered 3s]</h2></div>
    <pre id="tailOutput" class="h-[75vh] whitespace-pre-wrap"></pre>
    <script>
        const output = document.getElementById('tailOutput');
        const source = new EventSource("/stream/{filename}?type={'json' if is_json else 'std'}");
        source.onmessage = function(e) {{
            const node = document.createTextNode(e.data + "\\n");
            output.appendChild(node);
            output.scrollTop = output.scrollHeight;
            if (output.childNodes.length > 500) output.removeChild(output.firstChild);
        }};
        source.onerror = function() {{ source.close(); }};
    </script>
    """
    return render_template_string(BASE_UI.replace('{% block content %}{% endblock %}', html))

@app.route('/stream/<filename>')
def stream_log(filename):
    sid = session.get('ssh_id')
    client = active_ssh_sessions.get(sid)
    if not client: return Response("Unauthorized", status=401)
    
    is_json = request.args.get('type') == 'json'
    dirs = JSON_LOG_DIRS if is_json else LOG_DIRS
    
    full_path = None
    for d in dirs:
        stdin, stdout, stderr = client.exec_command(f"if [ -f {d}/{filename} ]; then echo {d}/{filename}; fi")
        path = stdout.read().decode().strip()
        if path:
            full_path = path
            break
    
    if not full_path: return Response("File not found", status=404)
    
    streamer = BufferedTailStreamer(client, full_path)
    return Response(streamer.stream(), mimetype='text/event-stream')

if __name__ == '__main__':
    init_db()
    app.run(host='127.0.0.1', port=5005, debug=False)