#!/bin/bash
# ╔══════════════════════════════════════════════════════════╗
# ║  DOX DESTRUCTION GUARD — SHELL COMMAND INTERCEPTION     ║
# ║  Blocks rm, del, rmdir, shred outside tmp/ directories  ║
# ║  Place in ~/.bashrc or source manually                  ║
# ╚══════════════════════════════════════════════════════════╝

# ────────────────────────────────────────────────────────
# Override via environment variable:
#   export DESTRUCT_OVERRIDE=1     # allow all
#   unset DESTRUCT_OVERRIDE        # re-enable guard
# ────────────────────────────────────────────────────────

_dox_is_tmp_path() {
    local path="$1"
    # Check if path contains /tmp/ or starts with tmp/
    [[ "$path" =~ (^|/)tmp(/|$) ]] && return 0
    return 1
}

_dox_block_destroy() {
    local cmd="$1"
    shift
    echo "" >&2
    echo "❌ DESTRUCTION BLOCKED — DOX Guard" >&2
    echo "   ${cmd} outside tmp/ is not allowed." >&2
    echo "   Only files inside tmp/ directories can be destroyed." >&2
    echo "" >&2

    # Show what was blocked
    for arg in "$@"; do
        # Skip flags
        [[ "$arg" =~ ^- ]] && continue
        echo "   🚫 $arg" >&2
    done

    echo "" >&2
    echo "   Enable override:  export DESTRUCT_OVERRIDE=1" >&2
    echo "   Disable override: unset DESTRUCT_OVERRIDE" >&2
    echo "   Then retry:       ${cmd} $*" >&2
    echo "" >&2
    return 1
}

# ────────────────────────────────────────────────────────
# Guard: rm
# ────────────────────────────────────────────────────────
rm() {
    # Respect override
    [[ -n "$DESTRUCT_OVERRIDE" ]] && command rm "$@" && return

    local has_non_tmp=0
    local args=()

    for arg in "$@"; do
        # Skip flags and options
        if [[ "$arg" =~ ^- ]]; then
            args+=("$arg")
            continue
        fi
        args+=("$arg")
        # Check this path against tmp/
        if ! _dox_is_tmp_path "$arg"; then
            has_non_tmp=1
        fi
    done

    if [[ $has_non_tmp -eq 1 ]]; then
        _dox_block_destroy "rm" "$@"
        return 1
    fi

    command rm "$@"
}

# ────────────────────────────────────────────────────────
# Guard: rmdir
# ────────────────────────────────────────────────────────
rmdir() {
    [[ -n "$DESTRUCT_OVERRIDE" ]] && command rmdir "$@" && return

    local has_non_tmp=0
    local args=()

    for arg in "$@"; do
        [[ "$arg" =~ ^- ]] && args+=("$arg") && continue
        args+=("$arg")
        if ! _dox_is_tmp_path "$arg"; then
            has_non_tmp=1
        fi
    done

    if [[ $has_non_tmp -eq 1 ]]; then
        _dox_block_destroy "rmdir" "$@"
        return 1
    fi

    command rmdir "$@"
}

# ────────────────────────────────────────────────────────
# Guard: del (Windows aliases)
# ────────────────────────────────────────────────────────
del() {
    # del maps to rm guard
    rm "$@"
}

# ────────────────────────────────────────────────────────
# Guard: shred / srm (secure delete)
# ────────────────────────────────────────────────────────
shred() {
    [[ -n "$DESTRUCT_OVERRIDE" ]] && command shred "$@" && return

    local args=()
    for arg in "$@"; do
        [[ "$arg" =~ ^- ]] && args+=("$arg") && continue
        args+=("$arg")
        if ! _dox_is_tmp_path "$arg"; then
            _dox_block_destroy "shred" "$@"
            return 1
        fi
    done
    command shred "$@"
}

# ────────────────────────────────────────────────────────
# git rm / git remove — intercepted by pre-commit hook
# ────────────────────────────────────────────────────────
# Shell cannot intercept git subcommands (git calls its own binary).
# The pre-commit hook handles git deletions.
# Shell-level guard only covers direct file system destruction.

# ────────────────────────────────────────────────────────
# Aliases — common dangerous rm patterns still go through guard
# ────────────────────────────────────────────────────────
# Aliases resolve before functions, so rm -rf still hits our rm() wrapper

# ────────────────────────────────────────────────────────
# Confirm load
# ────────────────────────────────────────────────────────
echo "🛡️  DOX Destruction Guard loaded — rm/del/rmdir/shred intercepted"


