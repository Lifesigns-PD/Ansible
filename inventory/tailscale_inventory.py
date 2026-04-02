#!/usr/bin/env python3
import os
import json
import urllib.request

# Pull credentials from environment variables (provided by Semaphore)
TAILSCALE_API_KEY = os.environ.get('tskey-api-kKExQPNGLY11CNTRL-qP8bip3VH71WHFL5pkk871GJJciqt53J')
TAILNET_NAME = os.environ.get('T48tog1ov911CNTRL')

def get_inventory():
    if not TAILSCALE_API_KEY or not TAILNET_NAME:
        return {}

    url = f"https://api.tailscale.com/api/v2/tailnet/{TAILNET_NAME}/devices"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TAILSCALE_API_KEY}"})
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            devices = data.get('devices', [])
    except Exception as e:
        # Fallback to empty inventory if API fails
        return {}

    inventory = {
        "tailscale_servers": {"hosts": []},
        "orchestrator_servers": {"children": ["tailscale_servers"]},
        "_meta": {"hostvars": {}}
    }

    for dev in devices:
        hostname = dev['hostname']
        ip = dev['addresses'][0] # Grabs the 100.x.x.x IPv4 address
        
        # Add to the group
        inventory["tailscale_servers"]["hosts"].append(hostname)
        
        # Tell Ansible how to connect to it
        inventory["_meta"]["hostvars"][hostname] = {
            "ansible_host": ip,
            "ansible_user": "ubuntu", # Change this if your machines use a different username
            "ansible_port": 22
        }

    return inventory

if __name__ == "__main__":
    # Ansible expects dynamic scripts to accept a --list argument
    import sys
    if len(sys.argv) == 2 and sys.argv[1] == '--list':
        print(json.dumps(get_inventory(), indent=2))
    else:
        print(json.dumps(get_inventory(), indent=2))
