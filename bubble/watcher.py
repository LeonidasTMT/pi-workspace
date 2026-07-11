#!/usr/bin/env python3
"""
AI Activity Watcher — polls session .jsonl for AI activity.

Entry types:
  message (role=user)          → IDLE
  message (role=assistant)     → classify by content type
  message (role=toolResult)    → keep previous state
  compaction                   → COMPACTING
  thinking_level_change        → THINKING
  model_change                 → THINKING
  no growth >15s               → IDLE

Writes .pi-status/state, .pi-status/last-response, .pi-status/last-action
for the bubble.
"""

import os
import time
import json

WORKSPACE = 'C:/Users/User/Documents/GitHub/pi-workspace'
STATE_FILE = os.path.join(WORKSPACE, '.pi-status', 'state')
LAST_RESPONSE_FILE = os.path.join(WORKSPACE, '.pi-status', 'last-response')
LAST_ACTION_FILE = os.path.join(WORKSPACE, '.pi-status', 'last-action')
LOG_FILE = os.path.join(WORKSPACE, '.pi-status', 'watcher.log')

SESSIONS_DIR = os.path.join(
    os.environ.get('USERPROFILE', ''),
    '.pi', 'agent', 'sessions'
)

IDLE_AFTER = 15.0
POLL_MS = 200
SESSION_SCAN_INTERVAL = 10

TOOL_STATES = {
    'edit': 'EDITING',
    'write': 'WRITING',
    'read': 'EXPLORING',
    'bash': 'WORKING',
    'grep': 'EXPLORING',
    'find': 'EXPLORING',
}

TOOL_LABELS = {
    'edit': 'editing',
    'write': 'writing',
    'read': 'reading',
    'bash': 'running',
    'grep': 'searching',
    'find': 'searching',
}


def extract_text(content):
    """Extract readable text from assistant content array."""
    parts = []
    for c in content:
        if isinstance(c, dict) and c.get('type') == 'text':
            parts.append(c.get('text', ''))
    return ' '.join(parts).strip() if parts else None


def seed_from_history(filepath):
    """On startup, scan the tail of the session for the last assistant response."""
    try:
        sz = os.path.getsize(filepath)
        if sz <= 0:
            return
        with open(filepath, 'rb') as f:
            # Read last ~50KB
            offset = max(0, sz - 50000)
            f.seek(offset)
            chunk = f.read().decode('utf-8', errors='replace')
        # Scan backwards for last assistant text response
        for line in reversed(chunk.split('\n')):
            line = line.strip()
            if not line:
                continue
            st, act, resp = classify_entry(line)
            if resp:
                write_last_response(resp)
                write_last_action(act or 'responding')
                return
    except Exception:
        pass


def classify_entry(raw_line):
    """Return (state, action_text, response_text) from a session log line."""
    try:
        entry = json.loads(raw_line.strip())
    except (json.JSONDecodeError, ValueError):
        return None, None, None

    entry_type = entry.get('type')
    if entry_type == 'compaction':
        return 'COMPACTING', 'compacting history', None
    if entry_type == 'thinking_level_change':
        return 'THINKING', 'changing thinking level', None
    if entry_type == 'model_change':
        return 'THINKING', 'switching model', None
    if entry_type in ('session',):
        return None, None, None

    msg = entry.get('message')
    if not msg or not isinstance(msg, dict):
        return None, None, None

    role = msg.get('role')
    content = msg.get('content')
    if not content or not isinstance(content, list):
        return None, None, None

    if role == 'user':
        return 'IDLE', None, None

    if role == 'assistant':
        text = extract_text(content)
        for c in content:
            if isinstance(c, dict) and c.get('type') == 'toolCall':
                name = c.get('name', '')
                state = TOOL_STATES.get(name, 'WORKING')
                action = f'{TOOL_LABELS.get(name, "working")} ({name})'
                return state, action, text
        if any(isinstance(c, dict) and c.get('type') == 'thinking' for c in content):
            return 'THINKING', 'thinking', text
        return 'WORKING', 'responding', text

    if role == 'toolResult':
        return None, None, None

    return None, None, None


def find_latest_session():
    """Find the most recently modified .jsonl session file."""
    best_path = None
    best_mtime = 0
    try:
        for root, _dirs, files in os.walk(SESSIONS_DIR):
            for fname in files:
                if fname.endswith('.jsonl'):
                    full = os.path.join(root, fname)
                    try:
                        mtime = os.path.getmtime(full)
                        if mtime > best_mtime:
                            best_mtime = mtime
                            best_path = full
                    except OSError:
                        pass
    except Exception:
        pass
    return best_path


def log(msg):
    try:
        ts = time.strftime('%H:%M:%S')
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f'{ts} {msg}\n')
    except Exception:
        pass


def write_state(state):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            f.write(state)
            f.flush()
            os.fsync(f.fileno())
        return True
    except Exception as e:
        log(f'write_state failed: {e}')
        return False


def write_last_response(text):
    try:
        truncated = text[:500] + ('...' if len(text) > 500 else '')
        with open(LAST_RESPONSE_FILE, 'w', encoding='utf-8') as f:
            f.write(truncated)
    except Exception:
        pass


def write_last_action(text):
    try:
        with open(LAST_ACTION_FILE, 'w', encoding='utf-8') as f:
            f.write(text)
    except Exception:
        pass


def main():
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)

    current_file = find_latest_session()
    last_pos = 0
    if current_file:
        try:
            last_pos = os.path.getsize(current_file)
        except OSError:
            last_pos = 0

    current_state = 'IDLE'
    idle_since = time.time()
    last_scan = time.time()

    log(f'Watcher started, file={current_file}, pos={last_pos}')
    write_state('IDLE')

    # Seed last-response from history on first start
    if current_file:
        seed_from_history(current_file)

    while True:
        now = time.time()

        # Periodic session file scan
        if now - last_scan > SESSION_SCAN_INTERVAL:
            last_scan = now
            new_file = find_latest_session()
            if new_file and new_file != current_file:
                log(f'Switched to new session: {new_file}')
                current_file = new_file
                try:
                    last_pos = os.path.getsize(current_file)
                except OSError:
                    last_pos = 0

        if current_file:
            try:
                sz = os.path.getsize(current_file)
                if sz > last_pos and sz > 0:
                    try:
                        with open(current_file, 'rb') as f:
                            f.seek(last_pos)
                            raw = f.read(sz - last_pos)
                    except (OSError, PermissionError):
                        time.sleep(POLL_MS / 1000.0)
                        continue

                    # Only process complete lines
                    text_decoded = raw.decode('utf-8', errors='replace')
                    newline_idx = text_decoded.rfind('\n')
                    if newline_idx >= 0:
                        complete = text_decoded[:newline_idx]
                        for line in complete.split('\n'):
                            line = line.strip()
                            if not line:
                                continue
                            state, action, response = classify_entry(line)
                            if state:
                                current_state = state
                                idle_since = now
                                write_state(state)
                            if action:
                                write_last_action(action)
                            if response:
                                write_last_response(response)
                        last_pos += newline_idx + 1
                    else:
                        # Entire chunk is one incomplete line — wait for more data
                        pass
                    # Sanity: don't go past actual file size
                    if last_pos > os.path.getsize(current_file):
                        last_pos = os.path.getsize(current_file)

            except Exception as e:
                log(f'Error reading file: {e}')

        # Auto-idle: file hasn't grown in IDLE_AFTER seconds
        if now - idle_since > IDLE_AFTER and current_state != 'IDLE':
            log(f'Going IDLE after {int(now - idle_since)}s of no growth')
            current_state = 'IDLE'
            write_state('IDLE')

        time.sleep(POLL_MS / 1000.0)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        write_state('IDLE')
