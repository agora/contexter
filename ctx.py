#!/usr/bin/env python3
import os, sys, re, time, json, subprocess, argparse
from pathlib import Path
from datetime import datetime

ROOT = Path.cwd()
CTX = ROOT / "contexter"
PACKDIR = CTX / "pack"
PLAN = ROOT / "PLAN.md"
CFGFILE = ROOT / "CONTEXTER.yaml"

# ---------- tiny yaml loader (safe-enough for our simple schema) ----------
def load_yaml(p):
    import yaml  # requires pyyaml
    return yaml.safe_load(Path(p).read_text(encoding="utf-8"))

# ---------- utils ----------
def now_iso(): return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
def approx_tokens(chars:int)->int: return max(1, chars//4)
def read(p:Path)->str: return p.read_text(encoding="utf-8", errors="ignore")
def write(p:Path, s:str): p.parent.mkdir(parents=True, exist_ok=True); p.write_text(s, encoding="utf-8")
def rel(p:Path)->str: return str(p.relative_to(ROOT)).replace("\\","/")

def git_branch_commit():
    b = subprocess.run(["git","rev-parse","--abbrev-ref","HEAD"], text=True, capture_output=True).stdout.strip() or "unknown"
    c = subprocess.run(["git","rev-parse","HEAD"], text=True, capture_output=True).stdout.strip() or "unknown"
    return b, c

def latest_touch_ts(paths):
    ts = 0
    for p in paths:
        try:
            t = int(subprocess.run(["git","log","-1","--format=%ct","--",p], text=True, capture_output=True).stdout.strip() or "0")
            ts = max(ts, t)
        except Exception: pass
    return ts

def append_plan(lines):
    PLAN.parent.mkdir(parents=True, exist_ok=True)
    if not PLAN.exists():
        write(PLAN, "# PLAN\n\n## QUESTIONS\n\n## PROGRESS\n")
    with PLAN.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

DEFAULT_DENY = [
    "**/node_modules/**","**/build/**","**/.*/**",
    "**/*.png","**/*.jpg","**/*.jpeg","**/*.gif","**/*.mp4","**/*.mov",
    "**/*.pt","**/*.onnx","**/*.ckpt","**/*.bin","**/*.pb","**/*.so","**/*.dylib"
]
DEFAULT_ALLOW = ["**/*"]  # everything, we’ll still skip outputs automatically

def get_scope(cfg):
    # If scope is missing, supply wide defaults
    scope = cfg.get("scope", {})
    allow = scope.get("allow", DEFAULT_ALLOW)
    deny = scope.get("deny", DEFAULT_DENY)
    return allow, deny

# ---------- filtering ----------
def load_ignores():
    pats=[]
    for n in [".gitignore",".contexterignore"]:
        p=ROOT/n
        if p.exists():
            for ln in read(p).splitlines():
                ln=ln.strip()
                if ln and not ln.startswith("#"): pats.append(ln)
    return pats

def fnmatch(path:str, pats)->bool:
    from fnmatch import fnmatch as _fn
    return any(_fn(path, pat) for pat in pats)

def allowed_files(cfg):
    ignores = load_ignores()
    allow, deny = get_scope(cfg)
    files=[]
    for p in ROOT.rglob("*"):
        if not p.is_file(): continue
        rp = rel(p)
        # Always skip our own outputs and control files
        if rp.startswith("contexter/") or rp.startswith(".contexter/") or rp in {"PLAN.md","CONTEXTER.yaml","ctx.py"}:
            continue
        # deny
        if deny and fnmatch(rp, deny): continue
        if ignores and fnmatch(rp, ignores): continue
        # allow (wildcard by default)
        if not allow or any(fnmatch(rp,[pat]) for pat in allow):
            files.append(rp)
    return files



def denies(pats): return [pats] if isinstance(pats,str) else pats

# ---------- rare facts ----------
def verify_rare_facts(cfg):
    miss=[]
    for k in cfg.get("rare_facts",{}).get("env",[]):
        if os.environ.get(k) is None: miss.append(f"env:{k}")
    def grep_token(tok):
        for p in ROOT.rglob("*"):
            if p.is_file():
                try:
                    if tok in read(p): return True
                except Exception: pass
        return False
    for k in cfg.get("rare_facts",{}).get("flags",[]):
        if not grep_token(k): miss.append(f"flag:{k}")
    for k in cfg.get("rare_facts",{}).get("paths",[]):
        # heuristic: mention in compose/config or folder named similar
        if not any(k in s for s in [" ".join(load_ignores())]) and not grep_token(k):
            miss.append(f"path:{k}")
    return miss

# ---------- secret scrub ----------
SCRUB_PATTERNS = [
    r"(?i)(api[_-]?key)\s*[:=]\s*\S+",
    r"(?i)(secret)\s*[:=]\s*\S+",
    r"(?i)(token)\s*[:=]\s*\S+",
]
def secret_scrub(txt:str):
    out=txt
    for pat in SCRUB_PATTERNS:
        out=re.sub(pat, r"\1: [REDACTED]", out)
    return out

# ---------- deps inference (heuristics, fast) ----------
def infer_deps(path, text, kinds):
    edges=[]
    if "import" in kinds:
        for m in re.finditer(r'^\s*(from\s+([\w\./]+)\s+import|import\s+([\w\./]+))', text, re.M):
            tgt=(m.group(2) or m.group(3) or "").replace(".", "/")
            if tgt: edges.append((path, tgt, "import"))
    if "http" in kinds:
        for m in re.finditer(r'https?://[^\s\'"]+', text): edges.append((path, m.group(0), "http"))
    if "db" in kinds and re.search(r'\b(select|insert|update|delete|from)\b', text, re.I):
        edges.append((path,"db:<unknown>","db"))
    if "queue" in kinds:
        for m in re.finditer(r'\b(publish|enqueue|send)\s*\(\s*["\']([\w\-:]+)["\']', text):
            edges.append((path, f"queue:{m.group(2)}","queue"))
    if "async_call" in kinds and "await" in text:
        for m in re.finditer(r'\bawait\s+(\w+)\s*\(', text): edges.append((path, f"<symbol:{m.group(1)}>","async_call"))
    if "call" in kinds:
        # light: function call tokens; symbolic
        for m in re.finditer(r'\b(\w+)\s*\(', text): edges.append((path, f"<symbol:{m.group(1)}>","call"))
    return edges

# ---------- smart truncation (mid block heuristic) ----------
def largest_span(lines):
    text="\n".join(lines)
    spans=[]
    for m in re.finditer(r'^(def|class|function|export\s+function)\s+[A-Za-z0-9_]+', text, re.M):
        start = text[:m.start()].count("\n")+1
        # naive end: next blank line or file end
        after=text[m.end():]
        offs=after.find("\n\n")
        end = start + (after[:offs].count("\n")+1 if offs!=-1 else len(lines)-start)
        end = max(end, start+10)
        end = min(end, len(lines))
        spans.append((start,end))
    return max(spans, key=lambda xy: xy[1]-xy[0]) if spans else None

# ---------- pack emitter (Markdown only) ----------
def emit_dependencies(md, edges):
    md.append("## DEPENDENCY GRAPH")
    md.append("(import|call|async_call|http|db|queue)")
    seen=set()
    for a,b,k in edges:
        line=f"- {a} -> {b} ({k})"
        if line not in seen:
            md.append(line); seen.add(line)
    md.append("")

def fence(md, lang, start, end, lines):
    code="\n".join(lines[start-1:end])
    md.append(f"#### CODE L{start}-L{end}")
    md.append(f"```{lang}")
    md.append(f"# L{start}-L{end}")
    md.append(code)
    md.append("```")
    md.append("")

def emit_file_section(md, path, lang, lines, cfg, truncated):
    max_lines = cfg["pack"].get("per_file_snippet_lines",180)
    tail_n = cfg["pack"].get("tail_lines_on_truncate",40)
    md.append(f"### FILE path={path} lang={lang}")
    md.append("#### ANCHORS")
    total=len(lines)
    if not truncated:
        end=min(total,max_lines)
        md.append(f"- L1-L{end}"); md.append("")
        fence(md, lang, 1, end, lines)
        return
    # truncated: head + mid + tail (when possible)
    head_end = max(1, min(total, max_lines - tail_n))
    anchors=[(1,head_end)]
    mid=None
    if cfg["pack"].get("mid_block_pick")=="largest_function":
        span=largest_span(lines)
        if span: mid=span; anchors.append(span)
    tail_start = max(1, total - tail_n + 1)
    anchors.append((tail_start,total))
    # unique & sorted
    uniq=[]
    for a in anchors:
        if a not in uniq: uniq.append(a)
    uniq=sorted(uniq, key=lambda x:x[0])
    for a,b in uniq: md.append(f"- L{a}-L{b}")
    md.append("")
    for a,b in uniq: fence(md, lang, a, b, lines)

def write_contextpack_md(files_meta, deps, cfg, totals, truncated):
    b, c = git_branch_commit()
    frontmatter = [
        "---",
        f"version: 1.0",
        f"generated: {totals['generated']}",
        f"encoder: {cfg['budgets']['encoder']}",
        f"token_limit: {cfg['budgets']['token_limit']}",
        f"branch: {b}",
        f"commit: {c}",
        f"limiter: {'truncated' if truncated else cfg['budgets']['limiter']}",
    ]
    links = cfg.get("links",{}).get("repos",[])
    if links:
        frontmatter.append("links:")
        for r in links:
            frontmatter.append(f"  - name: {r['name']}")
            frontmatter.append(f"    pack_uri: {r['pack_uri']}")
    frontmatter.append("---"); frontmatter.append("")

    md = []
    md += frontmatter
    md += ["# CONTEXTPACK","",
           "## SUMMARY",
           f"- Files packed: {totals['files_packed']}",
           f"- Tokens (approx): {totals['tokens_total']}",
           f"- Truncated: {'yes' if truncated else 'no'}",
           '- Policy: no_code_edits=true; abstention="Correct > Abstain >> Confidently wrong"',
           ""]
    if cfg["pack"].get("dependencies",True): emit_dependencies(md, deps)
    md.append("## FILES")
    for meta in files_meta:
        emit_file_section(md, meta["path"], meta["lang"], meta["lines"], cfg, meta["truncated"])
    md += ["## METRICS",
           f"- files_packed: {totals['files_packed']}",
           f"- tokens_total: {totals['tokens_total']}",
           f"- duration_ms: {totals['duration_ms']}",
           f"- truncation_reason: {'over_budget' if truncated else 'none'}",
           "",
           "## NOTES",
           f"- Rare facts verified: {totals['rare_facts']}",
           f"- Human review required: {'yes' if totals.get('coverage',1.0) < cfg['evals']['human_review_if_coverage_below'] else 'no'}",
           f"- Next steps: see PLAN.md",
           ""]
    write(PACKDIR/"CONTEXTPACK.md","\n".join(md))

# ---------- indexing + token budget ----------
def guess_lang(path):
    ext=Path(path).suffix.lower()
    return {"py":"python",".py":"python",".ts":"typescript",".tsx":"tsx",".js":"javascript",".go":"go",
            ".java":"java",".rb":"ruby",".rs":"rust",".php":"php",".cpp":"cpp",".cc":"cpp",".cxx":"cpp",".c":"c"}.get(ext, "")

def build_entries(files, cfg):
    entries=[]; deps=[]; toks_used=0
    kinds=cfg["pack"].get("dependency_kinds",[])
    for rp in files:
        p=ROOT/rp
        txt=secret_scrub(read(p)) if cfg["pack"].get("secret_scrub",True) else read(p)
        lang=guess_lang(rp)
        lines=txt.splitlines()
        # deps
        if kinds: deps.extend(infer_deps(rp, txt, kinds))
        entries.append({"path":rp,"lang":lang,"lines":lines,"content":txt,"truncated":False})
        toks_used += approx_tokens(len(txt))
    return entries, deps, toks_used

def enforce_budget(entries, cfg):
    budget=cfg["budgets"]["token_limit"]
    used=0; truncated_any=False
    # quick pass: if total way over, mark truncation and compute again by content length
    for e in entries:
        size=approx_tokens(len("\n".join(e["lines"])))
        if used + size <= budget:
            used += size
            continue
        e["truncated"]=True; truncated_any=True
    # recompute approximate by counting only kept fences; leave exact to LLM usage time
    return truncated_any

# ---------- evals ----------
def eval_dep_sanity(deps):
    bad=[]
    for a,b,k in deps:
        if k in ("http","db","queue"): continue
        if b.startswith("<symbol:"): continue
        if not (ROOT/ b).exists():
            bad.append((a,b,k))
    return bad

def eval_pack_freshness(files, generated_iso):
    try:
        gen_ts = int(datetime.fromisoformat(generated_iso.replace("Z","")).timestamp())
    except Exception:
        return False
    last_ts = latest_touch_ts(files)
    return gen_ts >= last_ts

# ---------- guard ----------
def guard_no_source_edits():
    changed = subprocess.run(["git","diff","--name-only"], text=True, capture_output=True).stdout.splitlines()
    touched = subprocess.run(["git","ls-files","-m"], text=True, capture_output=True).stdout.splitlines()
    candidates = set(filter(None, changed + touched))
    allowed_prefix=("contexter/",".contexter/")
    allowed_files={"PLAN.md","CONTEXTER.yaml"}
    outside=[c for c in candidates if not c.startswith(allowed_prefix) and c not in allowed_files]
    return outside

# ---------- commands ----------
def cmd_run(args):
    t0=time.time()
    cfg=load_yaml(CFGFILE)
    miss=verify_rare_facts(cfg)
    if miss:
        append_plan(["## QUESTIONS", f"- Rare facts missing: {', '.join(miss)}", "Stopping."]); print("ABSTAIN"); sys.exit(2)

    files=allowed_files(cfg)
    entries,deps,total_toks = build_entries(files, cfg)
    truncated=enforce_budget(entries, cfg) or (total_toks>cfg["budgets"]["token_limit"])
    totals={"generated":now_iso(),"files_packed":len(entries),"tokens_total":total_toks,"duration_ms":0,"rare_facts":"OK"}

    write_contextpack_md(entries, deps, cfg, totals, truncated)

    # evals
    gates_ok=True; notes=[]
    if cfg["evals"].get("dep_sanity",True):
        bad=eval_dep_sanity(deps)
        if bad: gates_ok=False; notes.append(f"dep_sanity failed ({len(bad)})")
    if cfg["evals"].get("pack_freshness",True):
        ok=eval_pack_freshness(files, totals["generated"])
        if not ok: gates_ok=False; notes.append("pack_freshness failed")

    outside=guard_no_source_edits()
    if outside: gates_ok=False; notes.append(f"guard_no_source_edits: {outside[:5]}")

    totals["duration_ms"]=int((time.time()-t0)*1000)
    append_plan(["## PROGRESS",
                 f"- files: {len(entries)}, truncated: {truncated}",
                 f"- deps: {len(deps)}, gates_ok: {gates_ok}",
                 f"- notes: {', '.join(notes) if notes else 'ok'}",
                 f"- wrote: contexter/pack/CONTEXTPACK.md",
                 ""])
    if not gates_ok:
        print("GATE_FAILED"); sys.exit(3)
    print("DONE")

def cmd_watch(args):
    cfg=load_yaml(CFGFILE)
    print("Watching for changes… Ctrl+C to stop.")
    prev = {p: (ROOT/p).stat().st_mtime for p in allowed_files(cfg)}
    try:
        while True:
            time.sleep(2)
            cur = {p: (ROOT/p).stat().st_mtime for p in allowed_files(cfg)}
            changed = [p for p in cur if p not in prev or cur[p]!=prev[p]]
            if changed:
                print("Changed:", ", ".join(changed[:5]), "…")
                cmd_run(args)
            prev=cur
    except KeyboardInterrupt:
        pass

def cmd_hub_build(args):
    cfg=load_yaml(CFGFILE)
    links = cfg.get("links",{}).get("repos",[])
    lines=["# HUB GRAPH"]
    broken=[]
    for r in links:
        uri=r["pack_uri"]
        p=(ROOT/uri).resolve()
        if not p.exists():
            broken.append(uri); continue
        # scan for DEPENDENCY GRAPH lines to stitch simple cross edges (optional simplicity)
        txt=read(p)
        for m in re.finditer(r'^- (.+?) -> (.+?) \((http|queue)\)', txt, re.M):
            lines.append(f"- this:? -> {r['name']}:{m.group(2)} ({m.group(3)})")
    for b in broken:
        lines.append(f"- BROKEN LINK: {b}")
    write(CTX/"hub/graph.md","\n".join(lines))
    print("hub graph written.")

# ---------- cli ----------
def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    sub.add_parser("watch")
    hub=sub.add_parser("hub"); hub.add_argument("action", choices=["build"])
    args=ap.parse_args()
    if args.cmd=="run": cmd_run(args)
    elif args.cmd=="watch": cmd_watch(args)
    elif args.cmd=="hub" and args.action=="build": cmd_hub_build(args)

if __name__=="__main__":
    main()
