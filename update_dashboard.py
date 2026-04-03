#!/usr/bin/env python3
"""Add setup panel to dashboard template"""

with open('scripts/web_machine_viewer.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the line with 'Deploy with Ansible' and insert setup before it
idx = content.find('Deploy with Ansible')
if idx == -1:
    print('Could not find Deploy with Ansible')
    exit(1)

# Back up to find the previous <div class="log-container">
prev_div_container = content.rfind('<div class="log-container">', 0, idx)
if prev_div_container == -1:
    print('Could not find log-container before Deploy with Ansible')
    exit(1)

setup_html = '''<div class="log-container">
    <h3>⚙️ Setup Ansible & Playbooks</h3>
    <p style="color: var(--color-text-muted); font-size: 12px; margin-bottom: 15px;">Prepare the target machine: install Ansible and copy playbooks to /tmp/ansible_deploy</p>
    
    <div style="display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap;">
        <button onclick="checkStatus()" class="action-btn" style="padding: 10px 20px; min-width: 140px;">🔍 Check Status</button>
        <button onclick="setupMachine()" class="action-btn" style="padding: 10px 20px; min-width: 140px;">📦 Copy & Install</button>
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

'''

new_content = content[:prev_div_container] + setup_html + content[prev_div_container:]

with open('scripts/web_machine_viewer.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print('✓ Setup section inserted successfully into dashboard template')
