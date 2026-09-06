/**
 * todos — sub-goal tracker for pi.
 *
 * Keeps the user (and the agent) in sync on what is being worked on:
 * - persistent widget above the editor + footer status, always visible
 * - `todo` tool so the agent plans/updates sub-goals while working
 *   (big goals = top-level items; sub-goals = children via parentId)
 * - `/todos` interactive board: add, edit, mark doing/done, reprioritize, remove
 *
 * Persistence is branch-safe: every mutation (tool action or board edit)
 * appends a full-state custom entry; reconstruction replays the current
 * branch and lets the last write win.
 *
 * Usage:
 *   /todos            open interactive board
 *   /todos add TEXT   quick-add a top-level goal
 *   /todos do ID      mark item as "doing" (current focus)
 *   /todos done ID    complete an item
 *   /todos rm ID      remove an item
 *
 * Board keys:  ↑/↓ select · a add sub · g add goal · e edit · s doing · d done
 *              u up · y down · t top priority · r remove · c clear done
 *              enter edit · q/esc quit        (input mode: enter save, esc back)
 */

import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext, Theme } from "@earendil-works/pi-coding-agent";
import { Key, matchesKey, truncateToWidth } from "@earendil-works/pi-tui";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

/* ------------------------------------ model */

type GoalStatus = "todo" | "doing" | "done";

interface Goal {
	id: number;
	text: string;
	/** null = top-level "big goal" */
	parentId: number | null;
	status: GoalStatus;
}

interface TodoState {
	items: Goal[]; // flat array in display order (children right after parent)
	nextId: number;
}

const TOOL_NAME = "todo";
const STATE_ENTRY = "todos-state";
const WIDGET_ID = "todos-widget";
const STATUS_ID = "todos-status";

let state: TodoState = { items: [], nextId: 1 };

/* ------------------------------ state helpers */

function goalById(id: number): Goal | undefined {
	return state.items.find((g) => g.id === id);
}

/** Only one item may be "doing" at a time (the current focus). */
function enforceSingleDoing(): void {
	let seen = false;
	for (const g of state.items) {
		if (g.status !== "doing") continue;
		if (seen) g.status = "todo";
		else seen = true;
	}
}

/** Ordered ids at the same level as `id` (top-level or siblings). */
function levelOrder(id: number): number[] {
	const target = goalById(id);
	if (!target) return [];
	const pool = state.items.filter((g) =>
		target.parentId === null ? g.parentId === null : g.parentId === target.parentId,
	);
	return pool.map((g) => g.id);
}

/** Rewrite flat array so that same-level slots follow `order` (children stay glued to parents). */
function applyLevelOrder(order: number[]): void {
	if (!order.length) return;
	const byId = new Map(state.items.map((g) => [g.id, g]));
	// doc-order children per top-level parent
	const kidsOf = new Map<number, Goal[]>();
	for (const g of state.items) {
		if (g.parentId === null) continue;
		const a = kidsOf.get(g.parentId);
		if (a) a.push(g);
		else kidsOf.set(g.parentId, [g]);
	}
	// top-level member: children follow immediately after their parent
	if ((byId.get(order[0])?.parentId ?? null) === null) {
		state.items = order.flatMap((id) => {
			const m = byId.get(id);
			return m ? [m, ...(kidsOf.get(m.id) ?? [])] : [];
		});
	} else {
		// sibling move under some parent: keep top-level order, splice that parent's block
		const p = byId.get(order[0])!.parentId!;
		state.items = state.items
			.filter((g) => g.parentId === null)
			.flatMap((t) => [t, ...(t.id === p ? order.map((id) => byId.get(id)) : kidsOf.get(t.id) ?? [])]);
	}
}

function moveItem(id: number, dir?: "up" | "down" | "top", pos?: number): string {
	const order = levelOrder(id);
	if (!order.includes(id)) return `#${id} not found`;
	let nextIdx: number;
	if (pos !== undefined) nextIdx = Math.max(0, Math.min(order.length - 1, pos));
	else if (dir === "top") nextIdx = 0;
	else {
		const i = order.indexOf(id);
		nextIdx = dir === "down" ? Math.min(order.length - 1, i + 1) : Math.max(0, i - 1);
	}
	if (nextIdx === order.indexOf(id)) return `#${id} already at that position`;
	const copy = order.filter((x) => x !== id);
	copy.splice(nextIdx, 0, id);
	applyLevelOrder(copy);
	return `moved #${id} to priority ${nextIdx + 1}/${order.length}`;
}

function addItem(text: string, parentId?: number, status?: GoalStatus): Goal {
	const parent = parentId === undefined ? null : goalById(parentId) ?? null;
	if (parent && parent.parentId !== null) {
		throw new Error(`#${parent.id} is not a top-level goal — only direct children are supported`);
	}
	const id = state.nextId++;
	const goal: Goal = { id, text, parentId: parent ? parent.id : null, status: "todo" };
	let pos = state.items.length;
	if (parent) {
		pos = state.items.findIndex((g) => g.id === parent!.id);
		while (pos + 1 < state.items.length && state.items[pos + 1].parentId === parent.id) pos++;
	}
	state.items.splice(pos + 1, 0, goal);
	if (status === "done") goal.status = "done";
	else if (status === "doing") setStatus(goal.id, "doing");
	return goal;
}

function reparentItem(id: number, parentId?: number): string {
	const g = goalById(id);
	if (!g) return `#${id} not found`;
	if (parentId !== undefined && !goalById(parentId)) return `parent #${parentId} not found`;
	// Prevent promoting into own subtree.
	let p = parentId === undefined ? null : goalById(parentId)!;
	while (p) {
		if (p.id === id) return "cannot move a goal under itself";
		p = p.parentId === null ? null : goalById(p.parentId)!;
	}
	state.items = state.items.filter((x) => x.id !== id);
	g.parentId = parentId === undefined ? null : parentId!;
	if (g.parentId === null) {
		let pos = -1;
		for (let i = state.items.length - 1; i >= 0; i--)
			if (state.items[i].parentId === null) { pos = i; break; }
		while (pos + 1 < state.items.length && state.items[pos + 1].parentId !== null) pos++;
		state.items.splice(pos + 1, 0, g);
	} else {
		const parent = goalById(g.parentId)!;
		let pos = state.items.findIndex((x) => x.id === parent.id);
		while (pos + 1 < state.items.length && state.items[pos + 1].parentId === parent.id) pos++;
		state.items.splice(pos + 1, 0, g);
	}
	enforceSingleDoing();
	return `#${id} ${g.parentId === null ? "promoted to top-level" : `now under #${g.parentId}`}`;
}

function subtreeIds(id: number): Set<number> {
	const ids = new Set([id]);
	let added = true;
	while (added) {
		added = false;
		for (const g of state.items) {
			if (!ids.has(g.id) && g.parentId !== null && ids.has(g.parentId)) {
				ids.add(g.id);
				added = true;
			}
		}
	}
	return ids;
}

function removeItem(id: number): string {
	const g = goalById(id);
	if (!g) return `#${id} not found`;
	const gone = subtreeIds(id);
	state.items = state.items.filter((x) => !gone.has(x.id));
	enforceSingleDoing();
	return gone.size > 1 ? `removed #${id} + ${gone.size - 1} sub-goal(s)` : `removed #${id}`;
}

function clearDone(): string {
	const memo = new Map<number, boolean>();
	const allDone = (id: number): boolean => {
		if (memo.has(id)) return memo.get(id)!;
		const g = goalById(id);
		if (!g) return true;
		const kids = state.items.filter((x) => x.parentId === id).map((k) => k.id);
		const ok = g.status === "done" && kids.every(allDone);
		memo.set(id, ok);
		return ok;
	};
	const gone = new Set<number>();
	for (const top of state.items.filter((g) => g.parentId === null)) {
		if (allDone(top.id)) for (const id of subtreeIds(top.id)) gone.add(id);
	}
	state.items = state.items.filter((x) => !gone.has(x.id));
	enforceSingleDoing();
	return `cleared ${gone.size} completed item(s)`;
}

function setStatus(id: number, status: GoalStatus): string {
	const g = goalById(id);
	if (!g) return `#${id} not found`;
	// "doing" is the focus — last write wins.
	if (status === "doing") {
		for (const x of state.items)
			if (x.id !== id && x.status === "doing") x.status = "todo";
	}
	g.status = status;
	enforceSingleDoing();
	return `#${id} → ${status}`;
}

/* ------------------------------ persistence */

function snapshot(): TodoState {
	return { items: state.items.map((g) => ({ ...g })), nextId: state.nextId };
}

function sanitize(data: unknown): TodoState | null {
	const d = data as Partial<TodoState> | undefined;
	if (!d || !Array.isArray(d.items)) return null;
	const items: Goal[] = [];
	for (const raw of d.items) {
		const g = raw as Partial<Goal>;
		if (!g || typeof g.text !== "string" || !g.text) continue;
		items.push({
			id: typeof g.id === "number" ? g.id : items.length + 1,
			text: g.text,
			parentId: typeof g.parentId === "number" ? g.parentId : null,
			status: g.status === "done" || g.status === "doing" ? g.status : "todo",
		});
	}
	return {
		items,
		nextId:
			typeof d.nextId === "number" && d.nextId > 0
				? d.nextId
				: (items.reduce((m, g) => Math.max(m, g.id), 0) + 1),
	};
}

function reconstruct(ctx: ExtensionContext): void {
	let st: TodoState | null = null;
	for (const entry of ctx.sessionManager.getBranch()) {
		if (entry.type === "message") {
			const msg = entry.message;
			if (msg.role !== "toolResult" || msg.toolName !== TOOL_NAME) continue;
			st = sanitize(msg.details);
		} else if (entry.type === "custom" && entry.customType === STATE_ENTRY) {
			st = sanitize(entry.data);
		}
		if (!st) st = null;
	}
	state = st ?? { items: [], nextId: 1 };
	enforceSingleDoing();
}

/* ------------------------------ display */

function progressLine(theme: Theme): string {
	const total = state.items.length;
	const done = state.items.filter((g) => g.status === "done").length;
	const barW = 10;
	const fill = Math.round((total ? done / total : 0) * barW);
	return (
		theme.fg("muted", "⬦ todos ") +
		theme.fg("accent", `${done}/${total}`) +
		" " +
		theme.fg("dim", "▓".repeat(fill) + "░".repeat(barW - fill))
	);
}

function goalLine(theme: Theme, g: Goal): string {
	const indent = g.parentId === null ? "  " : "      ";
	const mark =
		g.status === "done" ? theme.fg("success", "✓") : g.status === "doing" ? theme.fg("accent", "→") : theme.fg("dim", "○");
	const text =
		g.status === "done"
			? theme.fg("dim", g.text)
			: g.status === "doing"
				? theme.bold(theme.fg("text", g.text))
				: theme.fg("muted", g.text);
	return indent + mark + " " + text;
}

function widgetLines(theme: Theme): string[] {
	const items = state.items;
	if (!items.length) return [];
	const lines = [progressLine(theme)];
	const maxRows = 12;
	items.forEach((g, i) => {
		if (i >= maxRows) {
			lines.push(theme.fg("dim", `      … +${items.length - maxRows} more`));
			return;
		}
		lines.push(truncateToWidth(goalLine(theme, g), 100));
	});
	return lines;
}

function statusText(): string {
	if (!state.items.length) return "";
	const done = state.items.filter((g) => g.status === "done").length;
	const doing = state.items.find((g) => g.status === "doing");
	const s0 = `todos ${done}/${state.items.length}`;
	let out = s0;
	if (doing) out += ` · → ${truncateToWidth(doing.text, 42)}`;
	return out;
}

function refreshUi(ctx: ExtensionContext): void {
	if (!ctx.hasUI) return;
	const th = ctx.ui.theme;
	const lines = widgetLines(th);
	ctx.ui.setWidget(WIDGET_ID, lines.length ? lines : undefined);
	ctx.ui.setStatus(STATUS_ID, statusText() || undefined);
}

/** Plain-text board for the LLM. */
function boardText(): string {
	if (!state.items.length) return "(board empty — use add to plan sub-goals)";
	return state.items
		.map((g) => `${goalById(g.id)?.parentId === null ? "" : "  "}[${g.status}] #${g.id} ${g.text}`)
		.join("\n");
}

/* ------------------------------ tool */

const TodoParams = Type.Object({
	action: StringEnum(["list", "add", "update", "reparent", "move", "remove", "clearDone"] as const),
	text: Type.Optional(Type.String({ description: "Goal text (for add/update)" })),
	id: Type.Optional(Type.Number({ description: "Item id" })),
	parentId: Type.Optional(Type.Number({ description: "Parent top-level goal id (add/reparent; omit for top-level)" })),
	status: Type.Optional(StringEnum(["todo", "doing", "done"] as const)),
	dir: Type.Optional(StringEnum(["up", "down", "top"] as const), { description: "move direction" }),
	pos: Type.Optional(Type.Number({ minimum: 0, description: "absolute position within level (move)" })),
});

/* ------------------------------ /todos board UI */

class TodoBoard {
	private sel = 0;
	private mode: "browse" | "input" = "browse";
	private buf = "";
	private flash = "";
	private commit?: () => void;
	public onChanged: (() => void) | undefined;
	public onClose: (() => void) | undefined;
	private cachedWidth?: number;
	private cachedLines?: string[];

	constructor(private theme: Theme) {}

	handleInput(data: string): void {
		this.flash = "";
		if (this.mode === "input") {
			if (matchesKey(data, Key.enter)) this.commit?.();
			else if (matchesKey(data, Key.escape)) this.toBrowse(false);
			else if (matchesKey(data, Key.backspace) || matchesKey(data, Key.delete))
				this.buf = this.buf.slice(0, -1);
			else {
				const clean = data.replace(/[\x00-\x1f\x7f]/g, "");
				if (clean && this.buf.length < 200) this.buf += clean;
			}
			this.invalidate();
			return;
		}

		if (!state.items.length) {
			if (matchesKey(data, "a")) this.startAdd(null);
			else if (matchesKey(data, Key.escape) || matchesKey(data, "q") || matchesKey(data, Key.ctrl("c")))
				this.onClose?.();
			return;
		}

		const last = state.items.length - 1;
		if (matchesKey(data, Key.up) || matchesKey(data, "k")) this.sel = Math.max(0, this.sel - 1);
		else if (matchesKey(data, Key.down) || matchesKey(data, "j")) this.sel = Math.min(last, this.sel + 1);
		else {
			const g = state.items[this.sel];
			switch (data) {
				case "a":
					// top-level selected → sub-goal under it; child selected → sibling
					this.startAdd(g.parentId === null ? g.id : g.parentId);
					break;
				case "g":
					// always a new top-level goal (append at end)
					this.startAdd(null);
					break;
				case "e":
					this.startEdit();
					break;
				case "s":
					setStatus(g.id, "doing");
					this.afterMutate(`#${g.id} marked doing`);
					break;
				case "d":
					setStatus(g.id, g.status === "done" ? "todo" : "done");
					this.afterMutate(`${g.status === "done" ? "reopened" : "completed"} #${g.id}`);
					break;
				case "u":
					this.afterMutate(moveItem(g.id, "up"));
					break;
				case "y":
					this.afterMutate(moveItem(g.id, "down"));
					break;
				case "t":
					this.afterMutate(moveItem(g.id, "top"));
					break;
				case "r":
					removeItem(g.id);
					this.sel = Math.min(this.sel, state.items.length - 1);
					this.afterMutate(`removed #${g.id}`);
					break;
				case "c": {
					const msg = clearDone();
					this.sel = Math.max(0, Math.min(this.sel, state.items.length - 1));
					this.afterMutate(msg);
					break;
				}
			}
		}

		if (matchesKey(data, Key.enter)) this.startEdit();
		else if (matchesKey(data, "q") || matchesKey(data, Key.escape) || matchesKey(data, Key.ctrl("c"))) {
			this.onClose?.();
			return;
		} else this.invalidate();
	}

	private afterMutate(msg: string): void {
		this.sel = Math.max(0, Math.min(this.sel, state.items.length - 1));
		this.flash = msg;
		this.onChanged?.();
		this.invalidate();
	}

	private startAdd(parentId: number | null): void {
		this.mode = "input";
		this.buf = "";
		this.commit = () => {
			const text = this.buf.trim();
			if (!text) return this.toBrowse(true);
			try {
				addItem(text, parentId ?? undefined);
				this.afterMutate(`added "${truncateToWidth(text, 40)}"`);
			} catch (err) {
				this.flash = `error: ${(err as Error).message}`;
			}
			this.toBrowse(false);
		};
		this.invalidate();
	}

	private startEdit(): void {
		const g = state.items[this.sel];
		if (!g) return;
		this.mode = "input";
		this.buf = g.text;
		this.commit = () => {
			const text = this.buf.trim();
			if (text && text !== g.text) g.text = text;
			this.toBrowse(true);
		};
		this.invalidate();
	}

	private toBrowse(mutated: boolean): void {
		this.mode = "browse";
		this.commit = undefined;
		if (mutated) this.onChanged?.();
		this.invalidate();
	}

	render(width: number): string[] {
		if (this.cachedLines && this.cachedWidth === width) return this.cachedLines;
		const th = this.theme;
		const lines: string[] = [progressLine(th)];

		if (!state.items.length) {
			if (this.mode === "input") {
				lines.push(
					truncateToWidth(`${th.fg("accent", "> ○ ")}${this.buf ? th.fg("text", this.buf) : th.fg("dim", "new goal…")}`, width),
				);
			} else {
				lines.push(th.fg("dim", "  no goals yet — press a to add"));
			}
		} else {
			state.items.forEach((g, i) => {
				const selected = i === this.sel;
				const indent = g.parentId === null ? "" : "    ";
				const mark =
					g.status === "done"
						? th.fg("success", "✓")
						: g.status === "doing"
							? th.fg("accent", "→")
							: th.fg("dim", "○");
				let text: string;
				if (this.mode === "input" && selected) {
					text = this.buf ? th.fg("text", this.buf) : th.fg("dim", "type…");
				} else if (g.status === "done") text = th.fg("dim", g.text);
				else if (g.status === "doing") text = th.bold(th.fg("text", g.text));
				else text = th.fg("muted", g.text);
				lines.push(truncateToWidth(`${indent}${selected ? ">" : " "} ${mark} ${text}`, width));
			});
		}

		if (this.flash) lines.push(th.fg("warning", `  ⚡ ${truncateToWidth(this.flash, Math.max(10, width - 4))}`));
		lines.push(
			truncateToWidth(
				this.mode === "input"
					? th.fg("dim", "  enter save · esc back")
					: th.fg(
							"dim",
							`a sub · g goal · e edit · s doing · d done · u/y/t prio · r rm · c clear-done · q quit`,
						),
				width,
			),
		);

		this.cachedWidth = width;
		this.cachedLines = lines;
		return lines;
	}

	invalidate(): void {
		this.cachedWidth = undefined;
		this.cachedLines = undefined;
	}
}

/* ------------------------------ extension */

export default function (pi: ExtensionAPI) {
	const persistUiEdit = (): void => {
		pi.appendEntry(STATE_ENTRY, snapshot());
	};

	pi.registerTool({
		name: TOOL_NAME,
		label: "Todo",
		description:
			"Plan and track work as goals/sub-goals. Top-level items are big goals; children (parentId) are sub-goals. Exactly one item is 'doing' at a time.",
		promptSnippet: "Plan/track sub-goals: list, add, update status/priority, complete",
		promptGuidelines: [
			"Before non-trivial work, plan with todo: add one top-level goal naming the task plus 3–8 sub-goals under it (add with parentId), then mark the first sub-goal doing.",
			"Keep todo current while working: exactly one item is doing at a time; flip items to done as they finish; use move to reprioritize when the user changes focus.",
		],
		parameters: TodoParams,

		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			let msg = "";
			switch (params.action) {
				case "list":
					break;
				case "add": {
					if (!params.text?.trim()) throw new Error("text required for add");
					const g = addItem(params.text.trim(), params.parentId, params.status);
					msg = `added #${g.id}${g.parentId ? ` under #${g.parentId}` : " (top-level)"}`;
					break;
				}
				case "update": {
					if (params.id === undefined) throw new Error("id required for update");
					const g = goalById(params.id);
					if (!g) throw new Error(`#${params.id} not found`);
					const notes: string[] = [];
					if (params.text?.trim()) {
						g.text = params.text.trim();
						notes.push(`updated #${g.id}`);
					}
					if (params.status) notes.push(setStatus(g.id, params.status));
					msg = notes.join(" · ");
					break;
				}
				case "reparent": {
					if (params.id === undefined) throw new Error("id required for reparent");
					msg = reparentItem(params.id, params.parentId);
					break;
				}
				case "move": {
					if (params.id === undefined) throw new Error("id required for move");
					if (params.pos === undefined && !params.dir) throw new Error("dir or pos required for move");
					msg = moveItem(params.id, params.dir, params.pos);
					break;
				}
				case "remove": {
					if (params.id === undefined) throw new Error("id required for remove");
					msg = removeItem(params.id);
					break;
				}
				case "clearDone":
					msg = clearDone();
					break;
			}

			// Every mutation leaves a durable checkpoint (same as board edits), so
			// state survives compaction/branching even if tool results are gone.
			if (params.action !== "list") persistUiEdit();
			if (ctx.hasUI) refreshUi(ctx);

			const text = msg ? `${msg}\n${boardText()}` : boardText();
			return { content: [{ type: "text", text }], details: snapshot() };
		},

		renderCall(args, theme) {
			let t = theme.fg("toolTitle", theme.bold("todo ")) + theme.fg("muted", args.action);
			if (args.text) t += ` ${theme.fg("dim", `"${truncateToWidth(args.text, 50)}"`)}`;
			if (args.id !== undefined) t += ` ${theme.fg("accent", `#${args.id}`)}`;
			return new Text(t, 0, 0);
		},

		renderResult(result, { expanded }, theme) {
			const d = result.details as TodoState | undefined;
			if (d?.error) return new Text(theme.fg("error", `Error: ${d.error}`), 0, 0);
			const items = d?.items ?? [];
			if (!items.length && !expanded) {
				return new Text(theme.fg("dim", "board empty"), 0, 0);
			}
			let out = progressLine(theme);
			const show = expanded ? items : items.slice(0, 8);
			for (const g of show) out += "\n" + goalLine(theme, g);
			if (!expanded && items.length > 8) out += `\n${theme.fg("dim", `… ${items.length - 8} more`)}`;
			return new Text(out, 0, 0);
		},
	});

	pi.registerCommand("todos", {
		description: "Interactive goal board (or /todos add|do|done|rm …)",
		handler: async (args, ctx) => {
			const arg = args?.trim() ?? "";
			if (!arg) {
				if (ctx.mode !== "tui") {
					ctx.ui.notify("/todos board requires interactive mode", "error");
					return;
				}
				await ctx.ui.custom<void>((tui, theme, _kb, done) => {
					const board = new TodoBoard(theme);
					board.onChanged = () => persistUiEdit();
					board.onClose = () => done();
					return {
						render: (w: number) => board.render(w),
						handleInput: (data: string) => {
							board.handleInput(data);
							tui.requestRender();
						},
						invalidate: () => board.invalidate(),
					};
				});
				refreshUi(ctx);
				return;
			}

			const [cmd, ...rest] = arg.split(/\s+/);
			const restText = rest.join(" ");
			const idNum = Number(rest[0]);
			switch (cmd) {
				case "add": {
					if (!restText.trim()) return ctx.ui.notify("usage: /todos add <text>", "error");
					addItem(restText.trim());
					persistUiEdit();
					refreshUi(ctx);
					ctx.ui.notify(`added #${state.items[state.items.length - 1].id}`, "info");
					break;
				}
				case "do": {
					if (!Number.isFinite(idNum)) return ctx.ui.notify("usage: /todos do <id>", "error");
					setStatus(idNum, "doing");
					persistUiEdit();
					refreshUi(ctx);
					break;
				}
				case "done": {
					if (!Number.isFinite(idNum)) return ctx.ui.notify("usage: /todos done <id>", "error");
					setStatus(idNum, "done");
					persistUiEdit();
					refreshUi(ctx);
					break;
				}
				case "rm": {
					if (!Number.isFinite(idNum)) return ctx.ui.notify("usage: /todos rm <id>", "error");
					removeItem(idNum);
					persistUiEdit();
					refreshUi(ctx);
					break;
				}
				default:
					ctx.ui.notify(
						"usage: /todos | add TEXT | do ID | done ID | rm ID",
						"error",
					);
			}
		},
	});

	pi.on("session_start", (_event, ctx) => {
		reconstruct(ctx);
		refreshUi(ctx);
		if (_event.reason === "startup" && !state.items.length && ctx.hasUI) {
			ctx.ui.notify(
				"todos ready — /todos opens the board; I'll plan sub-goals with it so you can see what I'm working on.",
				"info",
			);
		}
	});

	pi.on("session_tree", (_event, ctx) => {
		reconstruct(ctx);
		refreshUi(ctx);
	});
}
