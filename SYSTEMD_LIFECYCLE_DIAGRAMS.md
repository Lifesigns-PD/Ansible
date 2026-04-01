# Systemd Service Lifecycle & Control Flow

## Complete Service Lifecycle Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          SYSTEMD SERVICE LIFECYCLE                      │
└─────────────────────────────────────────────────────────────────────────┘

BEFORE DEPLOYMENT
─────────────────
Server is running
  └─ Orchestrator: not installed
  └─ MQTT: not installed

                           ↓ ansible-playbook deploy.yml

INSTALLATION PHASE (Ansible runs)
──────────────────────────────────
1. Prerequisites Role
   ├─ apt-get update
   ├─ apt-get install [packages]
   ├─ useradd orcservice
   └─ mkdir /opt/orchestrator

2. MQTT Role
   ├─ apt-get install mosquitto
   ├─ Deploy /etc/mosquitto/conf.d/orchestrator.conf
   ├─ systemctl daemon-reload
   ├─ systemctl enable mosquitto
   └─ systemctl start mosquitto
                              ↓
                    mosquitto RUNNING
                    └─ PID: 1234
                    └─ Port 1883 listening

3. Orchestrator Role
   ├─ Copy /opt/orchestrator/bin/go-ble-orchestrator
   ├─ Copy /opt/orchestrator/frontend/
   ├─ Template /opt/orchestrator/config/config.json
   ├─ Deploy /etc/systemd/system/go-ble-orchestrator.service
   ├─ systemctl daemon-reload
   ├─ systemctl enable go-ble-orchestrator
   └─ systemctl start go-ble-orchestrator
                              ↓
               go-ble-orchestrator RUNNING
               └─ PID: 2500
               └─ Port 8083 listening
               └─ Depends on mosquitto

RUNNING STATE (Normal Operations)
──────────────────────────────────
systemd actively monitors:
  ├─ go-ble-orchestrator.service
  │  ├─ PID: 2500
  │  ├─ Memory: 45M
  │  ├─ CPU: 0.1%
  │  ├─ Health: OK
  │  ├─ Auto-restart: on-failure (RestartSec=5)
  │  └─ Restart count: 0
  │
  └─ mosquitto.service
     ├─ PID: 1234
     ├─ Memory: 1.2M
     ├─ CPU: 0%
     ├─ Health: OK
     ├─ Auto-restart: always
     └─ Restart count: 0

Status: ACTIVE ✓


CRASH SCENARIO
──────────────
Timestamp: 2:45:00 AM
  Memory leak in orchestrator
    ↓ Process uses 4GB RAM
    ↓ Kernel OOM killer triggers
    ↓ Process terminated (signal 9)

                              ↓ systemd.service [Restart=on-failure]

2:45:00 systemd detects crash
        ├─ ActiveState: failed
        ├─ Result: signal
        ├─ Check Restart policy
        └─ Restart: YES

2:45:00 Log to journalctl:
        "Main process exited, code=killed, status=9/KILL"

2:45:00 Start RestartSec timer:
        └─ Wait 5 seconds

2:45:05 Timer expires
        └─ Respawn process

2:45:05 New orchestrator process launched:
        ├─ ExecStart: /opt/orchestrator/bin/go-ble-orchestrator \
                      -config /opt/orchestrator/config/config.json
        ├─ User: orcservice
        ├─ Group: orcservice
        ├─ WorkingDirectory: /opt/orchestrator
        ├─ New PID: 2520
        └─ Monitoring: resumed

2:45:06 Status: ACTIVE ✓ (back up within 1 second)

Long-term
──────────
$ journalctl -u go-ble-orchestrator
  Shows crash event and auto-restart
  Restart count: 1
  Can investigate root cause


MANUAL STOP
───────────
$ systemctl stop go-ble-orchestrator

           systemd sends SIGTERM to PID 2520
                         ↓
           Process receives signal
                         ↓
           Graceful shutdown (15s timeout)
                         ↓
           If still running: SIGKILL
                         ↓
           Status: inactive (dead)
           └─ ActiveState: inactive
           └─ No PID
           └─ Not monitoring

Note: No auto-restart while stopped
      (Restart= only applies to unexpected failures)


MANUAL START
────────────
$ systemctl start go-ble-orchestrator

           systemd reads .service file
                         ↓
           Check dependency: Wants=mosquitto.service
                         ↓
           Verify mosquitto already running ✓
                         ↓
           Execute: ExecStart command
                         ↓
           New PID: 2540
                         ↓
           Connect to MQTT
                         ↓
           Start accepting HTTP requests (port 8083)
                         ↓
           Status: active (running)


RESTART
───────
$ systemctl restart go-ble-orchestrator

           1. Send SIGTERM to current PID
           2. Wait for process to exit
           3. (Restart= not triggered, it's manual)
           4. Execute ExecStart again
           5. New PID assigned
           6. Service back to active (running)

           Equivalent to: stop && start
           Time: ~1-2 seconds total


SYSTEM SHUTDOWN
───────────────
$ sudo shutdown -h now

           systemd initiates shutdown sequence
                         ↓
           [Reverse dependency order]
           1. Stop go-ble-orchestrator
              ├─ SIGTERM
              └─ Wait 15 seconds
           2. Stop mosquitto
              ├─ SIGTERM
              └─ Wait 15 seconds
           3. Unmount filesystems
           4. Power off

           Result: Clean shutdown, no data corruption


SYSTEM REBOOT
──────────────
$ sudo reboot

           1. systemd initiates shutdown (see above)
           2. After all services stopped
           3. Kernel reboots
           4. BIOS/UEFI loads Linux
           5. systemd starts (PID 1)
           6. Reads /etc/systemd/system/multi-user.target.wants/
              ├─ go-ble-orchestrator.service (enabled=yes)
              └─ mosquitto.service (enabled=yes)
           7. Launches mosquitto first
              └─ Because orchestrator has: After=mosquitto.service
           8. Launches orchestrator
           9. Services running
           10. System ready


STATUS PROGRESSION
──────────────────

active (running)
  ↓ systemctl stop
inactive (dead)
  ↓ systemctl start
active (running)
  ↓ process crashes
active (failed)
  ↓ auto-restart (RestartSec=5)
active (running)
  ↓ systemctl disable (removes boot symlink)
active (running)
  ↓ reboot
inactive (dead)
  └─ Won't auto-start on boot (disabled=yes)


DEPENDENCY RESOLUTION
─────────────────────

go-ble-orchestrator.service:
  After=network.target mosquitto.service
  Wants=mosquitto.service
  Requires=nothing

Boot sequence:
  1. network.target starts (all networking ready)
  2. mosquitto.service starts
     └─ PID 1234 running
  3. go-ble-orchestrator.service starts
     └─ PID 2500 running
     └─ Can connect to MQTT immediately

If mosquitto crashes:
  ├─ Restart=always on mosquitto.service
  ├─ mosquitto auto-restarts after 100ms
  ├─ go-ble-orchestrator still running (Wants= is soft)
  ├─ Orchestrator reconnects to MQTT when ready
  └─ No cascade failure


RESOURCE MANAGEMENT
────────────────────

systemd tracks per-service:
  ├─ Memory (RSS, VSZ)
  ├─ CPU time (user + system)
  ├─ File descriptors (open files)
  ├─ Process count
  ├─ Threads created
  └─ Resource limits (LimitNOFILE, LimitNPROC, etc.)

From service file:
  LimitNOFILE=65536  (max open files per process)
  LimitNPROC=4096    (max processes per user)

View live stats:
  $ systemctl status go-ble-orchestrator
    Shows: Tasks, Memory, CPU

Monitor over time:
  $ systemd-cgtop
    Shows resource usage of all services


ERROR STATES
─────────────

If start fails (bad config):
  Result: result-code=exit-code=1
  Action: Doesn't auto-restart (ExecStart failed, not crash)
  Fix: Correct config, then systemctl start

If start times out:
  Result: result-code=timeout
  Action: Kill process, mark failed
  Fix: Check why service hangs (MQTT unavailable?)

If dependency fails:
  Result: Wants=mosquitto says "nice to have"
       So orchestrator starts alone (but can't connect to MQTT)
  Fix: Check mosquitto.service status

If restart limit exceeded:
  Restart=on-failure with StartLimitBurst=5
  After 5 restarts in 10 seconds: Stop trying
  Result: StartLimitAction=reboot or StartLimitAction=none
  Check: systemctl reset-failed service_name


INTERACTION WITH ANSIBLE
─────────────────────────

Ansible tasks that use systemd:
  ├─ systemd_service: start, stop, restart, reload
  ├─ systemd module: enable, disable, mask, unmask
  ├─ service module: compatible module for legacy
  └─ shell module: systemctl commands directly

Idempotency:
  ✓ systemd module: Checks current state first
                    Only acts if state differs
  ✓ Re-run deploy.yml safely
                    Won't restart if already active
  ✓ Config changes trigger reload/restart via notify/handlers

Handlers (post-task actions):
  config.json changes
    ├─ notify: restart orchestrator
    │  └─ Goes to handlers section
    │  └─ Runs at end of play
    │  └─ systemctl restart go-ble-orchestrator


STATE AFTER EACH PHASE
──────────────────────

After prerequisites:
  ├─ Packages installed ✓
  ├─ User orcservice exists ✓
  ├─ Directories created ✓
  └─ Services: NOT running yet

After MQTT role:
  ├─ Mosquitto installed ✓
  ├─ Mosquitto configured ✓
  ├─ Mosquitto running ✓
  ├─ Port 1883 listening ✓
  └─ Orchestrator: NOT running yet

After orchestrator role:
  ├─ Binary copied ✓
  ├─ Config generated ✓
  ├─ Service file created ✓
  ├─ Service enabled (boot) ✓
  └─ Service running ✓

Final:
  ├─ Dashboard accessible ✓
  ├─ MQTT broker listening ✓
  ├─ Both services reboot-persistent ✓
  └─ All logs in journalctl ✓

```

---

## Command Reference: Systemd vs Traditional Init

```
TASK                  SYSTEMD              OLD SYSVINIT
─────────────────────────────────────────────────────────
Start service         systemctl start      /etc/init.d/service start
                      service_name

Stop service          systemctl stop       /etc/init.d/service stop
                      service_name

Restart service       systemctl restart    /etc/init.d/service restart
                      service_name

Reload config         systemctl reload     /etc/init.d/service reload
                      service_name

Check status          systemctl status     /etc/init.d/service status
                      service_name

Enable on boot        systemctl enable     update-rc.d service defaults
                      service_name

Disable on boot       systemctl disable    update-rc.d service remove
                      service_name

View logs             journalctl -u name   tail -f /var/log/app.log

View all services     systemctl list-unit  service --status-all
                      -files

View failed services  systemctl --failed   check /var/log/syslog

Reload daemon         systemctl            (not needed)
                      daemon-reload

See service file      systemctl cat        cat /etc/init.d/service
                      service_name
```

---

## Systemd Service File Structure (Your orchestrator.service)

```
[Unit] Section
──────────────
Description=BLE Orchestrator Service
  └─ Human-readable name

After=network.target mosquitto.service
  └─ Start AFTER these targets/services
  └─ Ensures dependencies are ready first

Wants=mosquitto.service
  └─ Start this service too (soft dependency)
  └─ If mosquitto fails, still start orchestrator
  └─ Unlike: Requires=mosquitto.service (would fail us too)

Documentation=man:systemd.unit(5)
  └─ Where to find help for this unit

PartOf=multi-user.target
  └─ If target stops, stop this service


[Service] Section
─────────────────
Type=simple
  └─ Service runs in foreground (doesn't fork)
  └─ systemd tracks the main process

User=orcservice
  └─ Run as this user (not root)
  └─ orcservice has limited permissions (security)

Group=orcservice
  └─ Run with this group

WorkingDirectory=/opt/orchestrator
  └─ cd /opt/orchestrator before running binary
  └─ App can reference files relative to this

ExecStart=/opt/orchestrator/bin/go-ble-orchestrator \
          -config /opt/orchestrator/config/config.json
  └─ Command to run when starting service
  └─ Arguments passed: -config flag with path

ExecReload=
  └─ (not defined here)
  └─ Would define how to reload without restart
  └─ Not needed for go app

Restart=on-failure
  └─ Auto-restart if process exits with non-zero code
  └─ Doesn't restart on manual stop
  └─ Doesn't restart on SIGTERM

RestartSec=5
  └─ Wait 5 seconds before restarting after failure

StandardOutput=journal
  └─ Capture stdout to systemd journal

StandardError=journal
  └─ Capture stderr to systemd journal

SyslogIdentifier=go-ble-orchestrator
  └─ Tag in logs to identify this service

NoNewPrivileges=true
  └─ Process can't gain new privileges (security)
  └─ Prevents privilege escalation

ProtectSystem=strict
  └─ Make /usr, /boot, /etc read-only
  └─ Process can't modify system files (security)

ProtectHome=yes
  └─ Make /root, /home inaccessible to process
  └─ Process can't access user home directories

ReadWritePaths=/opt/orchestrator
  └─ But allow writes to /opt/orchestrator
  └─ Where app stores its data


[Install] Section
──────────────────
WantedBy=multi-user.target
  └─ Boot target to include this service
  └─ multi-user.target = system boots to multi-user mode
  └─ Means: systemctl enable creates symlink to this target

When you run:
  systemctl enable go-ble-orchestrator
  ↓
  Creates symlink:
  /etc/systemd/system/multi-user.target.wants/go-ble-orchestrator.service
  → /etc/systemd/system/go-ble-orchestrator.service
  ↓
  On next boot:
  systemd loads multi-user.target
    ↓ reads multi-user.target.wants/
    ↓ finds go-ble-orchestrator.service symlink
    ↓ starts go-ble-orchestrator
```

---

## Ansible → Systemd Workflow Summary

```
┌─────────────────────────────────────────────┐
│ Step 1: Ansible Generates .service File    │
│ (from roles/orchestrator/templates/)        │
└────────────────┬────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│ Step 2: Populate Template Variables         │
│ {{ app_user }} → orcservice                 │
│ {{ app_home }} → /opt/orchestrator          │
│ {{ service_name }} → go-ble-orchestrator    │
└────────────────┬────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│ Step 3: Deploy to Target                    │
│ /etc/systemd/system/                        │
│   go-ble-orchestrator.service               │
└────────────────┬────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│ Step 4: Reload Systemd Daemon               │
│ $ systemctl daemon-reload                   │
│ (reads new .service files)                  │
└────────────────┬────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│ Step 5: Enable for Boot                     │
│ $ systemctl enable go-ble-orchestrator      │
│ (creates /etc/systemd/system/               │
│  multi-user.target.wants/symlink)          │
└────────────────┬────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│ Step 6: Start Service                       │
│ $ systemctl start go-ble-orchestrator       │
│ (launches binary as orcservice user)        │
└────────────────┬────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│ Step 7: Wait for Health                     │
│ curl http://localhost:8083/health           │
│ (verify app is ready)                       │
└────────────────┬────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│ RUNNING                                     │
│ systemd monitors service indefinitely       │
│ ├─ Tracks PID                               │
│ ├─ Auto-restarts on crash                   │
│ ├─ Logs to journalctl                       │
│ ├─ Survives reboots (enabled=yes)           │
│ └─ Ready for manual control                 │
└─────────────────────────────────────────────┘
```

