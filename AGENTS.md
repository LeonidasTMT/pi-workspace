# DOX — pi-workspace

- DOX is the self-documenting hierarchy for this project
- Follow DOX instructions across any edits

## Core Contract

- AGENTS.md files are binding work contracts for their subtrees
- Work products, source materials, instructions, records, assets, and durable docs must stay understandable from the nearest applicable AGENTS.md plus every parent AGENTS.md above it
- **NO DELETIONS of committed files** — `tmp/` is the only place anything can be deleted
- `tmp/` directories exist inside every module for disposable iteration (`search/tmp/`, `skills/tmp/`, `tmp/`, etc.)
- If old code is superseded, archive or mark it — never delete

## Read Before Editing

1. Read the root AGENTS.md
2. Identify every file or folder you expect to touch
3. Walk from the repository root to each target path
4. Read every AGENTS.md found along each route
5. If a parent AGENTS.md lists a child AGENTS.md whose scope contains the path, read that child and continue from there
6. Use the nearest AGENTS.md as the local contract and parent docs for repo-wide rules
7. If docs conflict, the closer doc controls local work details, but no child doc may weaken DOX

Do not rely on memory. Re-read the applicable DOX chain in the current session before editing.

## Update After Editing

Every meaningful change requires a DOX pass before the task is done.

Update the closest owning AGENTS.md when a change affects:

- purpose, scope, ownership, or responsibilities
- durable structure, contracts, workflows, or operating rules
- required inputs, outputs, permissions, constraints, side effects, or artifacts
- user preferences about behavior, communication, process, organization, or quality
- AGENTS.md creation, deletion, move, rename, or index contents

Update parent docs when parent-level structure, ownership, workflow, or child index changes. Update child docs when parent changes alter local rules. Remove stale or contradictory text immediately. Small edits that do not change behavior or contracts may leave docs unchanged, but the DOX pass still must happen.

## Hierarchy

- Root AGENTS.md is the DOX rail: project-wide instructions, global preferences, durable workflow rules, and the top-level Child DOX Index
- Child AGENTS.md files own domain-specific instructions and their own Child DOX Index
- Each parent explains what its direct children cover and what stays owned by the parent
- The closer a doc is to the work, the more specific and practical it must be

## Child Doc Shape

- Create a child AGENTS.md when a folder becomes a durable boundary with its own purpose, rules, responsibilities, workflow, materials, or quality standards
- Work Guidance must reflect the current standards of the project or user instructions; if there are no specific standards or instructions yet, leave it empty
- Verification must reflect an existing check; if no verification framework exists yet, leave it empty and update it when one exists

Default section order:
- Purpose
- Ownership
- Local Contracts
- Work Guidance
- Verification
- Child DOX Index

## Style

- Keep docs concise, current, and operational
- Document stable contracts, not diary entries
- Put broad rules in parent docs and concrete details in child docs
- Prefer direct bullets with explicit names
- Do not duplicate rules across many files unless each scope needs a local version
- Delete stale notes instead of explaining history
- Trim obvious statements, repeated rules, misplaced detail, and warnings for risks that no longer exist

## Closeout

1. Re-check changed paths against the DOX chain
2. Update nearest owning docs and any affected parents or children
3. Refresh every affected Child DOX Index
4. Remove stale or contradictory text
5. Run existing verification when relevant
6. Report any docs intentionally left unchanged and why

## User Preferences

- User prefers explicit review/approval before files are written
- No paid third-party APIs — use browser automation or free tools only
- User uses Opera GX with `--remote-debugging-port=9222` for CDP automation
- Search/extraction must create new tabs, never touch existing user tabs
- User works on Windows with cp932 console encoding — route Unicode output through temp files or stdout.buffer

### Deletion Guards — ENFORCED
- **Git pre-commit hook** (`hooks/pre-commit`) — blocks commits that delete files outside `tmp/`
- **Shell destruction guard** (`hooks/destruct-guard.sh`) — intercepts `rm`, `del`, `rmdir`, `shred` at the shell level
- Guards are loaded automatically via `~/.bashrc`
- Override: `export DESTRUCT_OVERRIDE=1` (then `unset` to re-enable)
- `tmp/` directories are the only place deletion is allowed
- Superseded code: archive, mark, or move — never delete
- `git rm` → intercepted by pre-commit hook; `rm -rf` → intercepted by shell guard

## Tech Stack

- **Language:** TypeScript
- **Runtime:** Node.js
- **Agent Framework:** [pi](https://pi.dev)
- **Package Manager:** npm
- **Browser Automation:** Opera GX via Chrome DevTools Protocol (CDP)
- **Search:** `search/web_search.py` CLI via Opera CDP (port 9222)

## Coding Standards

- Write clean, readable code with clear variable names
- Prefer existing patterns in the codebase over new conventions
- Keep functions focused and small
- Add comments for non-obvious logic only
- Use TypeScript types explicitly — avoid `any`
- Conventional Commits: `feat: add login`, `fix: handle null case`, `docs: update readme`

## Development Workflow

- Always verify changes work before declaring done
- Run existing tests after making changes
- Use `bash` to verify file changes (ls, cat, etc.)
- Prefer `edit` for modifying existing files, `write` for new files
- Read files fully before making changes

## Child DOX Index

- **hooks/** — DOX guard implementation (shell interception, git hooks)
- **search/** — Web search and extraction via Opera CDP
- **skills/** — AI agent skills, extensions, and reusable procedures
- **tmp/** — Temporary prototypes (excluded from git, disposable)
