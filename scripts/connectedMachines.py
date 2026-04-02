import subprocess
import json

def get_tailscale_machines():
    try:
        # Ask the local Tailscale client for the network status
        result = subprocess.run(
            ['tailscale', 'status', '--json'], 
            capture_output=True, 
            text=True, 
            check=True
        )
        data = json.loads(result.stdout)
        
        machines = []
        
        peers = data.get('Peer', {})
        for peer_id, peer_data in peers.items():
            if peer_data.get('TailscaleIPs'):
                machines.append({
                    'hostname': peer_data.get('HostName'),
                    'ip': peer_data['TailscaleIPs'][0]
                })
                
        return machines
        
    except FileNotFoundError:
        print("Error: Tailscale CLI is not installed or not in your system PATH.")
        return []
    except subprocess.CalledProcessError as e:
        print(f"Error executing tailscale command. Is Tailscale running? {e}")
        return []
    except Exception as e:
        print(f"Unexpected error: {e}")
        return []

# --- THIS IS THE PART THAT ACTUALLY RUNS IT ---
if __name__ == "__main__":
    print("Checking Tailscale network... please wait.")
    machines = get_tailscale_machines()
    
    if machines:
        print(f"\nSuccess! Found {len(machines)} connected machines:")
        for machine in machines:
            print(f" - {machine['hostname']}: {machine['ip']}")
    else:
        print("\nNo machines found. Check the errors above if any were printed.")