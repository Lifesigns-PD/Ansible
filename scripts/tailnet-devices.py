import requests
import json
import sys
import subprocess
import os
from dotenv import load_dotenv

# --- LOAD LOCAL ENVIRONMENT VARIABLES ---
# This looks for the .env file in the same directory as this script
load_dotenv()

# --- TAILSCALE CONFIGURATION ---
# Using the specific keys from your .env file
TAILSCALE_API_KEY = os.environ.get("Tailscale-tailnet-apikey")
TAILNET_NAME = os.environ.get("Tailscale-tailnet-name")

# --- SEMAPHORE CONFIGURATION ---
SEMAPHORE_API_TOKEN = "hpvsh9hnfxfethk2dvar0_stbeib_fg4ecrlrlb_woc=" 
SEMAPHORE_URL = "http://localhost:8085/api"

# Project-specific IDs from your browser URL
CONFIG = {
    "project_id": 1,
    "inventory_id": 1,
    "repository_id": 1,
    "become_key_id": 1,
    "view_id": None,         # Set to None (null) to avoid 'Invalid view' errors
    "environment_id": None   # Set to None (null) since you mentioned no environments exist
}

# --- PLAYBOOKS ---
PLAYBOOKS = {
    "deploy": "playbooks/deploy.yml",
    "uninstall": "playbooks/uninstall.yml"
}

def get_tailscale_devices():
    """Fetch devices using the Tailscale API and extract MagicDNS."""
    url = f"https://api.tailscale.com/api/v2/tailnet/{TAILNET_NAME}/devices"
    try:
        # Tailscale uses Basic Auth with the API Key as the username
        response = requests.get(url, auth=(TAILSCALE_API_KEY, ""))
        
        if response.status_code != 200:
            print(f"❌ Tailscale API Error: {response.status_code}")
            print(f"   Details: {response.text}")
            return []
        
        devices = response.json().get("devices", [])
        linux_nodes = []
        
        print(f"\n{'HOSTNAME':<25} {'MAGIC DNS':<45} {'OS':<10}")
        print("-" * 80)
        
        for dev in devices:
            # Filter for Linux only
            if dev.get("os") != "linux":
                continue
            
            hostname = dev.get("hostname")
            # The API 'name' field contains the full MagicDNS (e.g., machine.tailnet.ts.net)
            magic_dns = dev.get("name")
            
            linux_nodes.append({
                "hostname": hostname,
                "magic_dns": magic_dns
            })
            print(f"{hostname:<25} {magic_dns:<45} Linux")
            
        return linux_nodes
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return []

def create_semaphore_template(device, t_type, playbook):
    """Create template in Semaphore via API."""
    headers = {
        "Authorization": f"Bearer {SEMAPHORE_API_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Use MagicDNS for the Ansible limit flag
    target = device['magic_dns']
    
    # Construct a minimalist payload. 
    # We remove 'app_id' and 'project_id' from the body as they are handled by the URL.
    # 'arguments' is sent as a raw list rather than a stringified JSON.
    payload = {
        "name": f"{t_type.capitalize()} to {device['hostname']}",
        "playbook": playbook,
        "inventory_id": int(CONFIG["inventory_id"]),
        "repository_id": int(CONFIG["repository_id"]),
        "environment_id": CONFIG["environment_id"],
        "view_id": CONFIG["view_id"],
        "become_key_id": int(CONFIG["become_key_id"]),
        "arguments": json.dumps(["-l", target, "-vv"]),
        "allow_override_args_in_task": True,
        "description": f"Tailscale MagicDNS: {target}"
    }

    # API Endpoint includes the project_id
    url = f"{SEMAPHORE_URL}/project/{CONFIG['project_id']}/templates"
    
    try:
        # Use json= parameter for automatic JSON conversion
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code in [200, 201]:
            print(f"  ✅ {t_type.capitalize()} Created")
        else:
            # Print the exact error and the payload sent for debugging
            print(f"  ❌ {t_type.capitalize()} Failed: {response.text}")
    except Exception as e:
        print(f"  ❌ Request Error: {e}")

def main():
    if not TAILSCALE_API_KEY:
        print("❌ ERROR: TAILSCALE_API_KEY missing from .env (key: 'Tailscale-tailnet-apikey')")
        return
    if not TAILNET_NAME:
        print("❌ ERROR: TAILNET_NAME missing from .env (key: 'Tailscale-tailnet-name')")
        return

    print("Step 1: Fetching devices from Tailscale API...")
    devices = get_tailscale_devices()
    
    if not devices:
        print("No Linux devices found.")
        return

    print(f"\nFound {len(devices)} Linux devices.")
    confirm = input("Confirm these are correct and proceed with Semaphore template creation? (y/n): ")
    
    if confirm.lower() != 'y':
        print("Aborted by user.")
        return

    print("\nStep 2: Creating Semaphore Templates...")
    for dev in devices:
        print(f"\n⚙️ Processing {dev['hostname']}...")
        for t_type, p_path in PLAYBOOKS.items():
            create_semaphore_template(dev, t_type, p_path)

    print("\n✨ Process Complete! Check your Semaphore UI.")

if __name__ == "__main__":
    main()