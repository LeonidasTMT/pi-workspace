#!/usr/bin/env python3
"""
Pi Status Bubble — always-on-top floating status bubble.

Compact: 150×24 collapsed, 240×180 expanded (response + action + elapsed).
Drag to move. Click to expand/collapse.
Type + Enter to send. Right-click to exit.

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
LAST_RESPONSE_FILE = os.path.join(PI_STATUS, 'last-response')
LAST_ACTION_FILE = os.path.join(PI_STATUS, 'last-action')
INPUT_FILE = os.path.join(PI_STATUS, 'input')
HISTORY_FILE = os.path.join(PI_STATUS, 'history')
POSITION_FILE = os.path.join(
    os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
    'pi-bubble', 'position.json'
)
os.makedirs(PI_STATUS, exist_ok=True)

# ── Theme ──
THEME = {
    'bg':       '#1e1e2e',
    'fg':       '#cdd6f4',
    'fg_dim':   '#6c7086',
    'border':   '#313244',
    'bg_input': '#181825',
    'bg_resp':  '#181825',
    'IDLE':     '#6c7086',
    'WORKING':  '#f9e24c',
    'THINKING': '#cba6f7',
    'WRITING':  '#f38ba8',
    'EDITING':  '#fab387',
    'DONE':     '#a6e3a1',
    'WAITING':  '#89b4fa',
    'NEW':      '#a6e3a1',
    'EXPLORING':'#94e2d0',
    'COMPACTING':'#f9e24c',
}

STATE_LABELS = {
    'IDLE': 'idle', 'WORKING': 'working', 'THINKING': 'thinking',
    'WRITING': 'writing', 'EDITING': 'editing', 'DONE': 'done',
    'WAITING': 'waiting', 'NEW': 'new', 'EXPLORING': 'exploring',
    'COMPACTING': 'compacting',
}

# ── File I/O ──
def read_state():
    try: return open(STATE_FILE).read().strip()
    except: return 'IDLE'

def read_last_response():
    try: return open(LAST_RESPONSE_FILE, encoding='utf-8').read().strip()
    except: return ''

def read_last_action():
    try: return open(LAST_ACTION_FILE, encoding='utf-8').read().strip()
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

COL_W, COL_H = 150, 24
EXP_W, EXP_H = 320, 220
DRAG_THRESH = 5
RESPONSE_LINES = 8  # max lines in response preview

class BubbleApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('pi')
        self.root.configure(bg=THEME['bg'])
        self.root.attributes('-topmost', True)
        self.root.overrideredirect(True)

        self.state = 'IDLE'
        self.expanded = False
        self.last_response = ''
        self.last_action = ''
        self.state_since = time.time()
        self._drag_start = None
        self._dragging = False

        self._build()
        self._load_pos()
        self.root.after(0, lambda: self._update())
        self.root.after(200, self._poll)

    def _build(self):
        self.m = tk.Frame(self.root, bg=THEME['bg'])
        self.m.pack(fill=tk.BOTH, expand=True)

        # Compact status bar
        self.sbar = tk.Frame(self.m, bg=THEME['bg'])
        self.sbar.pack(fill=tk.X, padx=4, pady=2)

        self.dot = tk.Label(self.sbar, text='\u25cf', fg=THEME['IDLE'],
                            bg=THEME['bg'], font=('Segoe UI Emoji', 8))
        self.dot.pack(side=tk.LEFT, padx=(0, 2))

        self.lbl = tk.Label(self.sbar, text='idle', fg=THEME['fg'],
                            bg=THEME['bg'], font=('Segoe UI', 8))
        self.lbl.pack(side=tk.LEFT)

        # Expanded panel
        self.pn = tk.Frame(self.m, bg=THEME['bg'])

        # Response preview (scrollable)
        self.rscrl = tk.Scrollbar(self.pn, bg=THEME['border'],
                                  activebackground=THEME['fg_dim'],
                                  highlightbackground=THEME['border'],
                                  highlightthickness=0, relief=tk.FLAT,
                                  cursor='xterm', width=8)
        self.rscrl.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4), pady=2)

        self.rtxt = tk.Text(self.pn, bg=THEME['bg_resp'], fg=THEME['fg'],
                            font=('Consolas', 8), relief=tk.FLAT,
                            insertbackground=THEME['fg'],
                            borderwidth=0, padx=4, pady=2, wrap=tk.WORD,
                            state=tk.DISABLED, yscrollcommand=self.rscrl.set,
                            cursor='xterm')
        self.rtxt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                       padx=(4, 0), pady=2)
        self.rscrl.config(command=self.rtxt.yview)

        # Action + elapsed bar
        self.abar = tk.Frame(self.pn, bg=THEME['bg'])
        self.action_lbl = tk.Label(self.abar, text='', fg=THEME['fg'],
                                   bg=THEME['bg'], font=('Segoe UI', 7),
                                   anchor=tk.W)
        self.action_lbl.pack(side=tk.LEFT, padx=(4, 0), pady=1)

        self.elapsed_lbl = tk.Label(self.abar, text='', fg=THEME['fg'],
                                    bg=THEME['bg'], font=('Segoe UI', 7),
                                    anchor='e')
        self.elapsed_lbl.pack(side=tk.RIGHT, padx=(0, 4), pady=1)

        # Input bar
        self.ifr = tk.Frame(self.pn, bg=THEME['bg'])
        self.ivar = tk.StringVar()
        self.inp = tk.Entry(self.ifr, textvariable=self.ivar,
                           bg=THEME['bg_input'], fg=THEME['fg'],
                           insertbackground=THEME['fg'],
                           font=('Consolas', 8), relief=tk.FLAT,
                           highlightbackground=THEME['border'],
                           highlightthickness=1, cursor='xterm')
        self.inp.pack(fill=tk.X, padx=4, pady=2)
        self.inp.bind('<Return>', self._send)

        # Mouse events on root = full window hit area
        self.root.bind('<Button-1>', self._on_down)
        self.root.bind('<B1-Motion>', self._on_move)
        self.root.bind('<ButtonRelease-1>', self._on_release)
        self.root.bind('<Button-3>', lambda e: self.root.destroy())

        # Input ignores drag
        self.inp.bind('<Button-1>', lambda e: e.widget.focus_set())
        self.rtxt.bind('<Button-1>', lambda e: self.rtxt.focus_set())

        self.root.protocol('WM_DELETE_WINDOW', lambda: self.root.destroy())

    # ── Drag vs Click ──
    def _on_down(self, event):
        if event.widget in (self.inp, self.ifr, self.rtxt):
            return
        self._dragging = False
        self._drag_start = (event.x_root, event.y_root,
                            self.root.winfo_x(), self.root.winfo_y())

    def _on_move(self, event):
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
        if not self._drag_start:
            return
        if event.widget in (self.inp, self.ifr, self.rtxt):
            self._drag_start = None
            return
        if not self._dragging:
            self._toggle()
        self._drag_start = None

    # ── UI ──
    def _toggle(self):
        self.expanded = not self.expanded
        if self.expanded:
            self.abar.pack(fill=tk.X, padx=(0, 0))
            self.pn.pack(fill=tk.BOTH, expand=True)
            self.ifr.pack(fill=tk.X, padx=4, pady=(2, 4))
            self.root.geometry(f'{EXP_W}x{EXP_H}')
            self.inp.focus_set()
            self._update_expanded()
        else:
            self.pn.pack_forget()
            self.abar.pack_forget()
            self.ifr.pack_forget()
            self.root.geometry(f'{COL_W}x{COL_H}')
        save_pos(self)

    def _send(self, event=None):
        text = self.ivar.get().strip()
        if text and send_message(text):
            self.ivar.set('')
            self.state = 'WAITING'
            self._update()
        self.inp.focus_set()

    def _elapsed(self):
        secs = int(time.time() - self.state_since)
        if secs < 60:
            return f'{secs}s'
        m, s = divmod(secs, 60)
        return f'{m}m {s}s'

    def _update_expanded(self):
        # Update response preview
        self.rtxt.config(state=tk.NORMAL)
        self.rtxt.delete('1.0', tk.END)
        resp = self.last_response or '(no response yet)'
        self.rtxt.insert('1.0', resp)
        self.rtxt.config(state=tk.DISABLED)

        # Update action
        act = self.last_action or STATE_LABELS.get(self.state, self.state.lower())
        self.action_lbl.configure(text=act)

        # Update elapsed
        self.elapsed_lbl.configure(text=self._elapsed())

    # ── Polling ──
    def _poll(self):
        s = read_state()
        if s != self.state:
            old = self.state
            self.state = s
            self.state_since = time.time()

            if s == 'NEW':
                if not self.expanded:
                    self.expanded = True
                    self.abar.pack(fill=tk.X)
                    self.pn.pack(fill=tk.BOTH, expand=True)
                    self.ifr.pack(fill=tk.X, padx=4, pady=(2, 4))
                    self.root.geometry(f'{EXP_W}x{EXP_H}')
                    self._update_expanded()
            elif old == 'NEW' and s in ('DONE', 'IDLE'):
                self.expanded = False
                self.pn.pack_forget()
                self.abar.pack_forget()
                self.ifr.pack_forget()
                self.root.geometry(f'{COL_W}x{COL_H}')
                save_pos(self)
            elif self.expanded:
                self._update_expanded()

        # Refresh expanded view (elapsed timer)
        if self.expanded and s in ('WORKING', 'THINKING', 'WRITING', 'EDITING', 'EXPLORING', 'COMPACTING'):
            self.elapsed_lbl.configure(text=self._elapsed())

        # Fetch response/action for expanded view
        if self.expanded:
            lr = read_last_response()
            la = read_last_action()
            if lr != self.last_response:
                self.last_response = lr
                self._update_expanded_text()
            if la != self.last_action:
                self.last_action = la
                self._update_expanded_action()

        self._update()
        self.root.after(200, self._poll)

    def _update_expanded_text(self):
        self.rtxt.config(state=tk.NORMAL)
        self.rtxt.delete('1.0', tk.END)
        resp = self.last_response or '(no response yet)'
        self.rtxt.insert('1.0', resp)
        self.rtxt.config(state=tk.DISABLED)

    def _update_expanded_action(self):
        act = self.last_action or STATE_LABELS.get(self.state, self.state.lower())
        self.action_lbl.configure(text=act)

    def _update(self):
        c = THEME.get(self.state, THEME['IDLE'])
        self.dot.configure(fg=c)
        self.lbl.configure(text=STATE_LABELS.get(self.state, self.state.lower()))

    def _load_pos(self):
        p = load_pos()
        self.root.geometry(f'{COL_W}x{COL_H}+{p.get("x", 1200)}+{p.get("y", 20)}')

if __name__ == '__main__':
    app = BubbleApp()
    app.root.mainloop()
