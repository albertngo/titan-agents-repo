---
name: grilling
description: Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.
---

Interview the user relentlessly until you reach a shared understanding. Map this as a **design tree**: every decision branches into the decisions that hang off it.

Work the tree in **rounds**. The **frontier** is every decision whose prerequisites are already settled: the questions you can ask _now_ without guessing at answers you haven't heard yet. Ask the whole frontier in one round, and give your recommended answer on every question. Then wait for the user's answers before the next round.

## Ask with pop-ups, always (Albert, 2026-10-17)

Every question goes through the **`AskUserQuestion` tool** — a pop-up the user clicks — never as a markdown list they have to type answers to. Rules:

- One `AskUserQuestion` call holds at most 4 questions, so a round larger than that is several calls back to back, in frontier order, until the round is spent. Number questions across the whole round (`Q1`…`Q14`), not per call.
- Each question has 2–4 options. **Your recommended answer is the first option, with "(Recommended)" at the end of its label.** The option `description` carries the trade-off, in one or two sentences. The tool adds "Other" by itself — never add one.
- `header` is the question's short title (≤12 chars). The `question` body states the choice and any fact the user needs to make it; it never asks for a fact you could look up.
- Use `multiSelect: true` only when the options are genuinely not exclusive (e.g. "which of these should alarm?").
- Before the first call of a round, write a few lines of chat listing the **facts you found** that the round rests on, so the user reads them once, not inside every pop-up.
- If `AskUserQuestion` is not available in the session, fall back to this markdown form, one block per question:

  ```
  ❓ **Q1** - **<question title>**: <question body, including the choices>

  ➡️ <your recommended answer>
  ```

Each round the user answers reshapes the tree: settled decisions push the frontier outward and unblock questions that depended on them. Recompute the frontier and ask the next round. A question whose answer depends on another question still open in this round belongs to a _later_ round, not this one.

Finding _facts_ is your job, never the user's. When a frontier question needs a fact from the environment (filesystem, tools, etc.), dispatch a sub-agent to find it; don't ask the user for anything you could look up yourself. Don't block on it: a running exploration is an unsettled prerequisite, so only the questions downstream of it wait for the sub-agent to report; ask the rest of the frontier now. The _decisions_ are the user's: put each to them and wait.

The session is done when the frontier is empty: every branch of the design tree visited, nothing left silently assumed. Do not act on it until the user confirms you have reached a shared understanding.
