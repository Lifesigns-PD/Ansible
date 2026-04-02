#!/usr/bin/env python3
"""
Tailscale-Aware Orchestrator Deployment Tool
Fetches machines from Tailscale, prompts for credentials, and triggers deployment
"""

import os
import sys
import json
import subprocess
import re
import getpass
from pathlib import Path
from typing import List, Dict, Tuple

# Load environment variables
from dotenv import load_dotenv

# Load .env from the scripts directory
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

# Configuration
TAILSCALE_API_KEY = os.getenv('TAILSCALE_API_KEY')
TAILSCALE_TAILNET = os.getenv('Tailscale-tailnet-name', 'T48tog1ov911CNTRL')
TAILSCALE_API_BASE = "https://api.tailscale.com/api/v2"

# Deployment config
ANSIBLE_DIR = Path(__file__).parent.parent
BINARY_DIR = Path(__file__).parent.parent.parent / "Cassia"
LOG_DIR = Path(__file__).parent.parent / "logs"

# Colors for terminal output
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_header(msg: str):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}")
    print(f"{msg}")
    print(f"{'='*60}{Colors.ENDC}\n")

def print_success(msg: str):
    print(f"{Colors.OKGREEN}✓ {msg}{Colors.ENDC}")

def print_info(msg: str):
    print(f"{Colors.OKCYAN}ℹ {msg}{Colors.ENDC}")

def print_warning(msg: str):
    print(f"{Colors.WARNING}⚠ {msg}{Colors.ENDC}")

def print_error(msg: str):
    print(f"{Colors.FAIL}✗ {msg}{Colors.ENDC}")

def get_tailscale_machines_local() -> List[Dict[str, str]]:
    """
    Get machines from local Tailscale client (no API key needed)
    Requires tailscale CLI installed
    """
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
                    'peer_id': peer_id
                })
        
        return sorted(machines, key=lambda x: x['hostname'])
        
    except FileNotFoundError:
        print_error("Tailscale CLI not installed. Install from https://tailscale.com/download")
        return []
    except subprocess.CalledProcessError as e:
        print_error(f"Tailscale not running: {e}")
        return []
    except json.JSONDecodeError:
        print_error("Failed to parse Tailscale output")
        return []

def get_tailscale_machines_api() -> List[Dict[str, str]]:
    """
    Get machines from Tailscale API (requires API key)
    """
    if not TAILSCALE_API_KEY:
        return []
    
    try:
        import requests
        
        headers = {
            'Authorization': f'Bearer {TAILSCALE_API_KEY}',
            'Accept': 'application/json'
        }
        
        url = f"{TAILSCALE_API_BASE}/tailnet/{TAILSCALE_TAILNET}/devices"
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            print_warning(f"Tailscale API error: {response.status_code}")
            return []
        
        data = response.json()
        machines = []
        
        for device in data.get('devices', []):
            # Get first IPv4 from addresses
            ips = device.get('addresses', [])
            tailscale_ip = next((ip.split('/')[0] for ip in ips if ':' not in ip), None)
            
            if tailscale_ip:
                machines.append({
                    'hostname': device.get('name', 'Unknown').rstrip('.'),
                    'ip': tailscale_ip,
                    'online': device.get('online', False),
                    'os': device.get('os', 'Unknown'),
                    'device_id': device.get('id')
                })
        
        return sorted(machines, key=lambda x: x['hostname'])
        
    except ImportError:
        print_warning("requests library not installed. Install with: pip install requests")
        return []
    except Exception as e:
        print_error(f"API fetch failed: {e}")
        return []

def select_machine(machines: List[Dict[str, str]]) -> Tuple[str, str]:
    """
    Display machines and prompt user to select one
    Returns tuple of (hostname, ip)
    """
    if not machines:
        print_error("No machines found!")
        return None, None
    
    print_header("Available Tailscale Machines")
    
    for idx, machine in enumerate(machines, 1):
        status = "🟢 Online" if machine.get('online') else "🔴 Offline"
        print(f"{idx}. {machine['hostname']:<25} ({machine['ip']:<15}) {status}")
    
    while True:
        try:
            choice = input(f"\n{Colors.BOLD}Select machine (1-{len(machines)}): {Colors.ENDC}").strip()
            idx = int(choice) - 1
            
            if 0 <= idx < len(machines):
                selected = machines[idx]
                
                if not selected.get('online'):
                    print_warning(f"⚠ {selected['hostname']} is offline. Proceed anyway? (y/n): ", end='')
                    if input().lower() != 'y':
                        continue
                
                print_success(f"Selected: {selected['hostname']} ({selected['ip']})")
                return selected['hostname'], selected['ip']
            else:
                print_error("Invalid selection!")
        except ValueError:
            print_error("Please enter a number!")

def prompt_credentials() -> Tuple[str, str]:
    """
    Prompt user for SSH credentials
    """
    print_header("SSH Credentials")
    
    username = input(f"{Colors.BOLD}SSH Username: {Colors.ENDC}").strip()
    if not username:
        print_error("Username cannot be empty!")
        return None, None
    
    password = getpass.getpass(f"{Colors.BOLD}SSH Password: {Colors.ENDC}")
    if not password:
        print_warning("Using key-based authentication instead")
        return username, None
    
    return username, password

def validate_binary_dir() -> bool:
    """
    Validate that binary directory exists
    """
    if not BINARY_DIR.exists():
        print_warning(f"Binary directory not found: {BINARY_DIR}")
        print_info("Deployment options:")
        print_info("  1. Ensure binaries are built: CGO_ENABLED=0 GOOS=linux go build")
        print_info("  2. Or use GitHub method (will be downloaded on target)")
        return False
    
    required_files = [
        'go-ble-orchestrator',
        'ecg_metrics',
        'frontend'
    ]
    
    missing = [f for f in required_files if not (BINARY_DIR / f).exists()]
    
    if missing:
        print_warning(f"Missing files in {BINARY_DIR}:")
        for f in missing:
            print(f"  - {f}")
        return False
    
    print_success(f"Binary directory validated: {BINARY_DIR}")
    return True

def show_deployment_methods():
    """
    Show deployment methods and explain differences
    """
    print_header("Deployment Methods")
    
    print(f"""{Colors.BOLD}Method 1: Ansible (Recommended for multi-server){Colors.ENDC}
    ├─ Uses: {Colors.OKCYAN}ansible-playbook playbooks/deploy.yml{Colors.ENDC}
    ├─ Requires: Pre-built binaries in {Colors.OKBLUE}{BINARY_DIR}{Colors.ENDC}
    ├─ Benefits: 
    │  • Fast - no downloads
    │  • Reproducible - same binaries across servers
    │  • Rollback capability
    │  • Configuration management via Ansible
    └─ Best for: Multiple servers, consistent deployments

{Colors.BOLD}Method 2: GitHub Auto-Download (Recommended for single server){Colors.ENDC}
    ├─ Uses: {Colors.OKCYAN}orchestrator setup/setup.sh{Colors.ENDC}
    ├─ Downloads: Latest release from GitHub API
    ├─ Benefits:
    │  • No pre-staging of binaries
    │  • Always latest version
    │  • Includes gateway-dashboard setup
    │  • Simpler for one-off deployments
    └─ Best for: Single server, manual deployment, always-latest

{Colors.BOLD}Method 3: Hybrid (Recommended for production){Colors.ENDC}
    ├─ Build locally → Ansible deploy to all servers
    ├─ Ensures version consistency across your infrastructure
    └─ Fastest deployment with full auditability
""")

def generate_ansible_command(target_ip: str, username: str, password: str = None, method: str = 'local') -> str:
    """
    Generate Ansible deployment command
    """
    cmd_parts = [
        'cd', str(ANSIBLE_DIR), '&&',
        'ansible-playbook',
        'playbooks/deploy.yml',
        '-i', 'inventory/production.yml',
        '-e', f'ansible_host={target_ip}',
        '-e', f'ansible_user={username}',
    ]
    
    if password:
        cmd_parts.extend(['-e', f'ansible_password={password}', '-k'])
    
    cmd_parts.extend(['--ask-vault-pass', '-vv'])
    
    return ' '.join(cmd_parts)

def generate_github_command(target_ip: str, username: str, password: str = None) -> str:
    """
    Generate command to run GitHub setup script
    """
    # Build SSH connection string
    ssh_user_host = f"{username}@{target_ip}"
    
    # SSH command that downloads and runs setup.sh
    cmd = f"""ssh {ssh_user_host} 'bash -c "
        curl -fsSL https://raw.githubusercontent.com/Lifesigns-PD/orchestrator-releases/main/setup.sh | sudo bash
    "'"""
    
    return cmd

def main():
    """
    Main orchestration flow
    """
    print_header("BLE Orchestrator Deployment Tool")
    
    # Step 1: Fetch Tailscale machines
    print_info("Fetching Tailscale machines...")
    
    # Try API first, fall back to local client
    machines = get_tailscale_machines_api()
    if not machines:
        print_info("Trying local Tailscale client...")
        machines = get_tailscale_machines_local()
    
    if not machines:
        print_error("Could not fetch machines from Tailscale!")
        sys.exit(1)
    
    print_success(f"Found {len(machines)} machines")
    
    # Step 2: User selects machine
    hostname, target_ip = select_machine(machines)
    if not hostname:
        print_error("No machine selected!")
        sys.exit(1)
    
    # Step 3: Prompt for credentials
    username, password = prompt_credentials()
    if not username:
        print_error("No credentials provided!")
        sys.exit(1)
    
    # Step 4: Show deployment methods
    show_deployment_methods()
    
    print(f"\n{Colors.BOLD}Which deployment method? (1-3): {Colors.ENDC}", end='')
    choice = input().strip()
    
    if choice == '1':
        # Ansible method
        if not validate_binary_dir():
            print_error("Cannot proceed with Ansible deployment!")
            sys.exit(1)
        
        cmd = generate_ansible_command(target_ip, username, password)
        print_header("Ansible Deployment Command")
        print(f"{Colors.OKBLUE}{cmd}{Colors.ENDC}")
        
    elif choice == '2':
        # GitHub method
        cmd = generate_github_command(target_ip, username, password)
        print_header("GitHub Auto-Download Command")
        print(f"{Colors.OKBLUE}{cmd}{Colors.ENDC}")
        print_info("This will:")
        print_info("  1. SSH into target server")
        print_info("  2. Download latest orchestrator release from GitHub")
        print_info("  3. Download latest gateway-dashboard")
        print_info("  4. Setup systemd services")
        
    elif choice == '3':
        # Hybrid method
        if not validate_binary_dir():
            print_error("Cannot proceed with hybrid deployment!")
            sys.exit(1)
        
        print_header("Hybrid Deployment Plan")
        print(f"1. Using Ansible to deploy pre-built binaries from {BINARY_DIR}")
        cmd = generate_ansible_command(target_ip, username, password)
        print(f"\n{Colors.OKBLUE}{cmd}{Colors.ENDC}")
        
    else:
        print_error("Invalid choice!")
        sys.exit(1)
    
    # Step 5: Confirm and execute
    print(f"\n{Colors.BOLD}Ready to deploy to {Colors.OKGREEN}{hostname}{Colors.ENDC} ({target_ip})")
    print(f"{Colors.WARNING}⚠ Review the command above carefully!{Colors.ENDC}")
    print(f"\n{Colors.BOLD}Execute deployment? (y/n): {Colors.ENDC}", end='')
    
    if input().lower() == 'y':
        print_info("Starting deployment...")
        try:
            if choice in ['1', '3']:
                # Ansible deployment
                subprocess.run(cmd, shell=True, check=True)
            else:
                # GitHub method
                subprocess.run(cmd, shell=True, check=True)
            
            print_success("Deployment completed successfully!")
            
        except subprocess.CalledProcessError as e:
            print_error(f"Deployment failed: {e}")
            sys.exit(1)
    else:
        print_info("Deployment cancelled")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}Aborted by user{Colors.ENDC}")
        sys.exit(0)
