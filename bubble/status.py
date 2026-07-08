#!/usr/bin/env python3
"""
Pi Status Bubble — always-on-top floating status + message bubble.

Polls .pi-status/state for current AI status.
Writes messages to .pi-status/input when I type.
Auto-expands when state=NEW (unread reply).

Usage: python bubble/status.py
"""

import sys
import os
import json
import time
import pathlib

# ── Config ──
WORKSPACE = os.environ.get('PI_WORKSPACE') or '/c/Users/User/Documents/GitHub/pi-workspace'
PI_STATUS = os.path.join(WORKSPACE, '.pi-status')
STATE_FILE = os.path.join(PI_STATUS, 'state')
INPUT_FILE = os.path.join(PI_STATUS, 'input')
RESPONSE_FILE = os.path.join(PI_STATUS, 'response')
HISTORY_FILE = os.path.join(PI_STATUS, 'history')

POSITION_FILE = os.path.join(
    os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
    'pi-bubble', 'position.json'
)

DEFAULT_POS = {'x': 1200, 'y': 20, 'w': 175, 'h': 30}
POLL_MS = 500
MAX_HISTORY_LINES = 10

# ── Color theme ──
THEME = {
    'bg':           '#1a1a2e',
    'fg':           '#e0e0e0',
    'bg_input':     '#16213e',
    'fg_input':     '#ffffff',
    'border':       '#333366',
    'state_IDLE':   '#555555',
    'state_WORKING':'#ffaa00',
    'state_DONE':   '#00cc66',
    'state_WAITING':'#4488ff',
    'state_NEW':    '#00cc66',
}

# ── Ensure dirs ──
os.makedirs(PI_STATUS, exist_ok=True)
os.makedirs(os.path.dirname(POSITION_FILE), exist_ok=True)

# ── Load/save position ──
def load_pos():
    try:
        with open(POSITION_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return DEFAULT_POS

def save_pos(pos):
    try:
        os.makedirs(os.path.dirname(POSITION_FILE), exist_ok=True)
        with open(POSITION_FILE, 'w') as f:
            json.dump(pos, f)
    except Exception:
        pass

def read_state():
    """Read .pi-status/state, return stripped string."""
    try:
        with open(STATE_FILE, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        return 'IDLE'
    except Exception:
        return 'IDLE'

def read_response():
    """Read last AI response."""
    try:
        with open(RESPONSE_FILE, 'r') as f:
            return f.read().strip()[:2000]
    except FileNotFoundError:
        return ''

def read_input():
    """Read what I typed."""
    try:
        with open(INPUT_FILE, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        return ''

def send_message(text):
    """Write message to .pi-status/input, set state=WAITING, log to history."""
    try:
        with open(INPUT_FILE, 'w', encoding='utf-8') as f:
            f.write(text)
        with open(STATE_FILE, 'w') as f:
            f.write('WAITING')
        # Append to history
        try:
            with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
                f.write(f'[IN {time.strftime("%H:%M:%S")}] {text}\n')
        except Exception:
            pass
        return True
    except Exception as e:
        print(f'Failed to send message: {e}', file=sys.stderr)
        return False

def get_last_response_preview():
    """Get a short preview of the last AI response."""
    response = read_response()
    if not response:
        return ''
    lines = response.split('\n')
    if len(lines) > 3:
        lines = lines[:3]
        lines.append('...')
    return '\n'.join(lines)

# ── Tkinter app ──
import tkinter as tk

class BubbleApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('pi')
        self.root.configure(bg=THEME['bg'])
        self.root.attributes('-topmost', True)
        self.root.overrideredirect(True)  # No title bar

        self.state = 'IDLE'
        self.expanded = False
        self.last_response_shown = ''
        self.drag_data = {'x': 0, 'y': 0}

        self._init_widgets()
        self._load_position()
        self._bind_drag()
        self._start_poll()

    def _init_widgets(self):
        """Build both collapsed and expanded UI."""
        # ── Status bar (always visible) ──
        self.status_frame = tk.Frame(self.root, bg=THEME['bg'])
        self.status_frame.pack(fill=tk.BOTH, ipadx=8, ipady=4)

        self.dot = tk.Label(self.root, text='●', fg=THEME['state_IDLE'],
                           bg=THEME['bg'], font=('Segoe UI', 10))
        self.dot.pack(side=tk.LEFT, padx=(2, 4))

        self.state_label = tk.Label(self.root, text='idle', fg=THEME['fg'],
                                    bg=THEME['bg'], font=('Segoe UI', 9))
        self.state_label.pack(side=tk.LEFT)

        # ── Expanded content (hidden by default) ──
        self.expanded_frame = tk.Frame(self.root, bg=THEME['bg'])
        self.expanded_frame.pack_forget()  # Hidden

        # Separator
        sep = tk.Frame(self.expanded_frame, bg=THEME['border'], height=1)
        sep.pack(fill=tk.X, padx=4, pady=(0, 4))

        # Response area (scrollable)
        self.resp_frame = tk.Frame(self.expanded_frame, bg=THEME['bg'],
                                   relief=tk.GROOVE, bd=1)
        self.resp_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        self.resp_scroll = tk.Scrollbar(self.resp_frame, orient=tk.VERTICAL,
                                        bg=THEME['bg'])
        self.resp_text = tk.Text(self.resp_frame, bg=THEME['bg_input'],
                                fg=THEME['fg_input'], font=('Consolas', 9),
                                wrap=tk.WORD, state=tk.DISABLED,
                                yscrollcommand=self.resp_scroll.set,
                                padx=6, pady=4)
        self.resp_scroll.config(command=self.resp_text.yview)
        self.resp_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.resp_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Input area
        self.input_frame = tk.Frame(self.expanded_frame, bg=THEME['bg'])
        self.input_frame.pack(fill=tk.X, padx=4, pady=(4, 4))

        self.input_var = tk.StringVar()
        self.input_entry = tk.Entry(self.input_frame, textvariable=self.input_var,
                                   bg=THEME['bg_input'], fg=THEME['fg_input'],
                                   insertbackground=THEME['fg'],
                                   font=('Consolas', 9), relief=tk.FLAT)
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        send_btn = tk.Button(self.input_frame, text='>', bg=THEME['border'],
                            fg=THEME['fg'], font=('Segoe UI', 10), width=3,
                            relief=tk.FLAT)
        send_btn.pack(side=tk.RIGHT)

        # Bindings
        self.status_frame.bind('<Button-1>', self._toggle_expand)
        self.expanded_frame.bind('<Button-1>', lambda e: None)  # Prevent double-toggle
        self.input_entry.bind('<Return>', self._send)
        send_btn.configure(command=self._send)
        self.root.bind('<FocusIn>', lambda e: self._focus_input)

        # Close handling
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        self.status_frame.bind('<Button-3>', self._exit)  # Right-click = exit

    def _bind_drag(self):
        """Make status frame draggable."""
        self.status_frame.bind('<Button-1>', self._on_drag_start)
        self.root.bind('<B1-Motion>', self._on_drag_motion)
        self.status_frame.bind('<ButtonRelease-1>', self._on_drag_end)
        self.expanded_frame.bind('<Button-1>', self._on_drag_start)
        self.expanded_frame.bind('<ButtonRelease-1>', self._on_drag_end)

    def _on_drag_start(self, event):
        """Start dragging (but don't toggle expand if dragging)."""
        if self.expanded and event.widget in (self.status_frame,):
            # Only drag from status bar
            self.drag_data = {'x': event.x_root, 'y': event.y_root,
                            'start_expand': self.expanded}
        elif not self.expanded:
            self.drag_data = {'x': event.x_root, 'y': event.y_root,
                            'start_expand': self.expanded}

    def _on_drag_motion(self, event):
        """Move window while dragging."""
        dx = event.x_root - self.drag_data.get('x', event.x_root)
        dy = event.y_root - self.drag_data.get('y', event.y_root)
        if abs(dx) > 3 or abs(dy) > 3:
            newx = self.root.winfo_x() + dx
            newy = self.root.winfo_y() + dy
            self.root.geometry(f'+{max(0, newx)}+{max(0, newy)}')
            self.drag_data['x'] = event.x_root
            self.drag_data['y'] = event.y_root

    def _on_drag_end(self, event):
        """Save position after dragging."""
        self._save_position()

    def _toggle_expand(self, event):
        """Toggle expanded/collapsed on click (not drag)."""
        if not self.expanded:
            self.expanded = True
            self.expanded_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=0)
            self.root.geometry(f'320x{320}')
            self._save_position()
            self._show_response()
        else:
            self._collapse()

    def _collapse(self):
        self.expanded = False
        self.expanded_frame.pack_forget()
        self.root.geometry(f'175x30')
        self._save_position()

    def _show_response(self):
        """Display last AI response in the expanded view."""
        state = self.state
        response = read_response()

        self.resp_text.configure(state=tk.NORMAL)
        self.resp_text.delete('1.0', tk.END)

        if state in ('WAITING', 'NEW'):
            my_input = read_input()
            if my_input:
                self.resp_text.insert(tk.END, f'You typed: {my_input}\n\n', 'input')
                self.resp_text.tag_config('input', foreground='#888888')

        if state == 'NEW' and response:
            self.resp_text.insert(tk.END, response, 'response')
            self.resp_text.tag_config('response', foreground='#00ff88')
            self.last_response_shown = response
        elif state == 'WAITING':
            self.resp_text.insert(tk.END, 'Waiting for response...', '#888888')
        else:
            self.resp_text.insert(tk.END, 'No response yet', '#555555')

        self.resp_text.configure(state=tk.DISABLED)
        self.resp_text.see(tk.END)

    def _send(self):
        """Send the message from input field."""
        text = self.input_var.get().strip()
        if not text:
            return
        if send_message(text):
            self.input_var.set('')
            # Update local state
            self.state = 'WAITING'
            self._update_visuals()
            self._show_response()
        self.input_entry.focus_set()

    def _focus_input(self, event):
        if self.expanded:
            self.input_entry.focus_set()

    def _poll_state(self):
        """Poll .pi-status/state and update UI."""
        new_state = read_state()

        if new_state != self.state:
            old = self.state
            self.state = new_state

            # Auto-expand on NEW (unread reply)
            if new_state == 'NEW' and not self.expanded:
                self.expanded = True
                self.expanded_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=0)
                self.root.geometry('320x320')
                self._show_response()

            # Auto-collapse from NEW→IDLE after reading
            if old == 'NEW' and new_state in ('DONE', 'IDLE'):
                self._collapse()

        self._update_visuals()
        self.root.after(POLL_MS, self._poll_state)

    def _update_visuals(self):
        """Update dot color and label based on current state."""
        state = self.state
        dot_color = THEME.get(f'state_{state}', THEME['state_IDLE'])

        self.dot.configure(fg=dot_color)

        labels = {
            'IDLE': 'idle',
            'WORKING': 'working',
            'DONE': 'done',
            'WAITING': 'waiting',
            'NEW': 'new message',
        }
        self.state_label.configure(text=labels.get(state, 'idle'))

        # Pulse animation for WORKING and WAITING
        if state in ('WORKING', 'WAITING'):
            self.dot.after(600, self._pulse)

    def _pulse(self):
        """Breathe animation for active states."""
        fg = self.dot.cget('fg')
        self.dot.configure(fg='#222222')
        self.root.after(300, lambda: self.dot.configure(fg=fg))
        if self.state in ('WORKING', 'WAITING'):
            self.root.after(900, self._pulse)

    def _load_position(self):
        """Load saved position."""
        pos = load_pos()
        x, y = pos.get('x', DEFAULT_POS['x']), pos.get('y', DEFAULT_POS['y'])
        self.root.geometry(f'175x30+{x}+{y}')

    def _save_position(self):
        """Save current position."""
        pos = {
            'x': self.root.winfo_x(),
            'y': self.root.winfo_y(),
            'w': self.root.winfo_width(),
            'h': self.root.winfo_height(),
        }
        save_pos(pos)

    def _start_poll(self):
        """Start the state polling loop."""
        self.root.after(POLL_MS, self._poll_state)

    def _on_close(self):
        """Minimize instead of close."""
        self._collapse()
        self.root.withdraw()  # Hide to tray
        # Re-show on any future event (poll loop brings it back briefly)
        # Actually, keep it hidden but running. Re-show after 2s then minimize again.
        self.root.after(2000, self._peek)

    def _peek(self):
        """Briefly show, then hide again."""
        self.root.deiconify()
        self.root.after(500, self._auto_hide)

    def _auto_hide(self):
        self.root.withdraw()
        self.root.after(3000, self._peek)

    def _exit(self, event=None):
        """Right-click to exit completely."""
        save_pos({'x': self.root.winfo_x(), 'y': self.root.winfo_y()})
        self.root.destroy()
        sys.exit(0)

    def run(self):
        self.root.after(0, lambda: self._update_visuals())
        self.root.mainloop()

# ── Main ──
if __name__ == '__main__':
    app = BubbleApp()
    app.run()
