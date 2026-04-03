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
import socket
import shlex
import threading
import time
import queue
from pathlib import Path
from flask import Flask, render_template_string, jsonify, request, session, redirect, url_for, flash, Response
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configuration - Load from .env file
TAILSCALE_API_KEY = os.getenv("Tailscale-tailnet-apikey") or os.getenv("TAILSCALE_API_KEY")
TAILSCALE_TENANT_NAME = os.getenv("Tailscale-tailnet-name") or os.getenv("TAILSCALE_TENANT_NAME")
LINUX_USER_PASS = os.getenv("linux_user_pass") or os.getenv("LINUX_USER_PASS", "mpr")

LOG_DIR = "/opt/go-ble-orchestrator/logs"
ANSIBLE_DIR = Path(__file__).parent.parent  # Points to /ansible directory
PLAYBOOKS_DIR = ANSIBLE_DIR / "playbooks"
INVENTORY_FILE = ANSIBLE_DIR / "inventory" / "production.yml"

# In-memory storage for active SSH sessions
active_ssh_sessions = {}

# Background monitoring - cached machine list
cached_machines = []
cached_machines_lock = threading.Lock()
last_update_time = None
update_interval = 30  # Update every 30 seconds
monitoring_active = False

# ============================================================================
# TAILSCALE INTEGRATION
# ============================================================================

def get_tailscale_machines_api():
    """Get machines from Tailscale API + local client for real-time status"""
    api_key = TAILSCALE_API_KEY
    
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
# BACKGROUND MONITORING - Auto-detect new machines and status changes
# ============================================================================

def background_monitor_machines():
    """Background worker thread that continuously monitors Tailscale tailnet for changes"""
    global cached_machines, last_update_time, monitoring_active
    
    print("[Monitor] Starting background machine monitoring thread...")
    monitoring_active = True
    
    while monitoring_active:
        try:
            machines = get_tailscale_machines_api()
            
            with cached_machines_lock:
                cached_machines = machines
                last_update_time = time.time()
                online_count = sum(1 for m in machines if m['online'])
                total_count = len(machines)
            
            print(f"[Monitor] Updated at {time.strftime('%H:%M:%S')} - {online_count}/{total_count} machines online")
            
        except Exception as e:
            print(f"[Monitor] Error during update: {e}")
        
        # Wait before next update
        time.sleep(update_interval)

def start_background_monitor():
    """Start the background monitoring thread (daemon mode)"""
    global monitoring_active
    
    if not monitoring_active:
        monitor_thread = threading.Thread(target=background_monitor_machines, daemon=True)
        monitor_thread.start()
        print("[Monitor] Background monitoring thread started")

def stop_background_monitor():
    """Stop the background monitoring thread"""
    global monitoring_active
    monitoring_active = False
    print("[Monitor] Background monitoring thread stopped")

# ============================================================================
# SSH EXECUTION HELPERS
# ============================================================================

def execute_ssh(command, timeout=30):
    """Execute command over active SSH session with timeout"""
    session_id = session.get('ssh_id')
    if not session_id or session_id not in active_ssh_sessions:
        return None, "Session expired. Please reconnect."
    
    client = active_ssh_sessions[session_id]
    try:
        stdin, stdout, stderr = client.exec_command(command)
        # Set timeout on the channel to prevent hanging on large files
        stdout.channel.settimeout(timeout)
        
        try:
            exit_status = stdout.channel.recv_exit_status()
        except socket.timeout:
            return None, f"Command timed out after {timeout}s"
        
        if exit_status != 0:
            err = stderr.read().decode('utf-8', errors='ignore')
            out = stdout.read().decode('utf-8', errors='ignore')
            return out or None, err
        
        # Read with size limit to prevent massive memory bloat on huge files
        out = stdout.read(16*1024*1024).decode('utf-8', errors='ignore')  # 16MB limit
        return out, None
    except socket.timeout:
        return None, "SSH command timed out"
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
# JSON LOG HELPERS - Time conversion and searching
# ============================================================================

from datetime import datetime
import time as time_module

def parse_datetime_string(dt_str):
    """Parse dd/mm/yyyy hh:mm:ss to epoch seconds"""
    try:
        dt = datetime.strptime(dt_str.strip(), "%d/%m/%Y %H:%M:%S")
        epoch_seconds = int(dt.timestamp())
        return epoch_seconds
    except Exception as e:
        raise ValueError(f"Invalid datetime format: {dt_str}. Expected: dd/mm/yyyy hh:mm:ss. Error: {e}")

def search_json_logs_by_timestamp(client, log_dir, log_file, start_epoch, end_epoch):
    """
    Search JSON log file for entries with timestamp1 within range
    Returns matching lines as list
    """
    try:
        # Use grep + awk to search timestamp1 in JSON files
        # grep - find lines with timestamp1
        # awk - parse and filter by epoch range
        command = f"""
        grep -h 'timestamp1' {log_dir}/{log_file} 2>/dev/null | awk -F'timestamp1":' '{{
            split($2, a, ",");
            ts = a[1];
            gsub(/[^0-9]/, "", ts);
            if (ts >= {start_epoch} && ts <= {end_epoch}) {{
                print $0
            }}
        }}' | head -1000
        """
        
        stdin, stdout, stderr = client.exec_command(command)
        exit_code = stdout.channel.recv_exit_status()
        output = stdout.read().decode('utf-8').strip()
        
        if exit_code != 0:
            error = stderr.read().decode('utf-8').strip()
            return [], error
        
        lines = [line for line in output.split('\n') if line.strip()]
        return lines, None
        
    except Exception as e:
        return [], str(e)

def list_json_logs(client):
    """Get list of json_logs from both /opt/go-ble-orchestrator/logs and /opt/go-ble-orchestrator/"""
    json_logs = {'logs': [], 'root': []}
    
    try:
        # Check /opt/go-ble-orchestrator/logs/json_logs
        cmd1 = 'ls -1 /opt/go-ble-orchestrator/logs/json_logs 2>/dev/null'
        stdin, stdout, stderr = client.exec_command(cmd1)
        stdout.channel.recv_exit_status()
        logs_dir_files = stdout.read().decode('utf-8').strip().split('\n')
        json_logs['logs'] = [f for f in logs_dir_files if f.strip() and f.endswith('.log')]
    except:
        pass
    
    try:
        # Check /opt/go-ble-orchestrator/json_logs (in case running older version)
        cmd2 = 'ls -1 /opt/go-ble-orchestrator/json_logs 2>/dev/null'
        stdin, stdout, stderr = client.exec_command(cmd2)
        stdout.channel.recv_exit_status()
        root_dir_files = stdout.read().decode('utf-8').strip().split('\n')
        json_logs['root'] = [f for f in root_dir_files if f.strip() and f.endswith('.log')]
    except:
        pass
    
    return json_logs

# ============================================================================
# BUFFERED LIVE TAIL STREAMING - 3-second chunks with threading
# ============================================================================

class BufferedTailStreamer:
    """
    Efficiently streams tail -f output in 3-second chunks
    Uses threading to pre-fetch next chunk while streaming current chunk
    Prevents memory bloat and frontend lag
    """
    
    def __init__(self, client, log_dir, filename, chunk_size=3):
        self.client = client
        self.log_path = f"{log_dir}/{filename}"
        self.chunk_size = chunk_size  # seconds
        self.data_queue = queue.Queue(maxsize=2)  # Buffer 2 chunks max
        self.stop_event = threading.Event()
        self.reader_thread = None
        self.chunk_count = 0
    
    def _read_tail_chunk(self):
        """Read last 100 lines from log file (runs in background thread)"""
        try:
            # Use tail -f with timeout protection
            stdin, stdout, stderr = self.client.exec_command(
                f'tail -n 100 {self.log_path}',
                timeout=5
            )
            exit_code = stdout.channel.recv_exit_status()
            
            if exit_code != 0:
                error = stderr.read().decode('utf-8', errors='ignore').strip()
                return {'error': error, 'lines': [], 'chunk': self.chunk_count}
            
            output = stdout.read().decode('utf-8', errors='ignore').strip()
            lines = [l for l in output.split('\n') if l.strip()]
            
            self.chunk_count += 1
            return {
                'lines': lines,
                'count': len(lines),
                'chunk': self.chunk_count,
                'timestamp': time.time()
            }
        
        except Exception as e:
            return {'error': str(e), 'lines': [], 'chunk': self.chunk_count}
    
    def start_streaming(self):
        """Start background reader thread"""
        if self.reader_thread is not None:
            return
        
        self.stop_event.clear()
        self.reader_thread = threading.Thread(target=self._stream_worker, daemon=True)
        self.reader_thread.start()
    
    def _stream_worker(self):
        """Background worker that continuously reads 100-line chunks at 3-second intervals"""
        while not self.stop_event.is_set():
            try:
                chunk_data = self._read_tail_chunk()
                
                # Put chunk in queue (blocks if queue full, giving time to consume)
                try:
                    self.data_queue.put(chunk_data, timeout=self.chunk_size)
                except queue.Full:
                    # Queue full = frontend can't keep up; drop oldest
                    try:
                        self.data_queue.get_nowait()
                    except queue.Empty:
                        pass
                    self.data_queue.put(chunk_data, timeout=0.1)
                
                # Wait 3 seconds before next chunk (allows memory deallocation)
                time.sleep(self.chunk_size)
            
            except Exception as e:
                print(f"[StreamWorker] Error: {e}")
                time.sleep(self.chunk_size)
    
    def stream_chunks(self, timeout_seconds=3600):
        """
        Generator that yields chunks from queue
        Called by Flask to stream data to frontend
        """
        start_time = time.time()
        self.start_streaming()
        
        try:
            while True:
                # Timeout if client disconnects
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    yield json.dumps({'status': 'timeout'}) + '\n'
                    break
                
                try:
                    # Get next buffered chunk (with timeout to allow stop checks)
                    chunk = self.data_queue.get(timeout=4)
                    
                    if chunk:
                        yield json.dumps(chunk) + '\n'
                        # Flush to client immediately
                        
                except queue.Empty:
                    # No new data yet; send heartbeat to keep connection alive
                    yield json.dumps({'status': 'waiting'}) + '\n'
        
        except GeneratorExit:
            self.stop()
        finally:
            self.stop()
    
    def stop(self):
        """Stop the background reader thread"""
        self.stop_event.set()
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=2)

# Track active streamers per session
active_streamers = {}

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
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; transition: all 0.3s ease-out; }
        
        body {
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
            color: #e2e8f0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }
        
        @keyframes float { 0%, 100% { transform: translateY(0px); } 50% { transform: translateY(-8px); } }
        @keyframes pulse-glow { 0%, 100% { box-shadow: 0 0 10px rgba(34, 211, 238, 0.5); } 50% { box-shadow: 0 0 20px rgba(34, 211, 238, 0.8); } }
        @keyframes pulse-error { 0%, 100% { box-shadow: 0 0 10px rgba(239, 68, 68, 0.5); } 50% { box-shadow: 0 0 20px rgba(239, 68, 68, 0.8); } }
        @keyframes slide-in-top { from { opacity: 0; transform: translateY(-30px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes bounce-in { 0% { opacity: 0; transform: scale(0.8); } 100% { opacity: 1; transform: scale(1); } }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        
        .animate-float { animation: float 3s ease-in-out infinite; }
        .animate-pulse-glow { animation: pulse-glow 2s ease-in-out infinite; }
        .animate-pulse-error { animation: pulse-error 1.5s ease-in-out infinite; }
        .animate-slide-in-top { animation: slide-in-top 0.6s cubic-bezier(0.34, 1.56, 0.64, 1); }
        .animate-bounce-in { animation: bounce-in 0.5s cubic-bezier(0.34, 1.56, 0.64, 1); }
        .animate-fade-in { animation: fadeIn 0.6s ease-out; }
        
        .nav-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding: 16px 20px; background: linear-gradient(135deg, rgba(34, 211, 238, 0.08) 0%, rgba(59, 130, 246, 0.04) 100%); border: 1px solid rgba(34, 211, 238, 0.2); border-radius: 12px; animation: slide-in-top 0.5s; }
        .nav-bar h1 { font-size: 20px; font-weight: bold; color: #22d3ee; margin: 0; }
        .nav-links { display: flex; gap: 12px; flex-wrap: wrap; }
        .nav-btn { padding: 10px 16px; background: rgba(30, 41, 59, 0.7); border: 1px solid rgba(226, 232, 240, 0.15); color: #e2e8f0; border-radius: 8px; cursor: pointer; text-decoration: none; font-size: 12px; font-weight: 600; }
        .nav-btn:hover { border-color: rgba(34, 211, 238, 0.5); color: #22d3ee; box-shadow: 0 8px 16px rgba(34, 211, 238, 0.15); transform: translateY(-2px); }
        
        .header { display: flex; justify-content: space--between; align-items: center; margin-bottom: 30px; padding: 25px; background: linear-gradient(135deg, rgba(34, 211, 238, 0.1) 0%, rgba(59, 130, 246, 0.05) 100%); border: 1px solid rgba(34, 211, 238, 0.2); border-radius: 14px; animation: slide-in-top; }
        .header h2 { font-size: 28px; font-weight: bold; color: #22d3ee; margin: 0; }
        .header-stats { display: flex; gap: 20px; flex-wrap: wrap; }
        .stat { display: flex; flex-direction: column; align-items: center; padding: 15px 20px; background: rgba(30, 41, 59, 0.6); border-radius: 10px; border: 1px solid rgba(226, 232, 240, 0.1); }
        .stat:hover { background: rgba(30, 41, 59, 0.8); border-color: rgba(34, 211, 238, 0.3); box-shadow: 0 10px 20px rgba(34, 211, 238, 0.1); }
        .stat-value { font-size: 32px; font-weight: 700; color: #22d3ee; }
        .stat-label { font-size: 11px; color: #94a3b8; margin-top: 8px; text-transform: uppercase; letter-spacing: 0.05em; }
        
        .controls { display: flex; gap: 12px; margin-bottom: 24px; flex-wrap: wrap; animation: fadeIn 0.6s; }
        .search-box { flex: 1; min-width: 200px; padding: 12px 16px; background: rgba(30, 41, 59, 0.7); border: 1px solid rgba(226, 232, 240, 0.15); border-radius: 8px; color: #e2e8f0; font-size: 14px; }
        .search-box:focus { outline: none; border-color: rgba(34, 211, 238, 0.6); box-shadow: 0 0 12px rgba(34, 211, 238, 0.2); }
        .filter-btn { padding: 10px 16px; background: rgba(30, 41, 59, 0.6); border: 1px solid rgba(226, 232, 240, 0.15); color: #cbd5e1; border-radius: 8px; cursor: pointer; font-size: 12px; font-weight: 600; }
        .filter-btn:hover { border-color: rgba(34, 211, 238, 0.4); color: #22d3ee; }
        .filter-btn.active { background: rgba(34, 211, 238, 0.8); color: #001217; border-color: rgba(34, 211, 238, 0.8); box-shadow: 0 10px 20px rgba(34, 211, 238, 0.2); font-weight: 700; }
        
        .machines-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; margin-bottom: 30px; }
        .machine-card { background: linear-gradient(135deg, rgba(15, 23, 42, 0.9) 0%, rgba(30, 41, 59, 0.5) 100%); border: 1px solid rgba(226, 232, 240, 0.1); border-radius: 12px; padding: 20px; animation: fadeIn 0.5s; cursor: pointer; }
        .machine-card:hover { transform: translateY(-6px) scale(1.02); border-color: rgba(34, 211, 238, 0.6); box-shadow: 0 20px 40px rgba(34, 211, 238, 0.15); background: linear-gradient(135deg, rgba(15, 23, 42, 1) 0%, rgba(30, 41, 59, 0.8) 100%); }
        .machine-card.online { border-color: rgba(16, 185, 129, 0.3); background: linear-gradient(135deg, rgba(15, 23, 42, 0.9) 0%, rgba(5, 80, 60, 0.2) 100%); }
        .machine-card.offline { border-color: rgba(239, 68, 68, 0.3); background: linear-gradient(135deg, rgba(15, 23, 42, 0.9) 0%, rgba(80, 5, 5, 0.2) 100%); }
        
        .machine-status { display: inline-flex; align-items: center; gap: 8px; margin-bottom: 12px; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }
        .machine-status.status-online { color: #10b981; }
        .machine-status.status-online .status-indicator { background: #10b981; box-shadow: 0 0 6px rgba(16, 185, 129, 0.8); animation: pulse-glow 2s; }
        .machine-status.status-offline { color: #ef4444; animation: pulse-error 1.5s; }
        .status-indicator { width: 8px; height: 8px; border-radius: 50%; animation: float 3s; }
        
        .machine-hostname { font-size: 18px; font-weight: 700; color: #e2e8f0; margin-bottom: 12px; }
        .machine-card:hover .machine-hostname { color: #22d3ee; }
        .machine-details { padding: 12px 0; border-top: 1px solid rgba(226, 232, 240, 0.1); border-bottom: 1px solid rgba(226, 232, 240, 0.1); margin-bottom: 12px; }
        .detail-row { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 8px; }
        .detail-label { color: #94a3b8; }
        .detail-value { color: #22d3ee; font-family: 'Monaco', 'Courier New', monospace; font-weight: 600; }
        
        .machine-actions { display: flex; gap: 8px; margin-top: 12px; }
        .action-btn { flex: 1; padding: 10px 12px; background: rgba(34, 211, 238, 0.15); border: 1px solid rgba(34, 211, 238, 0.5); color: #22d3ee; border-radius: 8px; cursor: pointer; font-size: 12px; font-weight: 700; text-decoration: none; text-align: center; text-transform: uppercase; letter-spacing: 0.05em; }
        .action-btn:hover { background: rgba(34, 211, 238, 0.3); border-color: rgba(34, 211, 238, 0.8); box-shadow: 0 10px 20px rgba(34, 211, 238, 0.2); transform: translateY(-2px) scale(1.05); }
        .action-btn:active { transform: translateY(0) scale(0.98); }
        
        .log-container { background: linear-gradient(135deg, rgba(15, 23, 42, 0.8) 0%, rgba(30, 41, 59, 0.5) 100%); border: 1px solid rgba(226, 232, 240, 0.1); border-radius: 14px; padding: 25px; margin-bottom: 24px; animation: fadeIn 0.6s; }
        .log-container h3 { margin: 0 0 16px 0; font-size: 18px; font-weight: 700; color: #22d3ee; text-transform: uppercase; letter-spacing: 0.05em; }
        .log-list { list-style: none; display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }
        .log-item { padding: 14px; background: rgba(34, 211, 238, 0.1); border: 1px solid rgba(34, 211, 238, 0.4); border-radius: 8px; color: #22d3ee; font-weight: 700; text-align: center; text-decoration: none; cursor: pointer; font-size: 12px; display: block; }
        .log-item:hover { background: rgba(34, 211, 238, 0.2); border-color: rgba(34, 211, 238, 0.8); box-shadow: 0 10px 20px rgba(34, 211, 238, 0.15); transform: translateY(-3px); }
        
        pre { background: #0f172a; color: #cbd5e1; padding: 16px; border-radius: 8px; border: 1px solid rgba(226, 232, 240, 0.1); overflow-x: auto; overflow-y: auto; max-height: 500px; margin-bottom: 16px; font-family: 'Monaco', 'Courier New', monospace; font-size: 13px; line-height: 1.6; white-space: pre-wrap; word-break: break-all; }
        
        #loginModal, #messageModal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0, 0, 0, 0.7); z-index: 1000; align-items: center; justify-content: center; backdrop-filter: blur(4px); }
        #loginModal:target, #loginModal.show, #messageModal:target, #messageModal.show { display: flex; animation: bounce-in 0.5s; }
        #loginModal > div, #messageModal > div { background: linear-gradient(135deg, rgba(15, 23, 42, 0.95) 0%, rgba(30, 41, 59, 0.8) 100%); border: 2px solid rgba(34, 211, 238, 0.5); border-radius: 14px; padding: 32px; max-width: 400px; width: 90%; box-shadow: 0 20px 60px rgba(34, 211, 238, 0.2); }
        #loginModal h3, #messageModal h3 { margin: 0 0 24px 0; font-size: 20px; font-weight: 700; color: #22d3ee; }
        #messageIcon { font-size: 48px; margin-bottom: 16px; }
        
        .alert { padding: 16px; margin-bottom: 20px; border-radius: 8px; border: 1px solid; animation: bounce-in 0.5s; }
        .alert-success { background: rgba(16, 185, 129, 0.1); border-color: rgba(16, 185, 129, 0.5); color: #10b981; }
        
        input[type="text"], input[type="password"], input[type="datetime-local"], select, textarea { width: 100%; padding: 12px; margin-top: 6px; background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(226, 232, 240, 0.15); color: #e2e8f0; border-radius: 8px; font-size: 14px; color-scheme: dark; }
        input:focus, select:focus, textarea:focus { outline: none; border-color: rgba(34, 211, 238, 0.6); box-shadow: 0 0 16px rgba(34, 211, 238, 0.2); background: rgba(15, 23, 42, 0.9); }
        label { display: block; font-size: 12px; color: #94a3b8; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }
        
        .back-link { display: inline-block; margin-bottom: 20px; margin-right: 10px; padding: 10px 16px; background: rgba(30, 41, 59, 0.6); border: 1px solid rgba(226, 232, 240, 0.15); color: #cbd5e1; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 12px; }
        .back-link:hover { border-color: rgba(34, 211, 238, 0.5); color: #22d3ee; box-shadow: 0 8px 16px rgba(34, 211, 238, 0.15); transform: translateY(-2px); }
        
        .container { max-width: 1400px; margin: 0 auto; padding: 1.5rem; }
    </style>
</head>
<body class="bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 text-gray-100 min-h-screen">
    <div class="container mx-auto max-w-7xl px-4 py-6">
        {% if session.get('target_ip') %}
        <div class="flex justify-between items-center mb-6 p-5 bg-cyan-500/10 border border-slate-700 rounded-xl animate-slide-in-top hover:border-cyan-400/50">
            <h1 class="text-2xl font-bold text-cyan-400">🌐 Orchestrator Manager</h1>
            <div class="flex gap-3 flex-wrap">
                <a href="{{ url_for('machines') }}" class="px-3 py-2 bg-slate-800 border border-slate-600 rounded-lg text-gray-100 text-sm font-medium hover:border-cyan-400 hover:text-cyan-400 hover:shadow-lg hover:shadow-cyan-500/20">🏠 Machines</a>
                <a href="{{ url_for('dashboard') }}" class="px-3 py-2 bg-slate-800 border border-slate-600 rounded-lg text-gray-100 text-sm font-medium hover:border-cyan-400 hover:text-cyan-400 hover:shadow-lg hover:shadow-cyan-500/20">📁 Logs</a>
                <span class="px-3 py-2 bg-slate-800 border border-slate-600 rounded-lg text-gray-100 text-sm font-medium">📍 {{ session.get('target_ip') }}</span>
                <a href="{{ url_for('logout') }}" class="px-3 py-2 bg-slate-800 border border-red-600/50 rounded-lg text-red-400 text-sm font-medium hover:border-red-400 hover:bg-red-500/10 hover:shadow-lg hover:shadow-red-500/20">🚪 Logout</a>
            </div>
        </div>
        {% endif %}
        
        {% with messages = get_flashed_messages() %}
            {% if messages %}
                {% for message in messages %}
                    <div class="mb-5 p-4 bg-emerald-500/10 border border-emerald-500 text-emerald-400 rounded-lg animate-fade-in-scale">✓ {{ message }}</div>
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
                <input type="text" id="modalUsername" placeholder="ubuntu" value="{{ default_username }}" style="width: 100%; padding: 10px; background: var(--color-bg-dark); border: 1px solid var(--color-border); color: var(--color-text); border-radius: 6px; margin-top: 5px;">
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
    
    // ========= AUTO-REFRESH MONITORING =========
    let lastUpdateTime = 0;
    const REFRESH_INTERVAL = 5000; // Poll every 5 seconds
    
    async function refreshMachinesList() {
        try {
            const response = await fetch('/api/machines');
            const data = await response.json();
            
            if (!data.success) return;
            
            // Check if data is newer than what we're displaying
            if (data.timestamp <= lastUpdateTime) return;
            lastUpdateTime = data.timestamp;
            
            const machines = data.machines;
            const container = document.querySelector('.machines-grid');
            
            // Update stats in header (never triggers reflow)
            const statElements = document.querySelectorAll('.stat-value');
            if (statElements.length >= 3) {
                statElements[0].textContent = data.total;
                statElements[1].textContent = data.online;
                statElements[2].textContent = data.offline;
            }
            
            // Update machine cards IN-PLACE (no tile shifting)
            const existingCards = new Map();
            document.querySelectorAll('.machine-card').forEach(card => {
                const ipElement = card.querySelector('.machine-details .detail-value');
                if (ipElement) {
                    existingCards.set(ipElement.textContent.trim(), card);
                }
            });
            
            const machineIps = new Set();
            
            machines.forEach(machine => {
                machineIps.add(machine.ip);
                const machineClass = machine.online ? 'online' : 'offline';
                const statusText = machine.online ? 'Online' : 'Offline';
                const statusClass = machine.online ? 'status-online' : 'status-offline';
                
                const existingCard = existingCards.get(machine.ip);
                
                if (existingCard) {
                    // Update existing card in-place
                    existingCard.className = `machine-card ${machineClass}`;
                    
                    const statusDiv = existingCard.querySelector('.machine-status');
                    if (statusDiv) {
                        statusDiv.className = `machine-status ${statusClass}`;
                        statusDiv.innerHTML = `<span class="status-indicator"></span>${statusText}`;
                    }
                    
                    const hostnameDiv = existingCard.querySelector('.machine-hostname');
                    if (hostnameDiv) {
                        hostnameDiv.textContent = machine.hostname;
                    }
                    
                    const osValue = existingCard.querySelector('.machine-details .detail-row:last-child .detail-value');
                    if (osValue) {
                        osValue.textContent = machine.os;
                    }
                } else {
                    // Add new machine card
                    const newCard = document.createElement('div');
                    newCard.className = `machine-card ${machineClass}`;
                    newCard.innerHTML = `
                        <div class="machine-status ${statusClass}">
                            <span class="status-indicator"></span>
                            ${statusText}
                        </div>
                        <div class="machine-hostname">${machine.hostname}</div>
                        <div class="machine-details">
                            <div class="detail-row">
                                <span class="detail-label">IP:</span>
                                <span class="detail-value">${machine.ip}</span>
                            </div>
                            <div class="detail-row">
                                <span class="detail-label">OS:</span>
                                <span class="detail-value">${machine.os}</span>
                            </div>
                        </div>
                        <div class="machine-actions">
                            <button onclick="openLoginModal('${machine.ip}', '${machine.hostname}')" class="action-btn">🔐 Login</button>
                        </div>
                    `;
                    container.appendChild(newCard);
                }
            });
            
            // Remove cards for machines no longer in the list
            existingCards.forEach((card, ip) => {
                if (!machineIps.has(ip)) {
                    card.remove();
                }
            });
            
        } catch (error) {
            console.error('Error refreshing machines:', error);
        }
    }
    
    // Start auto-refresh polling
    console.log('[Monitor] Starting auto-refresh polling (5 second interval)');
    setInterval(refreshMachinesList, REFRESH_INTERVAL);
    
    // Initial refresh on page load
    refreshMachinesList();
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

<!-- JSON / Gateway Logs - Real-time Browser & Time-based Search -->
<div class="log-container">
    <h3>📊 JSON Log Browser - Real-time & Time-based Search</h3>
    <p style="color: var(--color-text-muted); font-size: 12px; margin-bottom: 15px;">Browse json_logs from /opt/go-ble-orchestrator/logs/json_logs or /opt/go-ble-orchestrator/json_logs (for older versions)</p>
    
    <!-- Log Directory Selection & File List -->
    <div style="background: rgba(0, 215, 255, 0.05); padding: 15px; border-radius: 8px; border: 1px solid var(--color-border); margin-bottom: 15px;">
        <div style="display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap;">
            <button onclick="loadJsonLogsList()" class="action-btn" style="padding: 10px 20px; min-width: 180px;">📂 Load Available Logs</button>
            <button onclick="toggleJsonRealtimeRefresh()" id="realtimeToggleBtn" class="action-btn" style="padding: 10px 20px; min-width: 180px; border-color: #6b7280; color: #cbd5e1;">⏸️ Start Real-time (3s)</button>
        </div>
        
        <div id="jsonLogsLoadingMsg" style="display: none; text-align: center; padding: 15px; color: var(--color-text-muted);">
            <div style="font-size: 16px; margin-bottom: 8px;">⏳</div>
            <div>Loading logs from directories...</div>
        </div>
        
        <div id="jsonLogsContainer" style="display: none;">
            <div style="margin-bottom: 12px;">
                <h4 style="color: var(--color-primary); margin-bottom: 8px;">📁 /opt/go-ble-orchestrator/logs/json_logs</h4>
                <div id="logsDir" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; padding: 10px 0;"></div>
            </div>
            <div>
                <h4 style="color: var(--color-primary); margin-bottom: 8px;">📁 /opt/go-ble-orchestrator/json_logs (legacy)</h4>
                <div id="rootDir" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; padding: 10px 0;"></div>
            </div>
        </div>
    </div>
    
    <!-- Real-time Log Display -->
    <div id="realtimeContainer" style="display: none; background: rgba(0, 215, 255, 0.05); padding: 15px; border-radius: 8px; border: 1px solid var(--color-border); margin-bottom: 15px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
            <h4 style="color: var(--color-primary);">🔴 Real-time: <span id="realtimeFileName" style="font-family: monospace; font-size: 12px;"></span></h4>
            <div style="display: flex; gap: 8px;">
                <span id="realtimeIndicator" style="width: 10px; height: 10px; background: #ef4444; border-radius: 50%; display: inline-block;"></span>
                <span id="realtimeStatus" style="font-size: 12px; color: var(--color-text-muted);">Stopped</span>
            </div>
        </div>
        <pre id="realtimeLog" style="height: 400px; overflow-y: auto; font-size: 12px;">Waiting to start real-time streaming...</pre>
    </div>
    
    <!-- Time-based Search -->
    <div style="background: rgba(0, 215, 255, 0.05); padding: 15px; border-radius: 8px; border: 1px solid var(--color-border); margin-bottom: 15px;">
        <h4 style="color: var(--color-primary); margin-bottom: 15px;">🕐 Time-based Log Search</h4>
        <p style="color: var(--color-text-muted); font-size: 12px; margin-bottom: 12px;">Format: dd/mm/yyyy hh:mm:ss - Searches for timestamps in JSON "timestamp1" field</p>
        
        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 15px;">
            <div>
                <label style="color: var(--color-text-muted); font-size: 12px; display: block; margin-bottom: 6px;">📁 Select Log File</label>
                <select id="jsonFileSelect" style="width: 100%; padding: 10px; background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(226, 232, 240, 0.15); color: #e2e8f0; border-radius: 8px; font-size: 13px;">
                    <option value="">-- Choose a log file --</option>
                </select>
            </div>
            <div>
                <label style="color: var(--color-text-muted); font-size: 12px; display: block; margin-bottom: 6px;">📅 From (dd/mm/yyyy hh:mm:ss)</label>
                <input type="text" id="fromDateTime" placeholder="01/04/2025 10:30:00" style="width: 100%; padding: 10px; background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(226, 232, 240, 0.15); color: #e2e8f0; border-radius: 8px; font-size: 13px;">
            </div>
            <div>
                <label style="color: var(--color-text-muted); font-size: 12px; display: block; margin-bottom: 6px;">📅 To (dd/mm/yyyy hh:mm:ss)</label>
                <input type="text" id="toDateTime" placeholder="01/04/2025 11:30:00" style="width: 100%; padding: 10px; background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(226, 232, 240, 0.15); color: #e2e8f0; border-radius: 8px; font-size: 13px;">
            </div>
        </div>
        
        <div id="epochPreviewJson" style="font-size: 11px; color: var(--color-text-muted); margin-bottom: 12px; font-family: monospace; min-height: 18px;"></div>
        
        <div style="display: flex; gap: 10px; flex-wrap: wrap;">
            <button onclick="searchJsonLogsByTime()" class="action-btn" style="padding: 10px 24px; min-width: 140px;">🔍 Search Logs</button>
            <button onclick="setLastNJsonMinutes(15)" class="action-btn" style="padding: 10px 16px; min-width: 100px;">Last 15 min</button>
            <button onclick="setLastNJsonMinutes(60)" class="action-btn" style="padding: 10px 16px; min-width: 100px;">Last 1 hour</button>
            <button onclick="setLastNJsonMinutes(360)" class="action-btn" style="padding: 10px 16px; min-width: 100px;">Last 6 hours</button>
        </div>
    </div>
    
    <!-- Search Results -->
    <div id="jsonSearchResults" style="display: none; background: rgba(0, 215, 255, 0.05); padding: 15px; border-radius: 8px; border: 1px solid var(--color-border);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
            <h4 style="color: var(--color-primary);">📋 Search Results <span id="jsonResultCount" style="font-size: 12px; color: var(--color-text-muted);"></span></h4>
            <label style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--color-text-muted); cursor: pointer;">
                <input type="checkbox" id="prettyJsonFormat" onchange="renderJsonResults()"> Pretty-print JSON
            </label>
        </div>
        <pre id="jsonResultsLog" style="height: 500px; overflow-y: auto;"></pre>
    </div>
    
    <div id="jsonSearchLoading" style="display: none; text-align: center; padding: 30px; color: var(--color-text-muted);">
        <div style="font-size: 32px; margin-bottom: 10px;">⏳</div>
        <div>Searching logs...</div>
    </div>
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
    
    // ========= JSON LOG BROWSER =========
    let jsonLogsData = { logs_dir: [], root_dir: [] };
    let realtimeIntervalId = null;
    let currentRealtimeFile = null;
    let currentRealtimeLocation = null;
    let jsonRawLines = [];
    
    // Update epoch preview when times change
    document.getElementById('fromDateTime').addEventListener('change', updateJsonEpochPreview);
    document.getElementById('toDateTime').addEventListener('change', updateJsonEpochPreview);
    
    function escapeHtml(text) {
        return String(text).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
    }
    
    function updateJsonEpochPreview() {
        const from = document.getElementById('fromDateTime').value;
        const to = document.getElementById('toDateTime').value;
        const preview = document.getElementById('epochPreviewJson');
        if (from && to) {
            const fromEpoch = dateStringToEpoch(from);
            const toEpoch = dateStringToEpoch(to);
            if (fromEpoch && toEpoch) {
                preview.textContent = `Epoch range: ${fromEpoch} → ${toEpoch} (seconds)`;
            }
        } else {
            preview.textContent = '';
        }
    }
    
    function dateStringToEpoch(dateStr) {
        // Parse: dd/mm/yyyy hh:mm:ss → epoch seconds
        const match = dateStr.match(/^(\\d{2})\\/(\\d{2})\\/(\\d{4})\\s+(\\d{2}):(\\d{2}):(\\d{2})$/);
        if (!match) return null;
        
        const [, day, month, year, hours, minutes, seconds] = match;
        const date = new Date(year, month - 1, day, hours, minutes, seconds, 0);
        return Math.floor(date.getTime() / 1000); // Convert to seconds
    }
    
    function setLastNJsonMinutes(minutes) {
        const now = new Date();
        const past = new Date(now.getTime() - minutes * 60 * 1000);
        
        document.getElementById('fromDateTime').value = formatDateForInput(past);
        document.getElementById('toDateTime').value = formatDateForInput(now);
        updateJsonEpochPreview();
    }
    
    function formatDateForInput(date) {
        const day = String(date.getDate()).padStart(2, '0');
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const year = date.getFullYear();
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        const seconds = String(date.getSeconds()).padStart(2, '0');
        return `${day}/${month}/${year} ${hours}:${minutes}:${seconds}`;
    }
    
    async function loadJsonLogsList() {
        document.getElementById('jsonLogsLoadingMsg').style.display = 'block';
        document.getElementById('jsonLogsContainer').style.display = 'none';
        
        try {
            const res = await fetch('/api/json-logs/list');
            const data = await res.json();
            
            if (!data.success) {
                alert('Error loading logs: ' + (data.error || 'Unknown error'));
                document.getElementById('jsonLogsLoadingMsg').style.display = 'none';
                return;
            }
            
            jsonLogsData = data.logs;
            
            // Populate logs directory
            const logsDirDiv = document.getElementById('logsDir');
            logsDirDiv.innerHTML = '';
            if (jsonLogsData.logs_dir.length > 0) {
                jsonLogsData.logs_dir.forEach(file => {
                    const btn = document.createElement('button');
                    btn.className = 'action-btn';
                    btn.style.padding = '8px 12px';
                    btn.textContent = file;
                    btn.onclick = () => startRealtimeStream('logs', file);
                    logsDirDiv.appendChild(btn);
                    
                    // Also add to search select
                    const option = document.createElement('option');
                    option.value = JSON.stringify({location: 'logs', file: file});
                    option.textContent = `${file} (from logs/json_logs)`;
                    document.getElementById('jsonFileSelect').appendChild(option);
                });
            } else {
                logsDirDiv.innerHTML = '<span style="color: var(--color-text-muted); font-size: 12px;">No logs found</span>';
            }
            
            // Populate root directory
            const rootDirDiv = document.getElementById('rootDir');
            rootDirDiv.innerHTML = '';
            if (jsonLogsData.root_dir.length > 0) {
                jsonLogsData.root_dir.forEach(file => {
                    const btn = document.createElement('button');
                    btn.className = 'action-btn';
                    btn.style.padding = '8px 12px';
                    btn.textContent = file;
                    btn.onclick = () => startRealtimeStream('root', file);
                    rootDirDiv.appendChild(btn);
                    
                    // Also add to search select
                    const option = document.createElement('option');
                    option.value = JSON.stringify({location: 'root', file: file});
                    option.textContent = `${file} (from json_logs)`;
                    document.getElementById('jsonFileSelect').appendChild(option);
                });
            } else {
                rootDirDiv.innerHTML = '<span style="color: var(--color-text-muted); font-size: 12px;">No logs found</span>';
            }
            
            document.getElementById('jsonLogsLoadingMsg').style.display = 'none';
            document.getElementById('jsonLogsContainer').style.display = 'block';
        } catch (err) {
            alert('Error: ' + err.message);
            document.getElementById('jsonLogsLoadingMsg').style.display = 'none';
        }
    }
    
    function startRealtimeStream(location, filename) {
        currentRealtimeFile = filename;
        currentRealtimeLocation = location;
        document.getElementById('realtimeFileName').textContent = `${location}/${filename}`;
        document.getElementById('realtimeContainer').style.display = 'block';
        document.getElementById('realtimeLog').innerHTML = '💡 Real-time streaming enabled (3s refresh)\\n';
        document.getElementById('realtimeIndicator').style.background = '#10b981';
        document.getElementById('realtimeStatus').textContent = 'Running';
        toggleJsonRealtimeRefresh();
    }
    
    function toggleJsonRealtimeRefresh() {
        if (!currentRealtimeFile) {
            alert('Please select a log file first by clicking it in the list above');
            return;
        }
        
        if (realtimeIntervalId) {
            clearInterval(realtimeIntervalId);
            realtimeIntervalId = null;
            document.getElementById('realtimeToggleBtn').textContent = '▶️ Start Real-time (3s)';
            document.getElementById('realtimeToggleBtn').style.borderColor = '#6b7280';
            document.getElementById('realtimeToggleBtn').style.color = '#cbd5e1';
            document.getElementById('realtimeIndicator').style.background = '#ef4444';
            document.getElementById('realtimeStatus').textContent = 'Stopped';
            return;
        }
        
        // Start buffered real-time streaming (3-second chunks from backend)
        document.getElementById('realtimeToggleBtn').textContent = '⏸️ Stop Real-time';
        document.getElementById('realtimeToggleBtn').style.borderColor = '#10b981';
        document.getElementById('realtimeToggleBtn').style.color = '#10b981';
        
        streamBufferedLogs();
    }
    
    async function streamBufferedLogs() {
        // Stream JSON logs using buffered 3-second chunks
        // Backend pre-fetches next chunk while streaming current
        // Prevents memory bloat and webpage lag
        try {
            const log = document.getElementById('realtimeLog');
            log.innerHTML = '🔴 Connecting to buffered stream (3s chunks)...\\n';
            
            const url = `/api/json-logs/${currentRealtimeLocation}/${encodeURIComponent(currentRealtimeFile)}/live-tail`;
            const response = await fetch(url);
            
            if (!response.ok) {
                log.innerHTML += `\\n<span style="color: #ef4444">[ERROR] Status ${response.status}: ${response.statusText}</span>\\n`;
                return;
            }
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let chunkNumber = 0;
            
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\\n');
                
                // Keep last incomplete line in buffer
                buffer = lines.pop() || '';
                
                for (const line of lines) {
                    if (!line.trim()) continue;
                    
                    try {
                        const chunk = JSON.parse(line);
                        chunkNumber++;
                        
                        // Handle different chunk types
                        if (chunk.error) {
                            log.innerHTML += `\\n<span style="color: #ef4444">[CHUNK ${chunkNumber}] ERROR: ${escapeHtml(chunk.error)}</span>\\n`;
                        } else if (chunk.status === 'waiting') {
                            // Backend still reading, show heartbeat
                            log.innerHTML += `·`;
                            log.scrollTop = log.scrollHeight;
                        } else if (chunk.status === 'timeout') {
                            log.innerHTML += `\\n<span style="color: #f59e0b">[INFO] Stream timeout - session limit reached</span>\\n`;
                        } else if (chunk.lines) {
                            // Data chunk received
                            const lines = chunk.lines || [];
                            log.innerHTML += `\\n<span style="color: #4b7c59; font-weight: bold;">📊 Chunk #${chunkNumber} (${lines.length} lines @ ${new Date(chunk.timestamp * 1000).toLocaleTimeString()})</span>\\n`;
                            
                            lines.forEach((logLine) => {
                                try {
                                    const obj = JSON.parse(logLine);
                                    const ts1 = obj.timestamp1 || obj.timestamp;
                                    const tsDisplay = ts1 ? new Date(ts1 > 1e12 ? ts1 : ts1 * 1000).toLocaleString() : '';
                                    log.innerHTML += `<span style="color: #94a3b8; font-size: 11px;">[${tsDisplay}]</span> ${escapeHtml(logLine)}\\n`;
                                } catch {
                                    log.innerHTML += escapeHtml(logLine) + '\\n';
                                }
                            });
                            
                            log.scrollTop = log.scrollHeight;
                        }
                    } catch (parseErr) {
                        // Skip lines that aren't valid JSON
                        if (line.trim()) {
                            log.innerHTML += escapeHtml(line) + '\\n';
                            log.scrollTop = log.scrollHeight;
                        }
                    }
                }
            }
            
            // Final buffer flush
            if (buffer.trim()) {
                log.innerHTML += escapeHtml(buffer) + '\\n';
                log.scrollTop = log.scrollHeight;
            }
            
            log.innerHTML += `\\n<span style="color: #f59e0b">[INFO] Stream completed normally</span>\\n`;
            document.getElementById('realtimeIndicator').style.background = '#ef4444';
            document.getElementById('realtimeStatus').textContent = 'Stopped';
            document.getElementById('realtimeToggleBtn').textContent = '▶️ Start Real-time (3s)';
            document.getElementById('realtimeToggleBtn').style.borderColor = '#6b7280';
            document.getElementById('realtimeToggleBtn').style.color = '#cbd5e1';
            
        } catch (err) {
            const log = document.getElementById('realtimeLog');
            log.innerHTML += `\\n<span style="color: #ef4444">[ERROR] Connection failed: ${escapeHtml(err.message)}</span>\\n`;
            document.getElementById('realtimeIndicator').style.background = '#ef4444';
            document.getElementById('realtimeStatus').textContent = 'Error';
        }
    }
    
    async function searchJsonLogsByTime() {
        const fileData = document.getElementById('jsonFileSelect').value;
        if (!fileData) {
            alert('Please select a log file');
            return;
        }
        
        const { location, file } = JSON.parse(fileData);
        const fromTime = document.getElementById('fromDateTime').value;
        const toTime = document.getElementById('toDateTime').value;
        
        if (!fromTime || !toTime) {
            alert('Please enter both From and To times (dd/mm/yyyy hh:mm:ss)');
            return;
        }
        
        document.getElementById('jsonSearchLoading').style.display = 'block';
        document.getElementById('jsonSearchResults').style.display = 'none';
        
        try {
            const res = await fetch('/api/json-logs/search', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    log_file: file,
                    location: location,
                    from_time: fromTime,
                    to_time: toTime
                })
            });
            
            const data = await res.json();
            document.getElementById('jsonSearchLoading').style.display = 'none';
            document.getElementById('jsonSearchResults').style.display = 'block';
            
            if (!data.success) {
                document.getElementById('jsonResultCount').textContent = '';
                document.getElementById('jsonResultsLog').innerHTML = `<span style="color: #ef4444">${escapeHtml(data.error)}</span>`;
                return;
            }
            
            jsonRawLines = data.lines || [];
            document.getElementById('jsonResultCount').textContent = `(${jsonRawLines.length} records found)`;
            renderJsonResults();
        } catch (err) {
            document.getElementById('jsonSearchLoading').style.display = 'none';
            document.getElementById('jsonSearchResults').style.display = 'block';
            document.getElementById('jsonResultsLog').innerHTML = `<span style="color: #ef4444">Error: ${escapeHtml(err.message)}</span>`;
        }
    }
    
    function renderJsonResults() {
        const pretty = document.getElementById('prettyJsonFormat').checked;
        const el = document.getElementById('jsonResultsLog');
        
        if (jsonRawLines.length === 0) {
            el.innerHTML = '<span style="color: var(--color-text-muted);">No records found in this time range.</span>';
            return;
        }
        
        let html = '';
        jsonRawLines.forEach((line, i) => {
            if (!line.trim()) return;
            if (pretty) {
                try {
                    const obj = JSON.parse(line);
                    const ts1 = obj.timestamp1 || obj.timestamp;
                    const tsDisplay = ts1 ? new Date(ts1 > 1e12 ? ts1 : ts1 * 1000).toLocaleString() : '';
                    html += `<span style="color: #4b5563; font-size: 11px;">─── Record ${i+1}${tsDisplay ? ' · ' + tsDisplay : ''} ───</span>\\n`;
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
    with cached_machines_lock:
        machines_list = cached_machines if cached_machines else get_tailscale_machines_api()
    
    return render_template_string(
        MACHINES_TEMPLATE,
        machines=machines_list,
        total=len(machines_list),
        online=sum(1 for m in machines_list if m['online']),
        offline=sum(1 for m in machines_list if not m['online']),
        default_username=LINUX_USER_PASS
    )

@app.route('/api/machines')
def api_machines():
    """API endpoint for getting current cached machine list (for auto-refresh)"""
    with cached_machines_lock:
        machines_list = cached_machines if cached_machines else get_tailscale_machines_api()
        update_time = last_update_time
    
    total_machines = len(machines_list)
    online_machines = sum(1 for m in machines_list if m['online'])
    offline_machines = total_machines - online_machines
    
    return jsonify({
        'success': True,
        'machines': machines_list,
        'total': total_machines,
        'online': online_machines,
        'offline': offline_machines,
        'last_update': update_time,
        'timestamp': time.time()
    })

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
    target_logs = []
    gateway_files = []
    
    # Look for standard .log files in both locations
    # Location 1: /opt/go-ble-orchestrator/logs
    out_base, err_base = execute_ssh(f"ls -1 {LOG_DIR}/*.log 2>/dev/null")
    if out_base:
        target_logs.extend([f.strip().split('/')[-1] for f in out_base.split('\n') if f.strip().endswith('.log')])
    
    # Location 2: /opt/go-ble-orchestrator/ (legacy)
    out_legacy, err_legacy = execute_ssh("ls -1 /opt/go-ble-orchestrator/*.log 2>/dev/null")
    if out_legacy:
        target_logs.extend([f.strip().split('/')[-1] for f in out_legacy.split('\n') if f.strip().endswith('.log')])
    
    # Remove duplicates and sort
    target_logs = sorted(list(set(target_logs)))
    
    # Look for json_logs in both locations
    # Location 1: /opt/go-ble-orchestrator/logs/json_logs
    out_json1, err_json1 = execute_ssh(f"ls -1 {LOG_DIR}/json_logs/*.log 2>/dev/null || ls -1 {LOG_DIR}/json_logs/*.json 2>/dev/null")
    if out_json1:
        gateway_files.extend([f.strip().split('/')[-1] for f in out_json1.split('\n') if f.strip()])
    
    # Location 2: /opt/go-ble-orchestrator/json_logs (legacy)
    out_json2, err_json2 = execute_ssh("ls -1 /opt/go-ble-orchestrator/json_logs/*.log 2>/dev/null || ls -1 /opt/go-ble-orchestrator/json_logs/*.json 2>/dev/null")
    if out_json2:
        gateway_files.extend([f.strip().split('/')[-1] for f in out_json2.split('\n') if f.strip()])
    
    # Remove duplicates and sort
    gateway_files = sorted(list(set(gateway_files)))

    return render_template_string(
        DASHBOARD_TEMPLATE,
        target_ip=session.get('target_ip'),
        logs=target_logs,
        gateway_files=gateway_files,
        playbooks=playbooks,
        log_dir=LOG_DIR
    )

def find_log_file(filename):
    """
    Find a log file in either location:
    1. /opt/go-ble-orchestrator/logs/
    2. /opt/go-ble-orchestrator/
    Returns (full_path, location_type) or (None, None) if not found
    """
    safe_name = filename.replace('..', '').lstrip('/')
    
    # Try logs directory first
    path1 = f"{LOG_DIR}/{safe_name}"
    # Try legacy root location
    path2 = f"/opt/go-ble-orchestrator/{safe_name}"
    
    return path1, path2

def find_json_log_file(filename):
    """
    Find a JSON log file in either location:
    1. /opt/go-ble-orchestrator/logs/json_logs/
    2. /opt/go-ble-orchestrator/json_logs/
    Returns (full_path, location_type) or (None, None) if not found
    """
    safe_name = filename.replace('..', '').lstrip('/')
    
    # Try logs directory first
    path1 = f"{LOG_DIR}/json_logs/{safe_name}"
    # Try legacy root location
    path2 = f"/opt/go-ble-orchestrator/json_logs/{safe_name}"
    
    return path1, path2

@app.route('/view/<path:filename>')
def view_file(filename):
    if 'ssh_id' not in session:
        return redirect(url_for('machines'))
    
    path1, path2 = find_log_file(filename)
    
    # Try path1 first - reduced to 300 lines to avoid timeout on large files
    out, err = execute_ssh(f"tail -n 300 {path1} 2>&1")
    
    # If file not found in path1 (error in output due to 2>&1), try path2
    # Note: with 2>&1, error message is in 'out', not 'err'
    if (not out or 'No such file' in out or 'cannot open' in out):
        out, err = execute_ssh(f"tail -n 300 {path2} 2>&1")
    
    return render_template_string(
        VIEWER_TEMPLATE,
        filename=filename,
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
    
    path1, path2 = find_json_log_file(filename)
    
    last_error = None
    
    # Try both locations
    for log_path in [path1, path2]:
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
            f"\" 2>&1"
        )
        
        out, err = execute_ssh(python_cmd)
        
        # Check if we got a file not found error
        if out and ('FileNotFoundError' in out or 'No such file' in out or 'cannot open' in out):
            last_error = out
            continue  # Try next path
        
        # If we got here and have output, return it (could be empty results or actual data)
        if out is not None:
            lines = [l for l in out.split('\n') if l.strip()]
            return jsonify({
                "lines": lines,
                "count": len(lines),
                "from_epoch": from_epoch,
                "to_epoch": to_epoch
            })
    
    # If we get here, file not found in either location
    error_msg = last_error if last_error else "File not found in either location"
    return jsonify({"error": error_msg}), 404

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
    path1 = f"{LOG_DIR}/{safe_filename}"
    path2 = f"/opt/go-ble-orchestrator/{safe_filename}"

    def generate():
        if not client:
            yield "data: [ERROR] Session expired. Please reconnect.\n\n"
            return
        try:
            # Use bash conditional to check path1 first, fallback to path2 if not found
            # [ -f path1 ] && use path1 || use path2
            cmd = f"[ -f '{path1}' ] && tail -n 50 -f '{path1}' 2>&1 || tail -n 50 -f '{path2}' 2>&1"
            stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
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

# ============================================================================
# JSON LOG ENDPOINTS
# ============================================================================

@app.route('/api/json-logs/list', methods=['GET'])
def list_json_logs_api():
    """List available JSON log files from both directories"""
    session_id = session.get('ssh_id')
    if not session_id or session_id not in active_ssh_sessions:
        return jsonify({'success': False, 'error': 'SSH session not found'})
    
    client = active_ssh_sessions.get(session_id)
    logs = list_json_logs(client)
    
    return jsonify({
        'success': True,
        'logs': {
            'logs_dir': logs.get('logs', []),  # From /opt/go-ble-orchestrator/logs/json_logs
            'root_dir': logs.get('root', [])   # From /opt/go-ble-orchestrator/json_logs
        }
    })

@app.route('/api/json-logs/search', methods=['POST'])
def search_json_logs_api():
    """Search JSON logs by timestamp range"""
    session_id = session.get('ssh_id')
    if not session_id or session_id not in active_ssh_sessions:
        return jsonify({'success': False, 'error': 'SSH session not found'})
    
    data = request.get_json()
    log_file = data.get('log_file', '')
    log_location = data.get('location', 'logs')  # 'logs' or 'root'
    from_time = data.get('from_time', '')
    to_time = data.get('to_time', '')
    
    if not all([log_file, from_time, to_time]):
        return jsonify({'success': False, 'error': 'Missing parameters: log_file, from_time, to_time'})
    
    # Determine log directory
    if log_location == 'root':
        log_dir = '/opt/go-ble-orchestrator/json_logs'
    else:
        log_dir = '/opt/go-ble-orchestrator/logs/json_logs'
    
    try:
        start_epoch = parse_datetime_string(from_time)
        end_epoch = parse_datetime_string(to_time)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)})
    
    if start_epoch >= end_epoch:
        return jsonify({'success': False, 'error': 'From time must be before To time'})
    
    client = active_ssh_sessions.get(session_id)
    lines, error = search_json_logs_by_timestamp(client, log_dir, log_file, start_epoch, end_epoch)
    
    if error:
        return jsonify({'success': False, 'error': error})
    
    return jsonify({
        'success': True,
        'count': len(lines),
        'lines': lines,
        'from_epoch': start_epoch,
        'to_epoch': end_epoch
    })

@app.route('/api/json-logs/<location>/<filename>', methods=['GET'])
def get_json_log_realtime(location, filename):
    """Stream JSON log file in real-time"""
    session_id = session.get('ssh_id')
    if not session_id or session_id not in active_ssh_sessions:
        return jsonify({'success': False, 'error': 'SSH session not found'}), 403
    
    # Determine log directory
    if location == 'root':
        log_dir = '/opt/go-ble-orchestrator/json_logs'
    else:
        log_dir = '/opt/go-ble-orchestrator/logs/json_logs'
    
    log_path = f"{log_dir}/{filename}"
    client = active_ssh_sessions.get(session_id)
    
    try:
        # Get last 100 lines
        stdin, stdout, stderr = client.exec_command(f'tail -100 {log_path}')
        exit_code = stdout.channel.recv_exit_status()
        
        if exit_code != 0:
            error = stderr.read().decode('utf-8').strip()
            return jsonify({'success': False, 'error': error})
        
        content = stdout.read().decode('utf-8').strip()
        lines = [l for l in content.split('\n') if l.strip()]
        
        return jsonify({
            'success': True,
            'filename': filename,
            'location': location,
            'count': len(lines),
            'lines': lines,
            'timestamp': time.time()
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/json-logs/<location>/<filename>/live-tail', methods=['GET'])
def live_tail_buffered(location, filename):
    """
    Stream JSON log file with 3-second buffering
    Prevents memory bloat by using background threads to pre-fetch chunks
    Each chunk contains 100 lines, sent every 3 seconds
    """
    session_id = session.get('ssh_id')
    if not session_id or session_id not in active_ssh_sessions:
        return jsonify({'success': False, 'error': 'SSH session not found'}), 403
    
    # Determine log directory
    if location == 'root':
        log_dir = '/opt/go-ble-orchestrator/json_logs'
    else:
        log_dir = '/opt/go-ble-orchestrator/logs/json_logs'
    
    client = active_ssh_sessions.get(session_id)
    
    # Create unique streamer instance per request
    streamer_id = f"{session_id}_{location}_{filename}"
    
    # Stop any existing streamer for this file
    if streamer_id in active_streamers:
        active_streamers[streamer_id].stop()
    
    # Create new buffered streamer (3-second chunks with background thread)
    streamer = BufferedTailStreamer(client, log_dir, filename, chunk_size=3)
    active_streamers[streamer_id] = streamer
    
    def cleanup():
        """Clean up streamer when connection closes"""
        if streamer_id in active_streamers:
            active_streamers[streamer_id].stop()
            del active_streamers[streamer_id]
    
    try:
        # Return streaming response with chunks
        response = Response(streamer.stream_chunks(timeout_seconds=3600), mimetype='application/x-ndjson')
        response.call_on_close(cleanup)
        return response
    except Exception as e:
        cleanup()
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    print("""
    ╔════════════════════════════════════════════════════╗
    ║   Orchestrator Manager - Full Integration         ║
    ╚════════════════════════════════════════════════════╝
    
    🌐 http://localhost:5005
    
    🔄 Background monitoring: ENABLED
       - Auto-discovering new machines
       - Polling interval: {} seconds
    """.format(update_interval))
    
    # Start background monitoring thread
    start_background_monitor()
    
    app.run(host='127.0.0.1', port=5005, debug=True, use_reloader=False)