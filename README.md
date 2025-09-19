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
