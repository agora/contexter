# Contexter — Getting Started

**Goal:** produce one LLM-friendly Markdown pack (`contexter/pack/CONTEXTPACK.md`) for any repo, while never touching source code.  
**Needed:** `ctx.py`, `CONTEXTER.yaml`, `PLAN.md`.

## TL;DR

**Codex (start):**
```

Plan mode. Treat contexter/pack/CONTEXTPACK.md as the context of truth.
Never edit source code. Only update PLAN.md and contexter/.
When unsure, add QUESTIONS to PLAN.md and stop.

````

**Human (first run):**
```bash
curl -sSL https://raw.githubusercontent.com/agora/contexter/main/ctx.py -o ctx.py
curl -sSL https://raw.githubusercontent.com/agora/contexter/main/CONTEXTER.yaml -o CONTEXTER.yaml
[ -f PLAN.md ] || printf "# PLAN\n\n## QUESTIONS\n\n## PROGRESS\n" > PLAN.md
chmod +x ctx.py
python3 -m pip install -q pyyaml
python3 ctx.py run
````

## Why this works

* One file to ingest (`CONTEXTPACK.md`) → fewer guesses, faster planning.
* No scope config needed; safe defaults in `ctx.py` skip heavy/hidden/binary paths.
* Dep-sanity is **warn** by default (won’t block you), yet issues show up in METRICS.
* Smart truncation keeps tokens within budget on big repos.

## Daily loop

1. Change code → `python3 ctx.py run`.
2. Tell Codex to propose next 3–5 small steps and append PROGRESS/DECISIONS/NEXT to `PLAN.md`.
3. If anything is unclear, Codex adds QUESTIONS to `PLAN.md` and pauses.

## Multi-repo (optional)

Link neighbor packs in `CONTEXTER.yaml`:

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

Packs only. No MCP or servers required.

````

---

# README.md
```md
# Contexter

**Author:** Gudjon Mar Gudjonsson  
**License:** MIT

Contexter generates a **single, LLM-ready Markdown pack** for any repository.  
It gives AI coding agents (like Codex) a compact, navigable picture of your codebase — with anchors, a dependency graph, and stable snippets — **without touching source code**.

## Why
- Large prompts cause context bloat and drift.
- Agents hallucinate on repo-specific “singleton facts”.
- Teams overcompensate with huge logs or guessy edits.

**Contexter fixes this** by packing the repo into one Markdown file that agents can scan fast, plus a simple plan file agents can update safely.

## What you get
- `contexter/pack/CONTEXTPACK.md`  
  - Front-matter (version, commit, budget).  
  - SUMMARY (file count, token estimate, truncation).  
  - DEPENDENCY GRAPH (import|http|db|queue).  
  - FILES with **anchors** and **code fences**.  
  - METRICS/NOTES (duration, freshness, dep warnings).

- `CONTEXTER.yaml` (repo-agnostic config; no scope needed).  
- `PLAN.md` (Codex writes PROGRESS/QUESTIONS; humans read).

## Quick start
```bash
curl -sSL https://raw.githubusercontent.com/agora/contexter/main/ctx.py -o ctx.py
curl -sSL https://raw.githubusercontent.com/agora/contexter/main/CONTEXTER.yaml -o CONTEXTER.yaml
[ -f PLAN.md ] || printf "# PLAN\n\n## QUESTIONS\n\n## PROGRESS\n" > PLAN.md
chmod +x ctx.py
python3 -m pip install -q pyyaml
python3 ctx.py run
````

## Use with Codex (no IDE required)

```
Plan mode. Use contexter/pack/CONTEXTPACK.md as the context of truth.
Never edit source code; only write to PLAN.md and contexter/.
Propose the next 3–5 atomic steps with acceptance checks.
If unsure, add QUESTIONS to PLAN.md and stop.
```

## Safe by default

* Guard: fails if anything outside `/contexter/`, `.contexter/`, `CONTEXTER.yaml`, `PLAN.md`, `ctx.py` changes.
* Secret scrub: redacts common tokens in pack output.
* Dep sanity: **warn** by default; switch to **strict** when you add path aliases.

## Multi-repo (optional)

Add links in `CONTEXTER.yaml`, then:

```bash
python3 ctx.py hub build
```

## License
MIT © Gudjon Mar Gudjonsson

````

---

## What changed vs before (so you don’t hit blockers again)
- **dep_sanity now “warn”** by default (no hard fail, but reports counts).
- **Path aliases + ignore_targets** let you map package imports to files and ignore externals cleanly.
- **Stable dep kinds** (no function-call heuristics) avoid thousands of false edges.
- **Scope-free defaults** reduce setup to just two files + one command.

You can paste these in now and run:
```bash
python3 ctx.py run
````
