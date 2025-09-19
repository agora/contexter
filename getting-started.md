# Contexter — Getting Started

**Goal:** create a single, LLM-friendly Markdown pack (`contexter/pack/CONTEXTPACK.md`) for any repo, while never touching source code.
**You only need:** `ctx.py`, `CONTEXTER.yaml`, `PLAN.md`.

---

## TL;DR

**Codex (start every session):**

```
Plan mode. Treat contexter/pack/CONTEXTPACK.md as the context of truth.
Never edit source code. Only update PLAN.md.
When unsure, add QUESTIONS to PLAN.md and stop.
```

**Human (first run in any repo):**

```bash
# From the repo root
curl -sSL https://raw.githubusercontent.com/agora/contexter/main/ctx.py -o ctx.py
curl -sSL https://raw.githubusercontent.com/agora/contexter/main/CONTEXTER.yaml -o CONTEXTER.yaml
[ -f PLAN.md ] || curl -sSL https://raw.githubusercontent.com/agora/contexter/main/PLAN.md -o PLAN.md
chmod +x ctx.py
python3 -m pip install -q pyyaml
python3 ctx.py run
```

This writes `contexter/pack/CONTEXTPACK.md`. Point Codex at it and begin the **plan → execute → sync** loop.

---

## Why this method (5-Whys compressed)

* **Why pack one file?** So the agent reads less and guesses less.
* **Why Markdown?** It’s simple, compact, and parsed well by LLMs.
* **Why two human files?** Less setup, less drift: `CONTEXTER.yaml` for policy, `PLAN.md` for progress.
* **Why never edit source?** Safety. Docs evolve without risking code.
* **Why abstain when unsure?** It stops confident wrong changes and forces clear QUESTIONS.

---

## 1) Prerequisites

* Python 3.9+ (3.10+ recommended)
* `pip install pyyaml`
* `curl` (or PowerShell `iwr` on Windows)

---

## 2) Bootstrap in any repo (human)

**macOS/Linux:**

```bash
curl -sSL https://raw.githubusercontent.com/agora/contexter/main/ctx.py -o ctx.py
curl -sSL https://raw.githubusercontent.com/agora/contexter/main/CONTEXTER.yaml -o CONTEXTER.yaml
[ -f PLAN.md ] || curl -sSL https://raw.githubusercontent.com/agora/contexter/main/PLAN.md -o PLAN.md
chmod +x ctx.py
python3 -m pip install -q pyyaml
python3 ctx.py run
```

**Windows PowerShell:**

```powershell
iwr https://raw.githubusercontent.com/agora/contexter/main/ctx.py -OutFile ctx.py
iwr https://raw.githubusercontent.com/agora/contexter/main/CONTEXTER.yaml -OutFile CONTEXTER.yaml
if (!(Test-Path PLAN.md)) { iwr https://raw.githubusercontent.com/agora/contexter/main/PLAN.md -OutFile PLAN.md }
python -m pip install pyyaml
python ctx.py run
```

> For deterministic CI, replace `main` with a tag or commit SHA.

---

## 3) Use with Codex (no IDE needed)

**Kickoff message to Codex:**

```
Plan mode. Use contexter/pack/CONTEXTPACK.md as the context of truth.
Never edit source code; only write to PLAN.md and contexter/.
Propose the next 3–5 atomic, verifiable steps with acceptance checks.
If any fact is missing, prepend QUESTIONS to PLAN.md and pause.
After each 3–5 steps: append PROGRESS/DECISIONS/NEXT to PLAN.md.
```

**Loop:**

1. Codex reads `CONTEXTPACK.md` (SUMMARY + DEPENDENCY GRAPH).
2. Codex updates `PLAN.md` with small steps.
3. You run the commands it proposes (e.g., `python3 ctx.py run`).
4. Codex appends PROGRESS/DECISIONS/NEXT to `PLAN.md`.
5. Repeat.

**Stop when unsure:** Codex adds **QUESTIONS** at the top of `PLAN.md` and pauses.

---

## 4) What gets generated

* `contexter/pack/CONTEXTPACK.md`

  * **Front-matter:** version, time, branch, commit, encoder, token limit, limiter.
  * **SUMMARY:** file count, token estimate, truncated status.
  * **DEPENDENCY GRAPH:** lines like `A -> B (import|call|async_call|http|db|queue)`.
  * **FILES:** per file → **ANCHORS** + **CODE** fences (`# Lx–Ly`).
  * **METRICS/NOTES:** gates, duration, next steps.

---

## 5) Config is general (no scope lists)

The default `CONTEXTER.yaml` is repo-agnostic. No `scope:` required.
`ctx.py` skips heavy/hidden paths by default and supports many languages via `languages:` hints.

You can add rare facts later (only if you want strict checks):

```yaml
rare_facts:
  env: ["DB_URL"]        # needed env keys
  flags: ["FEATURE_X"]   # repo constants that must exist
  paths: ["DATA_DIR"]    # required paths
```

If a listed fact is missing, the run abstains and Codex must add **QUESTIONS** to `PLAN.md`.

---

## 6) Keep it fresh

**Manual:**

```bash
python3 ctx.py run
```

**Auto-watch (local):**

```bash
python3 ctx.py watch
```

**CI idea:** on push to `main`, run `python3 ctx.py run`. Upload `contexter/pack/CONTEXTPACK.md` as an artifact or commit it to a docs branch.

---

## 7) Multi-repo (no servers, no MCP)

When another repo has a `CONTEXTPACK.md`, link it in `CONTEXTER.yaml`:

```yaml
links:
  repos:
    - name: frontend
      pack_uri: ../frontend/contexter/pack/CONTEXTPACK.md
```

Then:

```bash
python3 ctx.py hub build
```

This writes `contexter/hub/graph.md` with simple cross-repo edges.

---

## 8) Guardrails and gates

* **No-code-edits:** fails if anything outside `/contexter/`, `.contexter/`, `CONTEXTER.yaml`, `PLAN.md` changes.
* **Token budget:** flips to `truncated` (head/mid/tail) when over limit.
* **Dep sanity & freshness:** pack must be newer than latest code change; deps must be sane.
* **Human review hint:** if coverage below your threshold, NOTES flags it.

---

## 9) Troubleshooting

* Pack missing → confirm Python + PyYAML, and you’re at repo root.
* “GATE\_FAILED” → open `PLAN.md` → PROGRESS; ask Codex to add QUESTIONS and suggest a smaller next step.
* Pack large → let `limiter: truncated` keep head/mid/tail or lower `token_limit`.
* Sensitive strings → secret scrub is on; keep high-risk files out of the repo if needed.

---

## 10) Upgrade the runner

Refresh `ctx.py` and `CONTEXTER.yaml`, keep `PLAN.md`:

```bash
curl -sSL https://raw.githubusercontent.com/agora/contexter/main/ctx.py -o ctx.py
curl -sSL https://raw.githubusercontent.com/agora/contexter/main/CONTEXTER.yaml -o CONTEXTER.yaml
chmod +x ctx.py
python3 ctx.py run
```

---

**Done.**
Two human files (`CONTEXTER.yaml`, `PLAN.md`).
One command (`python3 ctx.py run`).
One pack (`contexter/pack/CONTEXTPACK.md`) for Codex to work fast and safely.
