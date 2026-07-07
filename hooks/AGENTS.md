# hooks/ — DOX Guard Implementation

## Purpose

Shell and git-level interception of destructive commands (`rm`, `del`, `rmdir`, `shred`).

## Components

- **`pre-commit`** — Git hook. Blocks commits that delete files outside `tmp/` paths. Runs before every `git commit`.
- **`destruct-guard.sh`** — Shell wrapper. Intercepts `rm`, `del`, `rmdir`, `shred` at the bash level. Loaded via `~/.bashrc`.

## Override

```bash
# Temporary override
export DESTRUCT_OVERRIDE=1
rm hooks/some-file   # allowed

# Re-enable guard
unset DESTRUCT_OVERRIDE
```

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
