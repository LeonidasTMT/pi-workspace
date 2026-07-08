#!/usr/bin/env python3
"""
AI Activity Watcher — parses session log to detect AI activity states.

Lines:
  toolCall name=edit → EDITING
  toolCall name=write → WRITING
  toolCall name=read → EXPLORING
  toolCall name=bash → WORKING
  thinking → THINKING
  user message → IDLE (waiting)
  no growth >2s → IDLE

Writes .pi-status/state for bubble to display.
Launch: python bubble/watcher.py
"""

import os, time, json

WORKSPACE = 'C:/Users/User/Documents/GitHub/pi-workspace'
STATE_FILE = os.path.join(WORKSPACE, '.pi-status', 'state')

SESSIONS_DIR = os.path.join(
    os.environ.get('USERPROFILE', ''),
    '.pi', 'agent', 'sessions'
)

IDLE_AFTER = 5.0  # seconds of no growth before marking IDLE (AI turns have pauses)
POLL = 0.2

# Classify assistant activity
TOOL_STATES = {
    'edit': 'EDITING',
    'write': 'WRITING',
    'read': 'EXPLORING',
    'bash': 'WORKING',
    'grep': 'EXPLORING',
    'find': 'EXPLORING',
}

def classify_line(line):
    """Return state from a session log line."""
    try:
        msg = json.loads(line.strip())
        role = msg.get('message', {}).get('role', '')
        content = msg.get('message', {}).get('content', [])
        
        if role == 'assistant':
            # Check for tool calls
            for c in content:
                if isinstance(c, dict) and c.get('type') == 'toolCall':
                    name = c.get('name', '')
                    return TOOL_STATES.get(name, 'WORKING')
            # Has thinking but no tools → thinking
            if any(c.get('type') == 'thinking' for c in content):
                return 'THINKING'
            # Just text → working
            return 'WORKING'
        elif role == 'user':
            return 'IDLE'
        elif role == 'toolResult':
            return 'WORKING'
    except (json.JSONDecodeError, KeyError):
        pass
    return None

def find_latest():
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

# Init
last_file = find_latest()
last_pos = 0
idle_since = time.time()
last_scan = time.time()
current_state = 'IDLE'

if last_file:
    try:
        last_pos = os.path.getsize(last_file)
    except OSError:
        pass

os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)

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
                    last_pos = os.path.getsize(last_file)
                except OSError:
                    pass

        if last_file:
            try:
                sz = os.path.getsize(last_file)
                if sz != last_pos:
                    # Only process complete lines (skip partials)
                    with open(last_file, 'rb') as f:
                        f.seek(last_pos)
                        raw = f.read(sz - last_pos)
                    
                    # Only process up to last newline to avoid partials
                    data = raw.decode('utf-8', errors='ignore')
                    lines = data.split('\n')
                    # Only process complete lines, leave last partial for next poll
                    last_partial = lines[-1] if lines else ''
                    last_pos += len(data.encode('utf-8')) - len(last_partial.encode('utf-8'))
                    
                    for line in lines[:-1]:  # skip incomplete last line
                        if line.strip():
                            s = classify_line(line)
                            if s:
                                current_state = s
                                idle_since = now
                                with open(STATE_FILE, 'w') as f:
                                    f.write(current_state)
            except Exception:
                pass

        # Auto-idle if no growth
        if (now - idle_since) > IDLE_AFTER and last_pos > 0:
            if current_state != 'IDLE':
                current_state = 'IDLE'
                with open(STATE_FILE, 'w') as f:
                    f.write('IDLE')

        time.sleep(POLL)
except KeyboardInterrupt:
    pass
finally:
    with open(STATE_FILE, 'w') as f:
        f.write('IDLE')
