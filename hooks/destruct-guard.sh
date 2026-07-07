#!/bin/bash
# ╔══════════════════════════════════════════════════════════╗
# ║  DOX DESTRUCTION GUARD — SHELL COMMAND INTERCEPTION     ║
# ║  Blocks rm, del, rmdir, shred outside tmp/ directories  ║
# ║  Place in ~/.bashrc or source manually                  ║
# ╚══════════════════════════════════════════════════════════╝

# ────────────────────────────────────────────────────────
# PROTECTED PATHS — ABSOLUTE BLOCK, NEVER DELETABLE
# ────────────────────────────────────────────────────────
# These paths and their children are NEVER deletable, ever.
# Cannot be overridden by DESTRUCT_OVERRIDE, period.
# Add more here as needed.

PROTECTED_PATHS=(
    "/c/Users/User/AppData/Local/Opera Software"        # Opera GX profile (cookies, history, passwords)
    "/c/Users/User/AppData/Roaming/Opera"               # Opera roaming data
    "/c/Users/User/AppData/Local/Microsoft/Edge"         # Edge profile
    "/c/Users/User/.pi"                                  # pi agent data, auth, sessions, settings
    "/c/Users/User/.npm"                                 # npm cache, config, packages
    "/c/Users/User/.ssh"                                 # SSH keys
    "/c/Users/User/.gnupg"                               # GPG keys
    "/c/Users/User/.aws"                                 # AWS credentials
    "/c/Users/User/AppData/Roaming/Git"                  # Git credentials
)

# ────────────────────────────────────────────────────────
# Environment override — allows deletion outside tmp/
# Does NOT bypass protected paths (those are absolute)
# ────────────────────────────────────────────────────────
#   export DESTRUCT_OVERRIDE=1     # allow non-tmp deletions
#   unset DESTRUCT_OVERRIDE        # re-enable guard

# ────────────────────────────────────────────────────────
# Path classification
# ────────────────────────────────────────────────────────

_dox_is_protected() {
    local path="$1"
    for protected in "${PROTECTED_PATHS[@]}"; do
        [[ "$path" == "$protected" || "$path" == "$protected/"* ]] && return 0
    done
    return 1
}

_dox_is_tmp_path() {
    local path="$1"
    [[ "$path" =~ (^|/)tmp(/|$) ]] && return 0
    return 1
}

# ────────────────────────────────────────────────────────
# Block messages
# ────────────────────────────────────────────────────────

_dox_block_destroy() {
    local cmd="$1"
    local reason="${2:-outside tmp/}"
    shift 2
    echo "" >&2
    echo "❌ DESTRUCTION BLOCKED — DOX Guard" >&2
    echo "   ${cmd} (${reason}) — not allowed." >&2
    echo "" >&2
    for arg in "$@"; do
        [[ "$arg" =~ ^- ]] && continue
        echo "   🚫 $arg" >&2
    done
    echo "" >&2
    if [[ "$reason" == "PROTECTED PATH" ]]; then
        echo "   🔒 Protected path — NEVER deletable, cannot be overridden." >&2
    else
        echo "   Enable override:  export DESTRUCT_OVERRIDE=1" >&2
        echo "   Disable override: unset DESTRUCT_OVERRIDE" >&2
    fi
    echo "" >&2
    return 1
}

# ────────────────────────────────────────────────────────
# classify_path — returns status for a single path
#   0 = tmp (always deletable)
#   1 = protected (never deletable)
#   2 = regular (blocked unless override)
# ────────────────────────────────────────────────────────

classify_path() {
    local path="$1"
    if _dox_is_protected "$path"; then
        echo "protected"
        return
    fi
    if _dox_is_tmp_path "$path"; then
        echo "tmp"
        return
    fi
    echo "regular"
}

# ────────────────────────────────────────────────────────
# check_paths — validates args, returns appropriate status
# ────────────────────────────────────────────────────────

check_paths() {
    local args=("$@")
    local has_protected=0
    local has_regular=0
    local protected_files=()

    for arg in "${args[@]}"; do
        [[ "$arg" =~ ^- ]] && continue
        local status
        status=$(classify_path "$arg")
        case "$status" in
            protected)
                has_protected=1
                protected_files+=("$arg")
                ;;
            regular) has_regular=1 ;;
        esac
    done

    # Protected takes absolute priority
    if [[ $has_protected -eq 1 ]]; then
        _dox_block_destroy "$COMMAND" "PROTECTED PATH" "${protected_files[@]}"
        return 1
    fi

    # Regular: blocked unless override
    if [[ $has_regular -eq 1 ]] && [[ -z "$DESTRUCT_OVERRIDE" ]]; then
        _dox_block_destroy "$COMMAND" "outside tmp/" "${args[@]}"
        return 1
    fi

    return 0
}

# ────────────────────────────────────────────────────────
# rm guard
# ────────────────────────────────────────────────────────

rm() {
    COMMAND="rm"
    if check_paths "$@"; then
        command rm "$@"
    fi
}

# ────────────────────────────────────────────────────────
# rmdir guard
# ────────────────────────────────────────────────────────

rmdir() {
    COMMAND="rmdir"
    if check_paths "$@"; then
        command rmdir "$@"
    fi
}

# ────────────────────────────────────────────────────────
# del guard (Windows alias → rm)
# ────────────────────────────────────────────────────────

del() {
    COMMAND="del"
    if check_paths "$@"; then
        command rm "$@"
    fi
}

# ────────────────────────────────────────────────────────
# shred guard
# ────────────────────────────────────────────────────────

shred() {
    COMMAND="shred"
    if check_paths "$@"; then
        command shred "$@"
    fi
}

# ────────────────────────────────────────────────────────
# Note on git rm / git remove
# ────────────────────────────────────────────────────────
# Shell cannot intercept git subcommands (git is a single binary,
# subcommands are internal). The pre-commit hook handles git deletions.
# If the paths above end up in git staging, the pre-commit hook
# catches them regardless.

# ────────────────────────────────────────────────────────
# Self-test on load
# ────────────────────────────────────────────────────────

_dox_selftest() {
    local pass=0
    local fail=0

    if _dox_is_protected "/c/Users/User/AppData/Local/Opera Software/Opera GX Stable/Cookies"; then
        ((pass++))
    else
        ((fail++)); echo "   ❌ SELFTEST: Opera Cookies not detected as protected" >&2
    fi

    if _dox_is_protected "/c/Users/User/.pi/agent/auth.json"; then
        ((pass++))
    else
        ((fail++)); echo "   ❌ SELFTEST: .pi/auth not detected as protected" >&2
    fi

    if ! _dox_is_protected "hooks/pre-commit"; then
        ((pass++))
    else
        ((fail++)); echo "   ❌ SELFTEST: hooks/pre-commit incorrectly marked protected" >&2
    fi

    if _dox_is_tmp_path "tmp/test"; then
        ((pass++))
    else
        ((fail++)); echo "   ❌ SELFTEST: tmp/test not detected as tmp/" >&2
    fi

    [[ $fail -gt 0 ]] && echo "   ⚠️  $fail self-test(s) FAILED" >&2
}

echo "🛡️  DOX Destruction Guard loaded" >&2
echo "   Protected: ${#PROTECTED_PATHS[@]} paths (absolute block)" >&2
echo "   Blocked: rm/del/rmdir/shred outside tmp/" >&2
echo "   Override: export DESTRUCT_OVERRIDE=1 (does NOT bypass protected)" >&2
_dox_selftest >&2
