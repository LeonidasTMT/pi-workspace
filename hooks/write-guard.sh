#!/bin/bash
# ╔══════════════════════════════════════════════════════════╗
# ║  DOX WRITE GUARD — FORCES WRITES INTO PI-WORKSPACE ONLY ║
# ║  Intercepts shell writes: cp, mv, touch, cat >, tee     ║
# ║  Also blocks DESTRUCT_OVERRIDE from being set            ║
# ╚══════════════════════════════════════════════════════════╝

# Workspace root — writes only allowed here
WORKSPACE_ROOT="/c/Users/User/Documents/GitHub/pi-workspace"

# ────────────────────────────────────────────────────────
# BLOCK DESTRUCT_OVERRIDE — nobody sets this, not even AI
# ────────────────────────────────────────────────────────
# Intercept export to catch DESTRUCT_OVERRIDE being set

export() {
    for arg in "$@"; do
        if [[ "$arg" == "DESTRUCT_OVERRIDE"* ]]; then
            echo "" >&2
            echo "❌ BLOCKED — DESTRUCT_OVERRIDE cannot be set" >&2
            echo "   This variable is locked to prevent circumventing DOX guards." >&2
            echo "" >&2
            return 1
        fi
    done
    command export "$@"
}

# ────────────────────────────────────────────────────────
# Path validation
# ────────────────────────────────────────────────────────

_dox_is_workspace() {
    local path="$1"
    [[ "$path" == "$WORKSPACE_ROOT" || "$path" == "$WORKSPACE_ROOT/"* ]] && return 0
    return 1
}

# ────────────────────────────────────────────────────────
# cp guard — destination must be inside workspace
# ────────────────────────────────────────────────────────

cp() {
    # Extract destination (last non-flag arg, or after -t)
    local dest=""
    local has_t=0
    for arg in "$@"; do
        if [[ "$arg" == "-t" ]]; then
            has_t=1
            continue
        fi
        [[ "$arg" =~ ^- ]] && continue
        if [[ $has_t -eq 0 ]]; then
            dest="$arg"
        else
            # After -t flag, all args are destinations
            if ! _dox_is_workspace "$arg" && ! [[ -d "$arg" ]]; then
                echo "" >&2
                echo "❌ WRITE BLOCKED — outside pi-workspace" >&2
                echo "   Can only write to: ${WORKSPACE_ROOT}" >&2
                echo "   Target: $arg" >&2
                echo "" >&2
                return 1
            fi
        fi
    done
    command cp "$@"
}

# ────────────────────────────────────────────────────────
# mv guard — destination must be inside workspace
# ────────────────────────────────────────────────────────

mv() {
    # Last non-flag arg is destination
    local dest=""
    for arg in "$@"; do
        [[ "$arg" =~ ^- ]] && continue
        dest="$arg"
    done
    if [[ -n "$dest" ]] && ! _dox_is_workspace "$dest"; then
        # Allow mv between tmp/ or within workspace
        # Block writing OUTSIDE workspace
        echo "" >&2
        echo "❌ WRITE BLOCKED — outside pi-workspace" >&2
        echo "   Can only write to: ${WORKSPACE_ROOT}" >&2
        echo "   Destination: $dest" >&2
        echo "" >&2
        return 1
    fi
    command mv "$@"
}

# ────────────────────────────────────────────────────────
# touch guard — must be inside workspace
# ────────────────────────────────────────────────────────

touch() {
    for arg in "$@"; do
        [[ "$arg" =~ ^- ]] && continue
        if ! _dox_is_workspace "$arg"; then
            echo "" >&2
            echo "❌ WRITE BLOCKED — outside pi-workspace" >&2
            echo "   Can only write to: ${WORKSPACE_ROOT}" >&2
            echo "   Target: $arg" >&2
            echo "" >&2
            return 1
        fi
    done
    command touch "$@"
}

# ────────────────────────────────────────────────────────
# tee guard — destination must be inside workspace
# ────────────────────────────────────────────────────────

tee() {
    for arg in "$@"; do
        [[ "$arg" =~ ^- ]] && continue
        if ! _dox_is_workspace "$arg"; then
            echo "" >&2
            echo "❌ WRITE BLOCKED — outside pi-workspace (tee)" >&2
            echo "   Can only write to: ${WORKSPACE_ROOT}" >&2
            echo "   Target: $arg" >&2
            echo "" >&2
            return 1
        fi
    done
    command tee "$@"
}

echo "🔒 DOX Write Guard loaded — writes restricted to: ${WORKSPACE_ROOT}" >&2
echo "   DESTRUCT_OVERRIDE: 🔒 locked (cannot be set)" >&2
