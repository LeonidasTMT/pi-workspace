"""Resident CDP bridge — ONE persistent browser-automation connection.

Every fresh TCP/CDP connection to a Chromium-based browser started with
--remote-debugging-port triggers a per-connection approval prompt in Opera
(and can make the app re-hand the debugger). This daemon holds exactly one
raw WebSocket to the browser's /devtools/browser endpoint for its whole
life, so the prompt appears once. All other automation then goes through
the local HTTP API instead of opening new CDP connections.

Run (pid/log files land in the current working directory):
  python search/cdp_bridge.py                      # start, foreground
  powershell -Command "Start-Process -FilePath python -ArgumentList 'search/cdp_bridge.py' -WindowStyle Hidden"
  python search/cdp_bridge.py status               # healthz + target count
  python search/cdp_bridge.py stop                 # kill via cdp_bridge.pid

HTTP API on http://127.0.0.1:9333 (override with --api-port):
  GET  /targets            -> {"targets": [{id, type, url}]}
  POST /eval   {match | targetId, expr}   Runtime.evaluate in that tab -> {value|error}
  POST /navigate {match | targetId, url}
  POST /close  {targetId}                  close a tab YOU opened only

Contracts (see search/AGENTS.md):
- While the bridge runs it is the ONLY client holding a CDP connection to
  that browser. web_search.py & co. must either go through the bridge or be
  paused — parallel separate connections re-trigger approval prompts and can
  make Opera tear down the shared session.
- Never close user tabs; only pass targetIds of tabs this automation opened.
- Target IDs are stable across in-tab navigations: pin the id up front,
  don't re-match by URL after navigating.

Implementation notes (hard-won on Windows / Opera GX):
- Raw masked WebSocket frames with NO Origin header: Chromium rejects any
  Origin unless launched with --remote-allow-origins; no-origin passes.
- Do not rely on the HTTP /json* endpoints — some builds return 404 for
  them even though the WS endpoint works fine.
"""
import argparse
import base64
import json
import os
import socket
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --------------------------------------------------------------------------
# Raw-socket WebSocket layer (no Origin header — required by this build)
# --------------------------------------------------------------------------


def connect(port=9222):
    s = socket.create_connection(('127.0.0.1', port), timeout=30)
    key = base64.b64encode(os.urandom(16)).decode()
    req = ("GET /devtools/browser HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\n"
           "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n") % (port, key)
    s.sendall(req.encode())
    buf = b''
    while b'\r\n\r\n' not in buf:
        chunk = s.recv(4096)
        if not chunk: raise RuntimeError('handshake failed')
        buf += chunk
    head, _, rest = buf.partition(b'\r\n\r\n')
    assert b' 101 ' in head.split(b'\r\n')[0], head[:80]
    return s, rest


def _send_frame(sock, payload: bytes):
    header = bytearray([0x81])
    n = len(payload)
    mask_bit = 0x80
    if n < 126:
        header.append(mask_bit | n)
    elif n < 65536:
        header.append(mask_bit | 126); header += struct.pack('>H', n)
    else:
        header.append(mask_bit | 127); header += struct.pack('>Q', n)
    mk = os.urandom(4)
    header += mk
    masked = bytes(b ^ mk[i % 4] for i, b in enumerate(payload))
    sock.sendall(bytes(header) + masked)


def _read_exact(sock, buf, n):
    while len(buf) < n:
        chunk = sock.recv(65536)
        if not chunk: raise RuntimeError('closed')
        buf += chunk
    data, buf = buf[:n], buf[n:]
    return data, buf


def recv_msg(sock, state):
    """state = {'buf': bytes}. Returns one CDP dict (skips pings, answers them)."""
    while True:
        if len(state['buf']) < 2:
            chunk = sock.recv(65536)
            if not chunk: raise RuntimeError('closed')
            state['buf'] += chunk
            continue
        buf = state['buf']
        fin = buf[0] & 0x80; op = buf[0] & 0x0F
        masked = bool(buf[1] & 0x80); ln = buf[1] & 0x7F
        off = 2
        if ln == 126:
            while len(buf) < off + 2:
                buf += sock.recv(65536)
            ln = struct.unpack('>H', buf[off:off + 2])[0]; off += 2
        elif ln == 127:
            while len(buf) < off + 8:
                buf += sock.recv(65536)
            ln = struct.unpack('>Q', buf[off:off + 8])[0]; off += 8
        if masked:
            while len(buf) < off + 4:
                buf += sock.recv(65536)
            mk = buf[off:off + 4]; off += 4
        else:
            mk = b''
        state['buf'] = buf
        need = off + ln
        while len(state['buf']) < need:
            chunk = sock.recv(65536)
            if not chunk: raise RuntimeError('closed mid-frame')
            state['buf'] += chunk
        payload, state['buf'] = state['buf'][off:need], state['buf'][need:]
        if mk:
            payload = bytes(b ^ mk[i % 4] for i, b in enumerate(payload))
        if op == 0x9:  # ping -> pong same payload
            _send_frame(sock, payload); continue
        if op != 0x1:
            continue
        try:
            m = json.loads(payload.decode('utf-8'))
        except Exception:
            continue
        if isinstance(m, dict) and 'id' in m:
            return m


# --------------------------------------------------------------------------
# Bridge: one CDP connection + HTTP control API
# --------------------------------------------------------------------------

class Bridge:
    def __init__(self, cdp_port=9222):
        self.cdp_port = cdp_port
        self.lock = threading.RLock()
        self.sock = None
        self.state = {'buf': b''}
        self.next_id = 0
        self.sessions = {}   # targetId -> sessionId (reuse attachments)
        self.connect_cdp()

    def connect_cdp(self):
        attempt = 0
        while True:
            try:
                self.sock, _rest = connect(self.cdp_port)
                return
            except Exception as e:
                attempt += 1
                print(f'cdp connect retry {attempt}: {e}', flush=True)
                time.sleep(3)

    def call(self, method, params=None, session=None):
        with self.lock:
            self.next_id += 1
            mid = self.next_id
            msg = {"id": mid, "method": method}
            if params is not None: msg["params"] = params
            if session: msg["sessionId"] = session
            _send_frame(self.sock, json.dumps(msg).encode())
            t0 = time.time()
            while True:
                try:
                    m = recv_msg(self.sock, self.state)
                except Exception:
                    # dead socket -> reconnect once and retry the call
                    if time.time() - t0 > 90: raise
                    print('cdp socket lost; reconnecting', flush=True)
                    try: self.sock.close()
                    except Exception: pass
                    self.state = {'buf': b''}
                    self.sessions = {}
                    self.connect_cdp()
                    continue
                if m.get('id') == mid and m.get('sessionId') == (session or None):
                    if 'error' in m: raise RuntimeError(m['error'].get('message', str(m['error'])))
                    return m.get('result')

    def session_for(self, target_id):
        with self.lock:
            if target_id not in self.sessions:
                r = self.call('Target.attachToTarget', {'targetId': target_id, 'flatten': True})
                self.sessions[target_id] = r['sessionId']
            return self.sessions[target_id]

    def find_target(self, match=None, target_id=None):
        tgts = self.call('Target.getTargets')['targetInfos']
        if target_id:
            for t in tgts:
                if t['targetId'] == target_id: return t
        elif match:
            for t in tgts:
                if t['type'] == 'page' and match.lower() in (t.get('url') or '').lower():
                    return t
        raise RuntimeError(f'target not found: {match or target_id}')

    def eval(self, expr, match=None, target_id=None):
        t = self.find_target(match=match, target_id=target_id)
        sess = self.session_for(t['targetId'])
        r = self.call('Runtime.evaluate', {'expression': expr, 'returnByValue': True}, session=sess)
        if 'exceptionDetails' in r:
            return {'error': str(r['exceptionDetails'].get('exception', {}).get('description', ''))[:300]}
        v = r.get('result', {}).get('value')
        # stringify non-primitive results for transport safety
        try:
            json.dumps(v)
        except TypeError:
            v = str(v)
        return {'value': v}

    def navigate(self, url, match=None, target_id=None):
        t = self.find_target(match=match, target_id=target_id)
        sess = self.session_for(t['targetId'])
        self.call('Page.navigate', {'url': url}, session=sess)
        return {'ok': True}

    def close(self, target_id):
        self.call('Target.closeTarget', {'targetId': target_id})
        with self.lock:
            self.sessions.pop(target_id, None)
        return {'ok': True}


BRIDGE = None


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stdout.write('http: ' + (fmt % args) + '\n')

    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/targets':
            try:
                r = BRIDGE.call('Target.getTargets')['targetInfos']
                slim = [{'id': t['targetId'], 'type': t['type'], 'url': (t.get('url') or '')[:120]} for t in r]
                self._json(200, {'targets': slim})
            except Exception as e:
                self._json(500, {'error': str(e)[:300]})
        elif self.path == '/healthz':
            self._json(200, {'ok': True})
        else:
            self._json(404, {'error': 'not found'})

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        try:
            body = json.loads(self.rfile.read(n) or b'{}')
        except Exception:
            self._json(400, {'error': 'bad json'}); return
        try:
            if self.path == '/eval':
                r = BRIDGE.eval(body['expr'], match=body.get('match'), target_id=body.get('targetId'))
                self._json(200, r)
            elif self.path == '/navigate':
                r = BRIDGE.navigate(body['url'], match=body.get('match'), target_id=body.get('targetId'))
                self._json(200, r)
            elif self.path == '/close':
                r = BRIDGE.close(body['targetId'])
                self._json(200, r)
            else:
                self._json(404, {'error': 'not found'})
        except Exception as e:
            self._json(500, {'error': str(e)[:300]})


def _api(port, path):
    import urllib.request
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=10) as r:
        return json.loads(r.read().decode())


def main():
    ap = argparse.ArgumentParser(description='Resident CDP bridge daemon (one persistent browser connection).')
    ap.add_argument('--cdp-port', type=int, default=9222, help='browser CDP port (default 9222)')
    ap.add_argument('--api-port', type=int, default=9333, help='local HTTP API port (default 9333)')
    ap.add_argument('action', nargs='?', choices=['start', 'stop', 'status'], default=None)
    args = ap.parse_args()

    if args.action == 'stop':
        if os.path.exists('cdp_bridge.pid'):
            pid = open('cdp_bridge.pid').read().strip()
            try:
                os.kill(int(pid), 9)
                print(f'killed bridge pid {pid}')
            except (ProcessLookupError, ValueError):
                print(f'stale pid file ({pid}); nothing to kill')
            os.remove('cdp_bridge.pid')
        else:
            print('no cdp_bridge.pid in cwd; if it runs elsewhere, find the python process holding port 9333')
        return 0

    if args.action == 'status':
        try:
            info = _api(args.api_port, '/healthz')
            tgts = _api(args.api_port, '/targets')['targets']
            pages = [t for t in tgts if t['type'] == 'page']
            print(f'running: {info}; targets={len(tgts)} (pages={len(pages)})')
            return 0
        except Exception as e:
            print(f'not running ({e})')
            return 1

    # start / foreground (default) — caller may detach (see module docstring)
    global BRIDGE
    BRIDGE = Bridge(cdp_port=args.cdp_port)
    with open('cdp_bridge.pid', 'w') as f:
        f.write(str(os.getpid()))
    tgts = BRIDGE.call('Target.getTargets')['targetInfos']
    print(f'bridge ready; targets={len(tgts)}', flush=True)
    srv = ThreadingHTTPServer(('127.0.0.1', args.api_port), H)
    print(f'http api on http://127.0.0.1:{args.api_port}', flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if os.path.exists('cdp_bridge.pid'):
            os.remove('cdp_bridge.pid')
    return 0


if __name__ == '__main__':
    sys.exit(main())
