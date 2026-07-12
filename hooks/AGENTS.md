# hooks/ — DOX Guard Implementation

## Purpose

Shell and git-level interception of destructive commands (`rm`, `del`, `rmdir`, `shred`).

## Components

- **`pre-commit`** — Git hook. Blocks commits that delete files outside `tmp/` paths. Runs before every `git commit`.
- **`destruct-guard.sh`** — Shell wrapper. Intercepts `rm`, `del`, `rmdir`, `shred` at the bash level. Loaded via `~/.bashrc`.

## Override

```bash
# Temporary override — allows regular files, NOT protected paths
export DESTRUCT_OVERRIDE=1
rm hooks/some-file   # allowed

# Re-enable guard
unset DESTRUCT_OVERRIDE
```

### Protected Paths — ABSOLUTE BLOCK

These paths are NEVER deletable, not even with `DESTRUCT_OVERRIDE`:

- `C:/Users/User/AppData/Local/Opera Software` — Opera GX profile (cookies, history, passwords)
- `C:/Users/User/AppData/Roaming/Opera` — Opera roaming data
- `C:/Users/User/.pi` — pi agent data, auth, sessions
- `C:/Users/User/.npm` — npm packages, cache
- `C:/Users/User/.ssh` — SSH keys
- `C:/Users/User/.gnupg` — GPG keys
- `C:/Users/User/.aws` — AWS credentials
- `C:/Users/User/AppData/Roaming/Git` — Git credentials

Add more to `PROTECTED_PATHS` array in `destruct-guard.sh` as needed.

## Self-Test

The guard runs a self-test on load to verify protected path detection:

```bash
$ source hooks/destruct-guard.sh 2>/dev/null
🛡️  DOX Destruction Guard loaded
   Protected: 9 paths (absolute block)
   Blocked: rm/del/rmdir/shred outside tmp/
   Override: export DESTRUCT_OVERRIDE=1 (does NOT bypass protected)
```

Any failure prints `⚠️` — means paths were added but not detected correctly.

## Coverage

| Command | Guard | Status |
|---------|-------|--------|
| `rm -rf ...` | `destruct-guard.sh` ✅ | Blocked outside tmp/ |
| `rm -r ...` | `destruct-guard.sh` ✅ | Blocked outside tmp/ |
| `rm ...` | `destruct-guard.sh` ✅ | Blocked outside tmp/ |
| `del ...` | `destruct-guard.sh` ✅ | Blocked outside tmp/ |
| `rmdir ...` | `destruct-guard.sh` ✅ | Blocked outside tmp/ |
| `shred ...` | `destruct-guard.sh` ✅ | Blocked outside tmp/ |
| `git rm ...` | `pre-commit` ✅ | Blocked at commit time |
| GUI/file explorer | ❌ not covered | Manual discipline |

## Verification

```bash
# Test block (should fail)
source hooks/destruct-guard.sh && rm hooks/pre-commit

# Test pass (should succeed)
source hooks/destruct-guard.sh && echo "x" > tmp/test && rm tmp/test

# Test override
export DESTRUCT_OVERRIDE=1 && rm hooks/test && unset DESTRUCT_OVERRIDE
```

## Child DOX Index

No child DOX files.
