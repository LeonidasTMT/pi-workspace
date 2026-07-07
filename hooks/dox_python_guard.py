#!/usr/bin/env python3
"""
DOX Python Write Guard — enforces write-only-in-workspace at the Python level.

Import this BEFORE any file operations. It monkey-patches os.remove, os.unlink,
shutil.rmtree, pathlib.Path.unlink/rmtree, and file() open() to block writes
outside the workspace.

Usage in scripts:
    import dox_python_guard  # blocks everything automatically
"""

import os
import sys
import pathlib
import shutil as _shutil
import builtins as _builtins

WORKSPACE = "/c/Users/User/Documents/GitHub/pi-workspace"
if hasattr(os.path, 'abspath'):
    WORKSPACE = os.path.normcase(os.path.abspath(WORKSPACE))

# Also allow TEMP dir for the web_search.py pattern
TEMP_DIR = os.environ.get('TEMP', os.environ.get('TMP', 'C:\\Windows\\Temp'))
TEMP_DIR = os.path.normcase(os.path.abspath(TEMP_DIR))

# Block DESTRUCT_OVERRIDE at Python level
if os.environ.get('DESTRUCT_OVERRIDE'):
    print("❌ BLOCKED: DESTRUCT_OVERRIDE cannot be set when using DOX guards", file=sys.stderr)
    sys.exit(1)

_saved_environ_setitem = os.environ.__class__.__setitem__

def _guarded_env_set(self, key, value):
    if key == 'DESTRUCT_OVERRIDE':
        raise PermissionError(
            "BLOCKED: DESTRUCT_OVERRIDE cannot be set by Python. "
            "DOX guards are not negotiable."
        )
    _saved_environ_setitem(self, key, value)

os.environ.__class__.__setitem__ = _guarded_env_set

def _is_writeable(path):
    """Check if path is inside workspace or tmp."""
    try:
        norm = os.path.normcase(os.path.abspath(path))
    except Exception:
        return False
    if norm == WORKSPACE or norm.startswith(WORKSPACE + os.sep):
        return True
    if norm == TEMP_DIR or norm.startswith(TEMP_DIR + os.sep):
        return True
    return False


# ── Monkey-patch os.remove ──
_os_remove = os.remove
def _guarded_remove(path):
    if not _is_writeable(path):
        raise PermissionError(
            f"DOX: Cannot delete outside workspace: {path}\n"
            f"  Allowed: {WORKSPACE}, {TEMP_DIR}"
        )
    return _os_remove(path)
os.remove = _guarded_remove


# ── Monkey-patch os.unlink ──
_os_unlink = os.unlink
def _guarded_unlink(path, *args, **kwargs):
    if not _is_writeable(path):
        raise PermissionError(
            f"DOX: Cannot unlink outside workspace: {path}\n"
            f"  Allowed: {WORKSPACE}, {TEMP_DIR}"
        )
    return _os_unlink(path, *args, **kwargs)
os.unlink = _guarded_unlink


# ── Monkey-patch shutil.rmtree ──
_shutil_rmtree = _shutil.rmtree
def _guarded_rmtree(path, *args, **kwargs):
    if not _is_writeable(path):
        raise PermissionError(
            f"DOX: Cannot rmtree outside workspace: {path}\n"
            f"  Allowed: {WORKSPACE}, {TEMP_DIR}"
        )
    return _shutil_rmtree(path, *args, **kwargs)
_shutil.rmtree = _guarded_rmtree


# ── Monkey-patch pathlib.Path.unlink ──
_pathlib_unlink = pathlib.Path.unlink
def _guarded_pathlink(self, *args, **kwargs):
    if not _is_writeable(str(self)):
        raise PermissionError(
            f"DOX: Cannot unlink outside workspace: {self}\n"
            f"  Allowed: {WORKSPACE}, {TEMP_DIR}"
        )
    return _pathlib_unlink(self, *args, **kwargs)
pathlib.Path.unlink = _guarded_pathlink


# ── Monkey-patch open() for write modes ──
_original_open = _builtins.open
_write_modes = {'w', 'x', 'a', 'w+', 'a+', 'x+', 'wb', 'ab', 'xb', 'w+b', 'a+b', 'x+b', 'bw', 'ba', 'bx'}

def _guarded_open(file, mode='r', *args, **kwargs):
    mode_str = str(mode)
    # Check if mode contains a write indicator
    if any(w in mode_str for w in _write_modes):
        if not _is_writeable(file):
            raise PermissionError(
                f"DOX: Cannot write outside workspace: {file} (mode={mode})\n"
                f"  Allowed: {WORKSPACE}, {TEMP_DIR}"
            )
    return _original_open(file, mode, *args, **kwargs)

_builtins.open = _guarded_open


print(f"🐍 DOX Python Guard loaded", file=sys.stderr)
print(f"   Write allowed: {WORKSPACE}, {TEMP_DIR}", file=sys.stderr)
print(f"   DESTRUCT_OVERRIDE: 🔒 locked (Python-level block)", file=sys.stderr)
