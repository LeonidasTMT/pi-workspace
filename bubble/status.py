#!/usr/bin/env python3
"""
Pi Status Bubble — always-on-top floating status + message bubble.

Auto-launched via ~/.bashrc.
Polls .pi-status/state every 200ms.
Drag to move. Click to expand/collapse.
Type + Enter to send messages. Right-click to exit.

Launch: python bubble/status.py
"""

import sys, os, json, time

# ── Paths ──
_WORKSPACE = os.environ.get('PI_WORKSPACE', '')
if not _WORKSPACE or not os.path.exists(_WORKSPACE):
    _WORKSPACE = 'C:/Users/User/Documents/GitHub/pi-workspace'
WORKSPACE = _WORKSPACE

PI_STATUS = os.path.join(WORKSPACE, '.pi-status')
STATE_FILE = os.path.join(PI_STATUS, 'state')
INPUT_FILE = os.path.join(PI_STATUS, 'input')
RESPONSE_FILE = os.path.join(PI_STATUS, 'response')
HISTORY_FILE = os.path.join(PI_STATUS, 'history')
POSITION_FILE = os.path.join(
    os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
    'pi-bubble', 'position.json'
)
os.makedirs(PI_STATUS, exist_ok=True)

# ── Theme ──
THEME = {
    'bg':        '#1e1e2e',
    'fg':        '#cdd6f4',
    'fg_dim':    '#6c7086',
    'border':    '#313244',
    'bg_input':  '#181825',
    'idle':      '#6c7086',
    'working':   '#f9e24c',
    'done':      '#a6e3a1',
    'waiting':   '#89b4fa',
    'new':       '#a6e3a1',
}

# ── File I/O ──
def read_state():
    try: return open(STATE_FILE).read().strip()
    except: return 'IDLE'

def read_response():
    try: return open(RESPONSE_FILE, encoding='utf-8').read().strip()[:2000]
    except: return ''

def read_input():
    try: return open(INPUT_FILE, encoding='utf-8').read().strip()
    except: return ''

def send_message(text):
    try:
        with open(INPUT_FILE, 'w', encoding='utf-8') as f: f.write(text)
        with open(STATE_FILE, 'w') as f: f.write('WAITING')
        with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
            f.write(f'[IN {time.strftime("%H:%M:%S")}] {text}\n')
    except Exception as e:
        print(f'Send failed: {e}', file=sys.stderr)
        return False
    return True

def load_pos():
    try: return json.load(open(POSITION_FILE))
    except: return {}

def save_pos(app):
    try:
        os.makedirs(os.path.dirname(POSITION_FILE), exist_ok=True)
        json.dump({'x': app.root.winfo_x(), 'y': app.root.winfo_y()},
                  open(POSITION_FILE, 'w'))
    except: pass

# ── Tkinter ──
import tkinter as tk

COL_W, COL_H = 185, 32
EXP_W, EXP_H = 300, 380
DRAG_THRESH = 5

class BubbleApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('pi')
        self.root.configure(bg=THEME['bg'])
        self.root.attributes('-topmost', True)
        self.root.overrideredirect(True)

        self.state = 'IDLE'
        self.expanded = False
        self._drag_start = None
        self._dragging = False

        self._build()
        self._load_pos()
        self.root.after(0, lambda: self._update())
        self.root.after(200, self._poll)

    def _build(self):
        """Single master frame — handles all mouse events."""
        self.m = tk.Frame(self.root, bg=THEME['bg'])
        self.m.pack(fill=tk.BOTH, expand=True)

        # Status bar
        self.sbar = tk.Frame(self.m, bg=THEME['bg'])
        self.sbar.pack(fill=tk.X, padx=6, pady=4)

        self.dot = tk.Label(self.sbar, text='\u25cf', fg=THEME['idle'],
                            bg=THEME['bg'], font=('Segoe UI Emoji', 10))
        self.dot.pack(side=tk.LEFT)

        self.lbl = tk.Label(self.sbar, text='idle', fg=THEME['fg'],
                            bg=THEME['bg'], font=('Segoe UI', 9))
        self.lbl.pack(side=tk.LEFT)

        # Expanded panel (hidden)
        self.pn = tk.Frame(self.m, bg=THEME['bg'])

        tk.Frame(self.pn, bg=THEME['border'], height=1).pack(fill=tk.X, pady=(0, 4))

        # Response display
        self.txt = tk.Text(self.pn, bg=THEME['bg_input'], fg=THEME['fg'],
                          font=('Consolas', 9), wrap=tk.WORD, state=tk.DISABLED,
                          padx=6, pady=4, relief=tk.GROOVE, bd=1,
                          highlightthickness=0, cursor='arrow')
        self.txt.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        # Input
        self.ifr = tk.Frame(self.pn, bg=THEME['bg'])
        self.ifr.pack(fill=tk.X, padx=4, pady=(0, 4))

        self.ivar = tk.StringVar()
        self.inp = tk.Entry(self.ifr, textvariable=self.ivar,
                           bg=THEME['bg_input'], fg=THEME['fg'],
                           insertbackground=THEME['fg'],
                           font=('Consolas', 9), relief=tk.FLAT,
                           highlightbackground=THEME['border'],
                           highlightthickness=1, cursor='xterm')
        self.inp.pack(fill=tk.X, expand=True)
        self.inp.bind('<Return>', self._send)

        # ── Mouse events on master ──
        # Click/move/release for drag-vs-click detection
        self.m.bind('<Button-1>', self._on_down)
        self.m.bind('<B1-Motion>', self._on_move)
        self.m.bind('<ButtonRelease-1>', self._on_release)

        # Right-click = exit
        self.m.bind('<Button-3>', lambda e: self.root.destroy())

        # Prevent interactive widgets from starting drag
        self.txt.bind('<Button-1>', lambda e: e.widget.focus_set())
        self.inp.bind('<Button-1>', lambda e: e.widget.focus_set())
        self.inp.bind('<B1-Motion>', lambda e: 'break')
        self.inp.bind('<ButtonRelease-1>', lambda e: 'break')

        # Window close = exit
        self.root.protocol('WM_DELETE_WINDOW', lambda: self.root.destroy())

    # ── Drag vs Click ──
    def _on_down(self, event):
        """Record position. Skip interactive widgets."""
        if event.widget in (self.txt, self.inp, self.ifr):
            return
        self._dragging = False
        self._drag_start = (event.x_root, event.y_root,
                           self.root.winfo_x(), self.root.winfo_y())

    def _on_move(self, event):
        """If past threshold, drag the window."""
        if not self._drag_start:
            return
        dx = event.x_root - self._drag_start[0]
        dy = event.y_root - self._drag_start[1]
        if abs(dx) >= DRAG_THRESH or abs(dy) >= DRAG_THRESH:
            self._dragging = True
            wx = max(0, self._drag_start[2] + dx)
            wy = max(0, self._drag_start[3] + dy)
            self.root.geometry(f'+{wx}+{wy}')

    def _on_release(self, event):
        """If not dragged, treat as click → toggle."""
        if not self._drag_start:
            return
        if event.widget in (self.txt, self.inp, self.ifr):
            self._drag_start = None
            return
        if not self._dragging:
            self._toggle()
        self._drag_start = None

    # ── UI ──
    def _toggle(self):
        self.expanded = not self.expanded
        if self.expanded:
            self.pn.pack(fill=tk.BOTH, expand=True)
            self.root.geometry(f'{EXP_W}x{EXP_H}')
            self._show_resp()
            self.inp.focus_set()
        else:
            self.pn.pack_forget()
            self.root.geometry(f'{COL_W}x{COL_H}')
        save_pos(self)

    def _show_resp(self):
        self.txt.configure(state=tk.NORMAL)
        self.txt.delete('1.0', tk.END)

        if self.state == 'WAITING':
            i = read_input()
            if i:
                self.txt.insert(tk.END, f'You: {i}\n\n', 'dim')
                self.txt.tag_config('dim', foreground=THEME['fg_dim'])
            self.txt.insert(tk.END, 'Waiting...', 'waiting')
            self.txt.tag_config('waiting', foreground=THEME['waiting'])
        elif self.state == 'NEW':
            i = read_input()
            if i:
                self.txt.insert(tk.END, f'You: {i}\n\n', 'dim')
                self.txt.tag_config('dim', foreground=THEME['fg_dim'])
            r = read_response()
            if r:
                self.txt.insert(tk.END, r, 'resp')
                self.txt.tag_config('resp', foreground=THEME['fg'])
            else:
                self.txt.insert(tk.END, '(empty)', 'dim')
        else:
            self.txt.insert(tk.END, 'Idle — type a message below.', 'dim')
            self.txt.tag_config('dim', foreground=THEME['fg_dim'])

        self.txt.configure(state=tk.DISABLED)
        self.txt.see(tk.END)

    def _send(self, event=None):
        text = self.ivar.get().strip()
        if text and send_message(text):
            self.ivar.set('')
            self.state = 'WAITING'
            self._update()
            self._show_resp()
        self.inp.focus_set()

    # ── Polling ──
    def _poll(self):
        s = read_state()
        if s != self.state:
            old = self.state
            self.state = s
            if s == 'NEW':
                if not self.expanded:
                    self.expanded = True
                    self.pn.pack(fill=tk.BOTH, expand=True)
                    self.root.geometry(f'{EXP_W}x{EXP_H}')
                    self._show_resp()
            elif old == 'NEW' and s in ('DONE', 'IDLE'):
                self.expanded = False
                self.pn.pack_forget()
                self.root.geometry(f'{COL_W}x{COL_H}')
                save_pos(self)
        self._update()
        self.root.after(200, self._poll)

    def _update(self):
        color = {
            'IDLE': THEME['idle'],
            'WORKING': THEME['working'],
            'DONE': THEME['done'],
            'WAITING': THEME['waiting'],
            'NEW': THEME['new'],
        }.get(self.state, THEME['idle'])
        self.dot.configure(fg=color)
        self.lbl.configure(text=self.state.lower().replace('_', ' '))

    def _load_pos(self):
        p = load_pos()
        self.root.geometry(f'{COL_W}x{COL_H}+{p.get("x", 1200)}+{p.get("y", 20)}')

if __name__ == '__main__':
    app = BubbleApp()
    app.root.mainloop()
