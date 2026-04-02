import os
import uuid
import paramiko
import requests
from flask import Flask, request, render_template_string, redirect, url_for, session, flash, Response

app = Flask(__name__)
app.secret_key = os.urandom(24) 

# --- CONFIGURATION ---
TAILSCALE_API_KEY = os.getenv("TAILSCALE_API_KEY") 
LOG_DIR = "/opt/go-ble-orchestrator/logs"

# In-memory storage for active SSH sockets
active_ssh_sessions = {}

# --- HTML TEMPLATES ---
BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Orchestrator Node Manager</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 20px; background-color: #1e1e2e; color: #cdd6f4; }
        .container { max-width: 1000px; margin: auto; background: #313244; padding: 25px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        h1, h2, h3 { color: #f38ba8; }
        button, .btn { padding: 10px 15px; margin: 5px; cursor: pointer; background: #89b4fa; color: #11111b; border: none; border-radius: 4px; text-decoration: none; display: inline-block; font-weight: bold; }
        button:hover, .btn:hover { background: #74c7ec; }
        .btn-back { background: #6c7086; color: #cdd6f4; }
        .btn-back:hover { background: #585b70; }
        .btn-mac { background: #a6e3a1; color: #11111b; }
        .btn-mac:hover { background: #94e2d5; }
        .file-list { list-style: none; padding: 0; }
        .file-list li { margin: 15px 0; padding: 15px; background: #45475a; border-radius: 6px; }
        input[type="text"], input[type="password"], input[type="datetime-local"] { padding: 10px; width: calc(100% - 22px); margin-bottom: 10px; border: 1px solid #585b70; border-radius: 4px; background: #1e1e2e; color: #cdd6f4; }
        pre { background: #11111b; color: #a6adc8; padding: 15px; border-radius: 5px; overflow-x: auto; max-height: 700px; border: 1px solid #585b70; }
        .nav-buttons { margin-bottom: 20px; border-bottom: 1px solid #585b70; padding-bottom: 15px; }
        .timestamp-form { display: flex; align-items: center; gap: 10px; margin-top: 15px; background: #313244; padding: 10px; border-radius: 6px; }
        .timestamp-form input { margin-bottom: 0; width: 250px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="nav-buttons">
            <a href="javascript:history.back()" class="btn btn-back">⬅ Back</a>
            <a href="javascript:history.forward()" class="btn btn-back">Front ➡</a>
            <a href="{{ url_for('index') }}" class="btn">🏠 Node List</a>
            {% if session.get('ssh_id') %}
                <a href="{{ url_for('dashboard') }}" class="btn">📁 Orchestrator Logs</a>
            {% endif %}
        </div>
        
        {% with messages = get_flashed_messages() %}
          {% if messages %}
            <script>
              {% for message in messages %}
                alert("{{ message | safe }}");
              {% endfor %}
            </script>
          {% endif %}
        {% endwith %}

        {% block content %}{% endblock %}
    </div>
</body>
</html>
"""

INDEX_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', """
    <h2>Available Tailscale Nodes</h2>
    <input type="text" id="searchInput" onkeyup="filterNodes()" placeholder="🔍 Search by name or IP address..." style="width: 100%; padding: 12px; margin-bottom: 20px; font-size: 16px; box-sizing: border-box;">

    <ul class="file-list" id="nodeList">
        {% for machine in machines %}
            <li class="node-item">
                <span class="node-text"><strong>{{ machine.hostname }}</strong> ({{ machine.ip }})</span>
                <form action="{{ url_for('login') }}" method="POST" style="margin-top: 10px;">
                    <input type="hidden" name="ip" value="{{ machine.ip }}">
                    <input type="text" name="username" placeholder="SSH Username" required>
                    <input type="password" name="password" placeholder="SSH Password" required>
                    <button type="submit">Connect to Node</button>
                </form>
            </li>
        {% else %}
            <li>No machines found. Ensure your API Key is set in your environment variables.</li>
        {% endfor %}
    </ul>

    <script>
    function filterNodes() {
        let input = document.getElementById('searchInput').value.toLowerCase();
        let nodes = document.getElementsByClassName('node-item');
        for (let i = 0; i < nodes.length; i++) {
            let nodeText = nodes[i].getElementsByClassName('node-text')[0].innerText.toLowerCase();
            if (nodeText.includes(input)) {
                nodes[i].style.display = "";
            } else {
                nodes[i].style.display = "none";
            }
        }
    }
    </script>
""")

DASHBOARD_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', """
    <h2>Orchestrator Logs Directory</h2>
    <p>Active Session: <strong>{{ target_ip }}</strong></p>
    
    <h3>Standard Logs</h3>
    <ul class="file-list">
        {% for log in logs %}
            <li style="display: inline-block; margin-right: 10px; margin-bottom: 10px;">
                <a href="{{ url_for('view_file', filename=log) }}" class="btn">{{ log }}</a>
            </li>
        {% endfor %}
    </ul>
    
    <h3>Gateway Logs (json_logs)</h3>
    <ul class="file-list">
        {% for file in gateway_files %}
            <li style="display: inline-block; margin-right: 10px; margin-bottom: 10px;">
                <a href="{{ url_for('view_gateway_file', filename=file) }}" class="btn btn-mac">📁 {{ file }}</a>
            </li>
        {% endfor %}
        {% if not gateway_files %}
            <li>No .log files found in json_logs directory.</li>
        {% endif %}
    </ul>
""")

GATEWAY_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', """
    <h2>Gateway Logs: {{ filename }}</h2>
    <p style="color: #a6adc8; margin-bottom: 20px;">/opt/go-ble-orchestrator/logs/json_logs/{{ filename }}</p>
    
    <div style="background: #45475a; padding: 20px; border-radius: 6px;">
        <form action="{{ url_for('view_json_timestamp', filename=filename) }}" method="GET" class="timestamp-form">
            <input type="datetime-local" step="1" name="timestamp" required title="Select Date and Time to search">
            <button type="submit" style="background: #f9e2af; color: #11111b;">Search Timestamp</button>
            <a href="{{ url_for('live_tail', filename='json_logs/' + filename) }}" class="btn btn-back">View Live File (tail -f)</a>
        </form>
    </div>
""")

VIEWER_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', """
    <h2>Viewing: {{ title }}</h2>
    <pre>{{ content }}</pre>
""")

LIVE_TAIL_TEMPLATE = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', """
    <h2>Live Tail: {{ title }} <span style="font-size: 14px; color: #a6e3a1;">(Streaming...)</span></h2>
    <pre id="logOutput" style="height: 600px; overflow-y: scroll;"></pre>
    
    <script>
        // Use Server-Sent Events to pipe the SSH tail -f output directly to the browser
        const evtSource = new EventSource("{{ url_for('stream_tail', filename=filename) }}");
        const logWindow = document.getElementById("logOutput");
        
        evtSource.onmessage = function(event) {
            logWindow.innerHTML += event.data + "\\n";
            logWindow.scrollTop = logWindow.scrollHeight; // Auto-scroll to bottom
        };
        
        evtSource.onerror = function() {
            logWindow.innerHTML += "\\n\\n[Connection Closed or Error. Please refresh to restart.]";
            evtSource.close();
        };
    </script>
""")

# --- HELPER FUNCTIONS ---

def get_tailscale_machines():
    if not TAILSCALE_API_KEY:
        print("ERROR: TAILSCALE_API_KEY environment variable is missing.")
        return []

    url = "https://api.tailscale.com/api/v2/tailnet/-/devices"
    headers = {
        "Authorization": f"Bearer {TAILSCALE_API_KEY}",
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status() 
        
        devices = response.json().get('devices', [])
        machines = []
        for dev in devices:
            if dev.get('addresses'):
                full_name = dev.get('name', '')
                if full_name and '.' in full_name:
                    display_name = full_name.split('.')[0]
                else:
                    display_name = dev.get('hostname', 'Unknown-Host')

                machines.append({
                    'hostname': display_name,
                    'ip': dev['addresses'][0]
                })
        return machines
    except Exception as e:
        print(f"Tailscale API Error: {e}")
        return []

def execute_ssh(command, auth_reason="Your SSH session was disconnected. Please re-enter your password."):
    session_id = session.get('ssh_id')
    if not session_id or session_id not in active_ssh_sessions:
        return None, f"AUTH_REQUIRED: {auth_reason}"
    
    client = active_ssh_sessions[session_id]
    try:
        stdin, stdout, stderr = client.exec_command(command)
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            return None, stderr.read().decode('utf-8')
        return stdout.read().decode('utf-8'), None
    except paramiko.ssh_exception.SSHException as e:
        active_ssh_sessions.pop(session_id, None) 
        session.pop('ssh_id', None)
        return None, f"AUTH_REQUIRED: {auth_reason} (Connection dropped)"

# --- ROUTES ---

@app.route('/')
def index():
    machines = get_tailscale_machines()
    return render_template_string(INDEX_TEMPLATE, machines=machines)

@app.route('/login', methods=['POST'])
def login():
    ip = request.form['ip']
    username = request.form['username']
    password = request.form['password']

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        client.connect(hostname=ip, username=username, password=password, timeout=10)
        session_id = str(uuid.uuid4())
        active_ssh_sessions[session_id] = client
        session['ssh_id'] = session_id
        session['target_ip'] = ip
        flash("Login successful! Welcome to the machine.")
        return redirect(url_for('dashboard'))
    except paramiko.AuthenticationException:
        flash("Login failed: Incorrect username or password.")
    except Exception as e:
        flash(f"Login failed: Could not reach machine. {str(e)}")
    
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'ssh_id' not in session:
        flash("Session required. Please select a machine and log in.")
        return redirect(url_for('index'))

    target_logs = ['app.log', 'stats_5s.log', 'sys-perf.log', 'mqtt-status.log']
    
    # Safely list ONLY files ending in .log inside the json_logs directory (No more duplicate paths)
    out, err = execute_ssh(f"ls -1 {LOG_DIR}/json_logs/*.log")
    if err:
        if "AUTH_REQUIRED" in err:
            flash(err.replace("AUTH_REQUIRED: ", ""))
            return redirect(url_for('index'))
        gateway_files = [] 
    else:
        # Extract just the file name (e.g., 04_E3_E5_DC_91_F2.log) from the full path
        gateway_files = [path.strip().split('/')[-1] for path in out.split('\n') if path.strip().endswith('.log')]

    return render_template_string(DASHBOARD_TEMPLATE, 
                                  target_ip=session.get('target_ip'), 
                                  logs=target_logs, 
                                  gateway_files=gateway_files)

@app.route('/view/<path:filename>')
def view_file(filename):
    out, err = execute_ssh(f"tail -f {LOG_DIR}/{filename}")
    if err:
        if "AUTH_REQUIRED" in err:
            flash(err.replace("AUTH_REQUIRED: ", ""))
            return redirect(url_for('index'))
        out = f"Error reading file: {err}"
    return render_template_string(VIEWER_TEMPLATE, title=filename, content=out)

@app.route('/gateway/<filename>')
def view_gateway_file(filename):
    return render_template_string(GATEWAY_TEMPLATE, filename=filename)

@app.route('/gateway/<filename>/search')
def view_json_timestamp(filename):
    timestamp_raw = request.args.get('timestamp')
    if not timestamp_raw:
        flash("Please select a date and time.")
        return redirect(url_for('view_gateway_file', filename=filename))

    # Convert the GUI datetime output (2026-04-02T10:45) to a standard grep format (2026-04-02 10:45)
    clean_timestamp = timestamp_raw.replace('T', ' ')
    safe_timestamp = clean_timestamp.replace("'", "'\\''")
    
    command = f"grep '{safe_timestamp}' {LOG_DIR}/json_logs/{filename}"
    out, err = execute_ssh(command, auth_reason="Connection lost while searching. Please log in again.")
    
    if err:
        if "AUTH_REQUIRED" in err:
            flash(err.replace("AUTH_REQUIRED: ", ""))
            return redirect(url_for('index'))
        flash(f"Search failed: {err}")
        return redirect(url_for('view_gateway_file', filename=filename))
    
    if not out:
        out = f"No log entries found for timestamp: {clean_timestamp}"

    return render_template_string(VIEWER_TEMPLATE, title=f"{filename} @ {clean_timestamp}", content=out)

@app.route('/live_tail/<path:filename>')
def live_tail(filename):
    """Renders the UI that will consume the streaming text."""
    if 'ssh_id' not in session:
        return redirect(url_for('index'))
    return render_template_string(LIVE_TAIL_TEMPLATE, title=filename, filename=filename)

@app.route('/stream/<path:filename>')
def stream_tail(filename):
    """A Server-Sent Events generator that pipes tail -f directly to the browser"""
    def generate():
        session_id = session.get('ssh_id')
        if not session_id or session_id not in active_ssh_sessions:
            yield "data: AUTH_REQUIRED - Session expired.\n\n"
            return
        
        client = active_ssh_sessions[session_id]
        
        # get_pty=True ensures the output is line-buffered over SSH
        stdin, stdout, stderr = client.exec_command(f"tail -n 50 -f {LOG_DIR}/{filename}", get_pty=True)
        
        try:
            for line in iter(stdout.readline, ""):
                # Format as a Server-Sent Event
                clean_line = line.replace('\n', '').replace('\r', '').replace('\\', '\\\\').replace('"', '\\"')
                yield f"data: {clean_line}\n\n"
        except Exception:
            pass
        finally:
            # Crucial: Closes the stream when you exit the webpage so `tail -f` doesn't run forever
            stdin.close()
            stdout.close()
            stderr.close()

    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    print("Starting Orchestrator UI on port 6900...")
    app.run(debug=True, host='0.0.0.0', port=6900)