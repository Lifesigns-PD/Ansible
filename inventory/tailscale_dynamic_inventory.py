#!/usr/bin/env python3
"""
Semaphore Dynamic Inventory Plugin - IMPROVED
Discovers all devices in Tailnet using Tailscale API v2 with full device attributes.
✓ Uses fields=all parameter for comprehensive device data
✓ Groups devices by tags, status, and authorization
✓ Retrieves tags, device routes, and advanced attributes
✓ Works with Semaphore environment variables
API Spec: https://api.tailscale.com/api/v2/
"""

import json
import subprocess
import sys
import os
from pathlib import Path
from typing import Dict, List, Any
import time

# ============================================================================
# ENV VARIABLE MAPPING - Semaphore Compatible
# ============================================================================

TAILSCALE_API_KEY = os.getenv("TAILSCALE_API_KEY") or os.getenv("Tailscale-tailnet-apikey")
TAILSCALE_TENANT_NAME = os.getenv("TAILSCALE_TENANT_NAME") or os.getenv("Tailscale-tailnet-name")
LINUX_USER = os.getenv("LINUX_USER") or os.getenv("linux_user") or "ubuntu"
LINUX_PASS = os.getenv("LINUX_PASS") or os.getenv("linux_user_pass")

# ============================================================================
# IMPROVED TAILSCALE API FUNCTIONS
# ============================================================================

def get_tailscale_devices_with_all_fields() -> List[Dict[str, Any]]:
    """
    Get all devices from Tailscale API with comprehensive field data.
    
    API Endpoint: GET /api/v2/tailnet/{tailnet}/devices
    Parameters: fields=all (returns all device attributes instead of defaults)
    
    Includes:
    - addresses, id, nodeId, name, hostname, os, created, lastSeen
    - authorized, connectedToControl, keyExpiryDisabled, expires
    - tags, blocksIncomingConnections, tailnetLockKey, tailnetLockError
    - machineKey, nodeKey, isExternal, isEphemeral, clientVersion
    """
    api_key = TAILSCALE_API_KEY
    
    if not api_key:
        print("[ERROR] TAILSCALE_API_KEY not set", file=sys.stderr)
        return []

    try:
        import requests
        
        # IMPROVED: Use fields=all to get all device attributes per Tailscale API spec
        url = "https://api.tailscale.com/api/v2/tailnet/-/devices?fields=all"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json"
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        devices = data.get('devices', [])
        
        print(f"[INFO] Retrieved {len(devices)} devices from Tailscale API", file=sys.stderr)
        return devices
        
    except Exception as e:
        print(f"[ERROR] API Error: {e}", file=sys.stderr)
        return []


def get_device_routes(device_id: str, api_key: str) -> Dict[str, Any]:
    """
    Retrieve routes advertised and enabled for a device.
    
    API Endpoint: GET /api/v2/device/{deviceId}/routes
    Returns: advertised and enabled subnet routes for this device
    """
    try:
        import requests
        
        url = f"https://api.tailscale.com/api/v2/device/{device_id}/routes"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json"
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
        return {'advertised': [], 'enabled': []}
        
    except Exception as e:
        return {'advertised': [], 'enabled': []}


def get_device_attributes(device_id: str, api_key: str) -> Dict[str, Any]:
    """
    Retrieve custom posture attributes for a device.
    
    API Endpoint: GET /api/v2/device/{deviceId}/attributes
    Returns: all posture attributes (both managed and custom:namespace)
    """
    try:
        import requests
        
        url = f"https://api.tailscale.com/api/v2/device/{device_id}/attributes"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json"
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
        return {}
        
    except Exception as e:
        return {}


def get_tailscale_machines_api() -> List[Dict[str, Any]]:
    """
    Enhanced machine discovery using Tailscale API v2 with all fields.
    Merges device info with local status when available.
    """
    api_key = TAILSCALE_API_KEY
    machines_by_ip = {}
    
    # IMPROVED: Try local client for real-time online/offline status (faster than API)
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
                    'os': peer_data.get('OS', 'Unknown'),
                    'client_version': peer_data.get('ClientVersion', '')
                }
        print("[INFO] Local Tailscale status retrieved", file=sys.stderr)
    except Exception as e:
        print(f"[WARNING] Local status unavailable (API will be used): {e}", file=sys.stderr)
    
    # Get enriched device data from API
    api_devices = get_tailscale_devices_with_all_fields()
    if not api_devices:
        print("[WARNING] No devices found via API", file=sys.stderr)
        return []

    machines = []
    
    for dev in api_devices:
        try:
            if not dev.get('addresses'):
                continue
                
            full_name = dev.get('name', '')
            ip = dev['addresses'][0].split('/')[0] if dev.get('addresses') else ''
            device_id = dev.get('id', '')
            node_id = dev.get('nodeId', '')
            
            # IMPROVED: Better hostname parsing
            if full_name and '.' in full_name:
                base_name = full_name.split('.')[0]
            else:
                base_name = dev.get('hostname', 'Unknown')
            
            # Create unique display name
            if device_id:
                unique_suffix = device_id[-8:]
                display_name = f"{base_name}-{unique_suffix}"
            else:
                ip_last = ip.split('.')[-1] if ip else 'unknown'
                display_name = f"{base_name}-{ip_last}"
            
            # Merge with local status (real-time data)
            local_status = machines_by_ip.get(ip, {})
            
            # IMPROVED: Extract tags from device (for grouping)
            tags = dev.get('tags', [])
            
            # IMPROVED: Check authorization and key expiry status
            is_authorized = dev.get('authorized', False)
            key_expires = dev.get('expires', '')
            key_expiry_disabled = dev.get('keyExpiryDisabled', False)
            
            # IMPROVED: Check for subnet routes or exit node functionality
            is_exit_node = False
            is_subnet_router = False
            try:
                routes = get_device_routes(node_id, api_key) if api_key and node_id else {}
                enabled = routes.get('enabled', [])
                if enabled:
                    for route in enabled:
                        if route == '0.0.0.0/0' or route == '::/0':
                            is_exit_node = True
                        else:
                            is_subnet_router = True
            except:
                pass
            
            machines.append({
                'hostname': display_name,
                'ip': ip,
                'online': local_status.get('online', dev.get('connectedToControl', False)),
                'os': local_status.get('os', dev.get('os', 'Unknown')),
                'device_id': device_id,
                'node_id': node_id,
                'last_seen': local_status.get('last_seen', dev.get('lastSeen', '')),
                'authorized': is_authorized,
                'key_expires': key_expires,
                'key_expiry_disabled': key_expiry_disabled,
                'tags': tags,
                'is_exit_node': is_exit_node,
                'is_subnet_router': is_subnet_router,
                'machine_key': dev.get('machineKey', ''),
                'node_key': dev.get('nodeKey', ''),
                'is_external': dev.get('isExternal', False),
                'is_ephemeral': dev.get('isEphemeral', False),
                'created': dev.get('created', ''),
                'blocks_incoming': dev.get('blocksIncomingConnections', False),
                'client_version': local_status.get('client_version', dev.get('clientVersion', ''))
            })
        except Exception as e:
            print(f"[WARNING] Failed to process device {dev.get('id')}: {e}", file=sys.stderr)
            continue
    
    if not machines:
        print("[WARNING] No machines discovered", file=sys.stderr)
        return []
    
    # Sort: online first, then by hostname
    result = sorted(machines, key=lambda x: (not x['online'], x['hostname']))
    print(f"[INFO] Discovered {len(result)} machines", file=sys.stderr)
    return result




def get_tailscale_machines_local():
    """
    Fallback: Get machines from local Tailscale client.
    Used when API is unavailable.
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
                    'peer_id': peer_id,
                    'os': peer_data.get('OS', 'Unknown'),
                    'last_seen': peer_data.get('LastSeen', ''),
                    'authorized': True,  # Assume local is authorized
                    'tags': [],
                    'is_exit_node': False,
                    'is_subnet_router': False,
                    'created': '',
                    'key_expires': '',
                    'key_expiry_disabled': False
                })
        
        return sorted(machines, key=lambda x: (not x['online'], x['hostname']))
        
    except Exception as e:
        print(f"[ERROR] Local client error: {e}", file=sys.stderr)
        return []




# ============================================================================
# IMPROVED SEMAPHORE INVENTORY OUTPUT
# ============================================================================

def generate_semaphore_inventory():
    """
    Generate inventory in Semaphore-compatible format with enhanced grouping.
    
    Groups:
    - all: All discovered machines
    - online: Only online machines
    - offline: Only offline machines
    - authorized: Only authorized machines
    - unauthorized: Machines pending authorization
    - exit_nodes: Machines acting as exit nodes
    - subnet_routers: Machines acting as subnet routers
    - tag_*: Machines grouped by their Tailscale tags
    """
    machines = get_tailscale_machines_api()
    
    if not machines:
        machines = get_tailscale_machines_local()
    
    # Create groups
    inventory = {
        "ungrouped": {},
        "all": {"hosts": {}},
        "online": {"hosts": {}},
        "offline": {"hosts": {}},
        "authorized": {"hosts": {}},
        "unauthorized": {"hosts": {}},
        "exit_nodes": {"hosts": {}},
        "subnet_routers": {"hosts": {}},
        "_meta": {"hostvars": {}}
    }
    
    # Collect all tags for grouping
    all_tags = set()
    for machine in machines:
        all_tags.update(machine.get('tags', []))
    
    # Create tag groups
    for tag in all_tags:
        inventory[f"tag_{tag}"] = {"hosts": {}}
    
    # Add machines to appropriate groups
    for machine in machines:
        hostname = machine['hostname']
        ip = machine['ip']
        
        # Add to all group
        inventory["all"]["hosts"][hostname] = ip
        
        # Add to status groups
        if machine['online']:
            inventory["online"]["hosts"][hostname] = ip
        else:
            inventory["offline"]["hosts"][hostname] = ip
        
        # Add to authorization groups
        if machine['authorized']:
            inventory["authorized"]["hosts"][hostname] = ip
        else:
            inventory["unauthorized"]["hosts"][hostname] = ip
        
        # Add to special role groups
        if machine['is_exit_node']:
            inventory["exit_nodes"]["hosts"][hostname] = ip
        if machine['is_subnet_router']:
            inventory["subnet_routers"]["hosts"][hostname] = ip
        
        # Add to tag groups
        for tag in machine.get('tags', []):
            inventory[f"tag_{tag}"]["hosts"][hostname] = ip
        
        # Create hostvars with enriched device info
        hostvars = {
            "ansible_host": ip,
            "ansible_user": LINUX_USER,
            "ansible_password": LINUX_PASS,
            "ansible_connection": "ssh",
            "tailscale_ip": ip,
            "os": machine['os'],
            "status": "online" if machine['online'] else "offline",
            "authorized": machine['authorized'],
            "device_id": machine.get('device_id', ''),
            "node_id": machine.get('node_id', ''),
            "last_seen": machine.get('last_seen', ''),
            "tags": machine.get('tags', []),
            "is_exit_node": machine.get('is_exit_node', False),
            "is_subnet_router": machine.get('is_subnet_router', False),
            "key_expires": machine.get('key_expires', ''),
            "key_expiry_disabled": machine.get('key_expiry_disabled', False),
            "created": machine.get('created', ''),
            "blocks_incoming": machine.get('blocks_incoming', False),
            "client_version": machine.get('client_version', ''),
            "is_external": machine.get('is_external', False),
            "is_ephemeral": machine.get('is_ephemeral', False)
        }
        
        inventory["_meta"]["hostvars"][hostname] = hostvars
    
    return inventory


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--list":
        # Return inventory
        inventory = generate_semaphore_inventory()
        print(json.dumps(inventory, indent=2))
    elif len(sys.argv) == 3 and sys.argv[1] == "--host":
        # Return host variables
        inventory = generate_semaphore_inventory()
        host = sys.argv[2]
        hostvars = inventory["_meta"]["hostvars"].get(host, {})
        print(json.dumps(hostvars, indent=2))
    else:
        print("Usage: tailscale_dynamic_inventory.py --list | --host <hostname>")
        sys.exit(1)
