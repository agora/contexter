# Contexter

Contexter is a **universal documentation packer** for software repositories.
It creates a **single Markdown file** (`contexter/pack/CONTEXTPACK.md`) that contains:

* **Front-matter**: commit, branch, token budget, generation time.
* **Summary**: file count, tokens, truncation.
* **Dependency Graph**: clean edges like `fileA.py -> fileB.py (import|http|db|queue)`.
* **Files**: per-file anchors (`# Lx–Ly`) with code fences.
* **Metrics/Notes**: token usage, freshness, missing deps (warn), next steps.

This gives Codex or any LLM agent a **compact, navigable, safe context** of your repo — without ever editing source code.

---

## Why

* **Context bloat**: pasting entire repos into an LLM blows token budgets.
* **Hallucinations**: models guess repo-specific facts and get them wrong.
* **Unsafe edits**: without guardrails, agents might touch code they shouldn’t.

Contexter fixes this by:

* Packing the repo into a single **LLM-friendly Markdown file**.
* Guarding against edits outside `/contexter/`, `.contexter/`, `PLAN.md`, `CONTEXTER.yaml`.
* Using **abstention > guessing**: when Codex is unsure, it stops and writes QUESTIONS to `PLAN.md`.

---

## How to Start (Codex + Human)

The easiest way is to start your Codex session with this message:

```
Plan mode. Read https://raw.githubusercontent.com/agora/contexter/refs/heads/main/getting-started.md 
and follow its steps to bootstrap Contexter in this repo. 
Never edit source code; only write to PLAN.md and contexter/. 
When unsure, prepend QUESTIONS to PLAN.md and stop.
```

Codex will:

1. Fetch the **getting-started.md** instructions.
2. Plan safe bootstrap steps in `PLAN.md` (download `ctx.py`, `CONTEXTER.yaml`, etc.).
3. Ask QUESTIONS if anything is unclear.
4. Leave your repo source untouched.

---

## Human Quick Start (manual bootstrap)

From your repo root:

```bash
curl -sSL https://raw.githubusercontent.com/agora/contexter/main/ctx.py -o ctx.py
curl -sSL https://raw.githubusercontent.com/agora/contexter/main/CONTEXTER.yaml -o CONTEXTER.yaml
[ -f PLAN.md ] || printf "# PLAN\n\n## QUESTIONS\n\n## PROGRESS\n" > PLAN.md
chmod +x ctx.py
python3 -m pip install -q pyyaml
python3 ctx.py run
```

This generates:

```
contexter/pack/CONTEXTPACK.md
```

---

## Daily Workflow

* After code changes:

  ```bash
  python3 ctx.py run
  ```

* Codex kickoff message (no IDE required):

  ```
  Plan mode. Use contexter/pack/CONTEXTPACK.md as the context of truth.
  Never edit source code; only write to PLAN.md and contexter/.
  Propose the next 3–5 atomic, verifiable steps with acceptance checks.
  If unsure, add QUESTIONS to PLAN.md and stop.
  ```

* Codex appends **PROGRESS/DECISIONS/NEXT** to `PLAN.md`.

* If blocked, Codex writes QUESTIONS to `PLAN.md` and pauses.

---

## Multi-Repo (optional)

1. Add links in `CONTEXTER.yaml`:

   ```yaml
   links:
     repos:
       - name: frontend
         pack_uri: ../frontend/contexter/pack/CONTEXTPACK.md
   ```
2. Build the hub graph:

   ```bash
   python3 ctx.py hub build
   ```

   → Writes `contexter/hub/graph.md` with cross-repo edges.

---

## Safe by Default

* **No-code-edits** guard: any attempt to change source code is blocked.
* **Secret scrub**: common keys/tokens redacted in packs.
* **Dep sanity**: “warn” mode by default — issues logged in METRICS but won’t block you.

---

## License

MIT © Gudjon Mar Gudjonsson
