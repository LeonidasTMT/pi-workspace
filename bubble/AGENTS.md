# bubble/ — Pi Status Bubble

## Purpose

Always-on-top floating window showing pi's real-time status. Optional message passing from desktop when terminal is backgrounded.

## Files

- **`status.py`** — The app. Tkinter-based, always-on-top, draggable.
- **`watcher.py`** — AI activity watcher. Parses session log to detect states.
- **`test_status.py`** — Signal protocol tests. Run: `python bubble/test_status.py`

## Signal Protocol

Signal files live in `.pi-status/` (gitignored):

| File | Writer | Content |
|------|--------|---------|
| `state` | Watcher (via session log) | THINKING / WRITING / EDITING / WORKING / EXPLORING / IDLE |
| `input` | You (via bubble) | My latest message |
| `response` | Me | My latest reply |
| `history` | Me (append-only) | Chat log, last 10 entries |

## Watcher Activity Detection

`watcher.py` polls the latest session `.jsonl` file every 200ms:

| Session Line | State |
|--------------|-------|
| `toolCall: edit` | EDITING |
| `toolCall: write` | WRITING |
| `toolCall: read` | EXPLORING |
| `toolCall: bash` | WORKING |
| `thinking` | THINKING |
| `user` message | IDLE |
| No growth >5s | IDLE |

## State Machine

| State | Trigger | Auto-transition |
|-------|---------|-----------------|
| `WORKING` | Running commands | → DONE on completion |
| `DONE` | Commands finished | → IDLE after 5s |
| `IDLE` | Default | — |
| `WAITING` | You sent a message | → NEW when I reply |
| `NEW` | I replied | → DONE on read → IDLE |

## Integration

### Shell helpers (`.bash_aliases`)
```bash
_pi-start    # write WORKING to .pi-status/state
_pi-end      # write DONE to .pi-status/state
```

### AI processing loop
1. Check `.pi-status/input` at start of turn
2. If non-empty → treat as user message
3. Process → write `.pi-status/response`
4. Append `.pi-status/history`
5. Write `NEW` to `.pi-status/state`
6. Bubble auto-expands to show reply

## UI

- **Collapsed**: 175×30, translucent, always-on-top
- **Expanded**: 320×320, shows response + input field
- **Click**: Toggle expand/collapse
- **Drag**: Move window (saves position)
- **Right-click**: Exit completely
- **Close (X)**: Exit (right-click also exits)

## Position

Saved to `%LOCALAPPDATA%\pi-bubble\position.json` — persists across runs.

## Testing

```bash
python bubble/test_status.py
```

Tests signal protocol without launching GUI. 14 tests covering:
- State read/write, whitespace handling
- Message send, input/response, history append
- Response truncation, position persistence

## Child DOX Index

No child DOX files.
