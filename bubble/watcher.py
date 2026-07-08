#!/usr/bin/env python3
"""
AI Activity Watcher — detects model turns via session log growth.

Polls latest session .jsonl size every 500ms.
File growing → AI active (THINKING)
Stopped growing >2s → AI idle (IDLE)

Writes .pi-status/state for bubble to display.
Launch: python bubble/watcher.py
"""

import os, time, sys, glob

WORKSPACE = 'C:/Users/User/Documents/GitHub/pi-workspace'
STATE_FILE = os.path.join(WORKSPACE, '.pi-status', 'state')

SESSIONS_DIR = os.path.join(
    os.environ.get('USERPROFILE', ''),
    '.pi', 'agent', 'sessions'
)

IDLE_AFTER = 2.0  # seconds of no growth before marking IDLE
POLL = 0.5        # polling interval

last_file = None
last_size = 0
idle_since = time.time()
last_scan = time.time()

def find_latest():
    """Find the most recently modified session .jsonl file."""
    try:
        all_jsonl = []
        for root, _dirs, files in os.walk(SESSIONS_DIR):
            for f in files:
                if f.endswith('.jsonl'):
                    path = os.path.join(root, f)
                    try:
                        all_jsonl.append((path, os.path.getmtime(path)))
                    except OSError:
                        pass
        if all_jsonl:
            all_jsonl.sort(key=lambda x: x[1], reverse=True)
            return all_jsonl[0][0]
    except Exception:
        pass
    return None

# Find initial file
last_file = find_latest()
if last_file:
    try:
        last_size = os.path.getsize(last_file)
    except OSError:
        pass

os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)

# Start idle
with open(STATE_FILE, 'w') as f:
    f.write('IDLE')

try:
    while True:
        now = time.time()

        # Re-scan for new session every 15s
        if now - last_scan > 15:
            last_scan = now
            new = find_latest()
            if new and last_file != new:
                last_file = new
                try:
                    last_size = os.path.getsize(last_file)
                except OSError:
                    pass

        if last_file:
            try:
                sz = os.path.getsize(last_file)
                if sz != last_size:
                    last_size = sz
                    idle_since = now
                    with open(STATE_FILE, 'w') as f:
                        f.write('THINKING')
                elif (now - idle_since) > IDLE_AFTER and last_size > 0:
                    with open(STATE_FILE, 'w') as f:
                        f.write('IDLE')
            except OSError:
                pass

        time.sleep(POLL)
except KeyboardInterrupt:
    pass
finally:
    with open(STATE_FILE, 'w') as f:
        f.write('IDLE')
