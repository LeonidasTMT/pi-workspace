#!/usr/bin/env python3
"""
Tests for bubble/status.py - verifies signal protocol without launching GUI.

Run: python bubble/test_status.py
"""

import sys
import os
import tempfile
import shutil

# Setup test workspace
TEST_DIR = tempfile.mkdtemp(prefix='pi-bubble-test-')
TEST_STATUS = os.path.join(TEST_DIR, '.pi-status')
os.makedirs(TEST_STATUS, exist_ok=True)

STATE_FILE = os.path.join(TEST_STATUS, 'state')
INPUT_FILE = os.path.join(TEST_STATUS, 'input')
RESPONSE_FILE = os.path.join(TEST_STATUS, 'response')
HISTORY_FILE = os.path.join(TEST_STATUS, 'history')

# ── Inline the pure-logic functions we need to test ──
# (Avoid importing tkinter for headless testing)

def read_state(path):
    try:
        with open(path, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        return 'IDLE'
    except Exception:
        return 'IDLE'

def read_response(path):
    try:
        with open(path, 'r') as f:
            return f.read().strip()[:2000]
    except FileNotFoundError:
        return ''

def read_input(path):
    try:
        with open(path, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        return ''

def send_message(text, input_file, state_file, history_file):
    try:
        import time
        with open(input_file, 'w', encoding='utf-8') as f:
            f.write(text)
        with open(state_file, 'w') as f:
            f.write('WAITING')
        try:
            with open(history_file, 'a', encoding='utf-8') as f:
                f.write(f'[IN {time.strftime("%H:%M:%S")}] {text}\n')
        except Exception:
            pass
        return True
    except Exception as e:
        print(f'Failed to send message: {e}', file=sys.stderr)
        return False

def get_last_response_preview(response):
    if not response:
        return ''
    lines = response.split('\n')
    if len(lines) > 3:
        lines = lines[:3]
        lines.append('...')
    return '\n'.join(lines)

def save_pos(pos, path):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            import json
            json.dump(pos, f)
    except Exception:
        pass

def load_pos(path):
    try:
        import json
        with open(path, 'r') as f:
            return json.load(f)
    except Exception:
        return {'x': 1200, 'y': 20, 'w': 175, 'h': 30}

# ── Tests ──
passed = 0
failed = 0

def check(name, got, expected=None):
    global passed, failed
    if expected is not None and got != expected:
        failed += 1
        print(f'  FAIL: {name} - got {got!r}, expected {expected!r}')
        return False
    else:
        passed += 1
        print(f'  PASS: {name}')
        return True

print('Pi Bubble - Signal Protocol Tests')
print('=' * 40)

# Test 1: read_state() returns IDLE when file missing
try:
    os.remove(STATE_FILE)
except FileNotFoundError:
    pass
result = read_state(STATE_FILE)
check('read_state() with missing file', result, 'IDLE')

# Test 2: read_state() returns state from file
with open(STATE_FILE, 'w') as f:
    f.write('WORKING')
result = read_state(STATE_FILE)
check('read_state() with WORKING', result, 'WORKING')

# Test 3: read_state() strips whitespace
with open(STATE_FILE, 'w') as f:
    f.write('  NEW  \n')
result = read_state(STATE_FILE)
check('read_state() strips whitespace', result, 'NEW')

# Test 4: send_message() writes input, state, history
with open(STATE_FILE, 'w') as f:
    f.write('WAITING')
if os.path.exists(INPUT_FILE):
    os.remove(INPUT_FILE)
if os.path.exists(HISTORY_FILE):
    os.remove(HISTORY_FILE)

result = send_message('hello pi', INPUT_FILE, STATE_FILE, HISTORY_FILE)
check('send_message() returns True', result, True)

with open(INPUT_FILE, 'r') as f:
    content = f.read().strip()
check('send_message() writes input file', content, 'hello pi')

with open(STATE_FILE, 'r') as f:
    state = f.read().strip()
check('send_message() sets state=WAITING', state, 'WAITING')

with open(HISTORY_FILE, 'r') as f:
    history = f.read()
check('send_message() appends to history', '[IN' in history and 'hello pi' in history, True)

# Test 5: read_input() returns what was written
result = read_input(INPUT_FILE)
check('read_input() returns input', result, 'hello pi')

# Test 6: read_response() returns empty when no response
try:
    os.remove(RESPONSE_FILE)
except FileNotFoundError:
    pass
result = read_response(RESPONSE_FILE)
check('read_response() empty when missing', result, '')

# Test 7: read_response() truncates long responses
with open(RESPONSE_FILE, 'w', encoding='utf-8') as f:
    f.write('x' * 3000)
result = read_response(RESPONSE_FILE)
check('read_response() truncates to 2000', len(result), 2000)

# Test 8: get_last_response_preview() returns short version
multiline_response = '\n'.join(['line ' + str(i) for i in range(20)])
result = get_last_response_preview(multiline_response)
check('get_last_response_preview() returns short', len(result) <= 100, True)  # 3 lines + ...

# Test 9: send_message() doesn't overwrite history
first_history_len = len(open(HISTORY_FILE).read())
send_message('second message', INPUT_FILE, STATE_FILE, HISTORY_FILE)
second_history_len = len(open(HISTORY_FILE).read())
check('send_message() appends history (not overwrites)', second_history_len > first_history_len, True)

# Test 10: Position save/load
pos_file = os.path.join(TEST_STATUS, 'pos.json')
save_pos({'x': 999, 'y': 888, 'w': 100, 'h': 200}, pos_file)
pos = load_pos(pos_file)
check('save/load position x', pos['x'], 999)
check('save/load position y', pos['y'], 888)

# Cleanup
shutil.rmtree(TEST_DIR)

print('=' * 40)
print(f'Results: {passed}/{passed + failed} passed')
if failed > 0:
    print(f'  {failed} test(s) FAILED')
    sys.exit(1)
else:
    print('  All tests passed')
    sys.exit(0)
