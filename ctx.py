#!/usr/bin/env python3
"""
Contexter runner — builds a pure-Markdown CONTEXTPACK.md for any repo.

Key improvements:
- Default scope (no config): skips heavy/hidden dirs and large/binary files.
- Dependency sanity modes: off | warn | strict (warn by default).
- Path alias resolver: maps package-like imports to filesystem paths.
- Stable dep kinds (no "call"/"async_call" noise by default).
- Smart truncation: head + largest mid block + tail (anchors preserved).
- Guard: never edits source files — only contexter/, .contexter/, PLAN.md, CONTEXTER.yaml.

Author: Gudjon Mar Gudjonsson
License: MIT
"""
import os, re, sys, time, argparse, subprocess
from pathlib import Path
from datetime import datetime

try:
    import yaml
except ImportError:
    print("PyYAML missing. Run: python3 -m pip install pyyaml", file=sys.stderr)
    sys.exit(1)

ROOT = Path.cwd()
CTX = ROOT / "contexter"
PACKDIR = CTX / "pack"
PLAN = ROOT / "PLAN.md"
CFGFILE = ROOT / "CONTEXTER.yaml"

# --------------------------- small helpers ---------------------------
def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def approx_tokens(chars:int) -> int:
    # conservative rough count good enough for budgeting
    return max(1, chars // 4)

def read(p:Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")

def write(p:Path, s:str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")

def rel(p:Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\","/")

def git_branch_commit():
    b = subprocess.run(["git","rev-parse","--abbrev-ref","HEAD"], text=True, capture_output=True).stdout.strip() or "unknown"
    c = subprocess.run(["git","rev-parse","HEAD"], text=True, capture_output=True).stdout.strip() or "unknown"
    return b, c

def append_plan(lines):
    PLAN.parent.mkdir(parents=True, exist_ok=True)
    if not PLAN.exists():
        write(PLAN, "# PLAN\n\n## QUESTIONS\n\n## PROGRESS\n")
    with PLAN.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

# --------------------------- config & scope ---------------------------
DEFAULT_DENY = [
    "**/node_modules/**","**/build/**","**/.*/**","**/.git/**",
    "**/*.png","**/*.jpg","**/*.jpeg","**/*.gif","**/*.mp4","**/*.mov","**/*.avi","**/*.mkv",
    "**/*.pt","**/*.onnx","**/*.ckpt","**/*.bin","**/*.pb","**/*.so","**/*.dylib","**/*.a","**/*.o",
    "**/*.zip","**/*.tar","**/*.gz","**/*.7z","**/*.pdf","**/*.ico"
]
DEFAULT_ALLOW = ["**/*"]  # include all files; we still apply deny + content checks

BINARY_SNIFF = (
    b"\x00",  # NUL likely indicates binary
)

def load_cfg():
    if not CFGFILE.exists():
        print("CONTEXTER.yaml not found.", file=sys.stderr)
        sys.exit(2)
    return yaml.safe_load(read(CFGFILE)) or {}

def load_ignores():
    pats=[]
    for n in [".gitignore",".contexterignore"]:
        p=ROOT/n
        if p.exists():
            for ln in read(p).splitlines():
                ln=ln.strip()
                if ln and not ln.startswith("#"):
                    pats.append(ln)
    return pats

def fnmatch_any(path:str, patterns) -> bool:
    from fnmatch import fnmatch as _fn
    if not patterns: return False
    if isinstance(patterns, str): patterns=[patterns]
    return any(_fn(path, pat) for pat in patterns)

def get_scope(cfg):
    scope = cfg.get("scope", {})
    allow = scope.get("allow", DEFAULT_ALLOW)
    deny  = scope.get("deny", DEFAULT_DENY)
    return allow, deny

def is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            chunk = f.read(4096)
            if any(b in chunk for b in BINARY_SNIFF): return True
    except Exception:
        return True
    return False

def allowed_files(cfg):
    ignores = load_ignores()
    allow, deny = get_scope(cfg)
    out=[]
    for p in ROOT.rglob("*"):
        if not p.is_file(): continue
        rp = rel(p)
        # Skip our own outputs / control files
        if rp.startswith("contexter/") or rp.startswith(".contexter/") or rp in {"PLAN.md","CONTEXTER.yaml","ctx.py"}:
            continue
        if fnmatch_any(rp, deny): continue
        if ignores and fnmatch_any(rp, ignores): continue
        if is_binary(p): continue
        if any(fnmatch_any(rp, [pat]) for pat in allow): out.append(rp)
    return out

# --------------------------- rare facts ---------------------------
def verify_rare_facts(cfg):
    miss=[]
    rf = cfg.get("rare_facts", {})
    for k in rf.get("env", []):
        if os.environ.get(k) is None:
            miss.append(f"env:{k}")
    # For flags/paths we only verify presence by text hint; stays soft in this runner
    def grep_token(tok):
        for p in ROOT.rglob("*"):
            if p.is_file():
                try:
                    if tok in read(p): return True
                except Exception: pass
        return False
    for k in rf.get("flags", []):
        if not grep_token(k): miss.append(f"flag:{k}")
    for k in rf.get("paths", []):
        if not grep_token(k): miss.append(f"path:{k}")
    return miss

# --------------------------- secret scrub ---------------------------
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

# --------------------------- language & deps ---------------------------
def guess_lang(path:str):
    ext = Path(path).suffix.lower()
    return {
        ".py":"python",".ts":"typescript",".tsx":"tsx",".js":"javascript",".mjs":"javascript",".cjs":"javascript",
        ".cpp":"cpp",".cc":"cpp",".cxx":"cpp",".c":"c",".hpp":"cpp",".hxx":"cpp",".h":"c",
        ".cu":"cuda",".go":"go",".java":"java",".rb":"ruby",".rs":"rust",".php":"php"
    }.get(ext, "")

def apply_aliases(target:str, aliases:list[dict]) -> list[str]:
    # Map import-like targets (e.g., "oz_core.utils") to file paths
    out=[]
    for rule in aliases:
        frm = rule.get("from"); to = rule.get("to")
        if not frm or not to: continue
        try:
            m = re.match(frm, target)
            if m:
                candidate = re.sub(frm, to, target)
                out.append(candidate)
        except re.error:
            continue
    return out or [target]

def infer_deps(path:str, text:str, kinds:list[str], cfg) -> list[tuple[str,str,str]]:
    edges=[]
    if "import" in kinds:
        # Python/JS/TS imports; fast regexes (heuristic)
        for m in re.finditer(r'^\s*from\s+([\w\.\-/@]+)\s+import\b', text, re.M):
            edges.append((path, m.group(1), "import"))
        for m in re.finditer(r'^\s*import\s+([\w\.\-/@]+)', text, re.M):
            edges.append((path, m.group(1), "import"))
        for m in re.finditer(r'^\s*import\s+\{?[ \w,]*\}?\s*from\s*[\'"]([\w\.\-/@]+)[\'"]', text, re.M):
            edges.append((path, m.group(1), "import"))
    if "http" in kinds:
        for m in re.finditer(r'https?://[^\s\'"]+', text):
            edges.append((path, m.group(0), "http"))
    if "db" in kinds and re.search(r'\b(select|insert|update|delete|from)\b', text, re.I):
        edges.append((path, "db:<unknown>", "db"))
    if "queue" in kinds:
        for m in re.finditer(r'\b(publish|enqueue|send|emit|produce)\s*\(\s*["\']([\w\-:./]+)["\']', text):
            edges.append((path, f"queue:{m.group(2)}","queue"))
    return edges

def resolve_dep_target(raw_target:str, cfg) -> list[str]:
    # Apply ignore rules and aliases; return candidate filesystem paths (relative)
    depcfg = cfg.get("deps", {})
    ignores = [re.compile(p) for p in depcfg.get("ignore_targets", [])]
    for rx in ignores:
        if rx.search(raw_target): return []  # ignored target

    candidates = apply_aliases(raw_target, depcfg.get("path_aliases", []))
    # Try common file endings for code
    expanded=[]
    for c in candidates:
        c = c.strip("/.")
        if not c: continue
        # If likely a URL or external, skip
        if c.startswith("http"): continue
        # Candidate folders and files:
        expanded += [
            c,
            f"{c}.py", f"{c}.ts", f"{c}.tsx", f"{c}.js",
            f"{c}/__init__.py", f"{c}/index.ts", f"{c}/index.tsx", f"{c}/index.js",
            f"{c}.cpp", f"{c}.hpp", f"{c}.cc", f"{c}.cxx", f"{c}.c", f"{c}.h",
            f"{c}.cu",
        ]
    # Deduplicate but preserve order
    seen=set(); final=[]
    for e in expanded:
        if e not in seen:
            final.append(e); seen.add(e)
    return final

# --------------------------- smart truncation ---------------------------
def largest_span(lines:list[str]):
    text="\n".join(lines)
    spans=[]
    for m in re.finditer(r'^(def|class|function|export\s+function)\s+[A-Za-z0-9_]+', text, re.M):
        start = text[:m.start()].count("\n")+1
        after=text[m.end():]
        # naive end: next blank or file end
        offs = after.find("\n\n")
        end  = start + (after[:offs].count("\n")+1 if offs!=-1 else len(lines)-start)
        end  = max(end, start+8); end = min(end, len(lines))
        spans.append((start,end))
    return max(spans, key=lambda xy: xy[1]-xy[0]) if spans else None

def fence(md:list[str], lang:str, start:int, end:int, lines:list[str]):
    code="\n".join(lines[start-1:end])
    md.append(f"#### CODE L{start}-L{end}")
    md.append(f"```{lang}")
    md.append(f"# L{start}-L{end}")
    md.append(code)
    md.append("```")
    md.append("")

def emit_file_section(md, path, lang, lines, cfg, truncated):
    max_lines = cfg["pack"].get("per_file_snippet_lines",180)
    tail_n    = cfg["pack"].get("tail_lines_on_truncate",40)
    md.append(f"### FILE path={path} lang={lang}")
    md.append("#### ANCHORS")
    total=len(lines)
    if not truncated:
        end=min(total,max_lines)
        md.append(f"- L1-L{end}"); md.append("")
        fence(md, lang, 1, end, lines)
        return
    head_end = max(1, min(total, max_lines - tail_n))
    anchors=[(1,head_end)]
    if cfg["pack"].get("mid_block_pick")=="largest_function":
        span=largest_span(lines)
        if span: anchors.append(span)
    tail_start = max(1, total - tail_n + 1)
    anchors.append((tail_start,total))
    # unique + sorted
    uniq=[]
    for a in anchors:
        if a not in uniq: uniq.append(a)
    uniq=sorted(uniq, key=lambda x:x[0])
    for a,b in uniq: md.append(f"- L{a}-L{b}")
    md.append("")
    for a,b in uniq: fence(md, lang, a, b, lines)

def emit_dependencies(md, edges):
    md.append("## DEPENDENCY GRAPH")
    md.append("(import|http|db|queue)")
    seen=set()
    for a,b,k in edges:
        line=f"- {a} -> {b} ({k})"
        if line not in seen:
            md.append(line); seen.add(line)
    md.append("")

# --------------------------- build process ---------------------------
def build_entries(files:list[str], cfg):
    entries=[]; deps=[]; total_chars=0
    kinds = cfg["pack"].get("dependency_kinds", [])
    for rp in files:
        p=ROOT/rp
        try:
            txt=read(p)
        except Exception:
            continue
        if cfg["pack"].get("secret_scrub",True):
            txt=secret_scrub(txt)
        lang=guess_lang(rp)
        lines=txt.splitlines()
        if kinds:
            deps.extend(infer_deps(rp, txt, kinds, cfg))
        entries.append({"path":rp,"lang":lang,"lines":lines,"truncated":False})
        total_chars += len(txt)
    return entries, deps, approx_tokens(total_chars)

def enforce_budget(entries, cfg):
    budget=cfg["budgets"]["token_limit"]
    # simple linear pass: mark over-budget files as truncated
    used=0; truncated_any=False
    for e in entries:
        # assume full content cost if not truncated yet
        est = approx_tokens(len("\n".join(e["lines"])))
        if used + est <= budget:
            used += est
            continue
        e["truncated"]=True; truncated_any=True
    return truncated_any

def dep_sanity_check(edges, cfg):
    mode = (cfg.get("deps", {}).get("sanity_mode") or "warn").lower()
    if mode == "off": return True, []
    missing=[]
    for a,b,k in edges:
        # external edges are OK
        if k in ("http","db","queue"): continue
        # map package-like target to candidate files
        candidates = resolve_dep_target(b, cfg)
        exists = any((ROOT/c).exists() for c in candidates)
        if not exists:
            missing.append((a,b,k))
    if mode == "strict":
        return len(missing)==0, missing
    # warn
    return True, missing

def eval_pack_freshness(files, generated_iso):
    try:
        gen_ts = int(datetime.fromisoformat(generated_iso.replace("Z","")).timestamp())
    except Exception:
        return True
    last_touch=0
    for rp in files:
        out = subprocess.run(["git","log","-1","--format=%ct","--",rp], text=True, capture_output=True)
        try:
            t = int(out.stdout.strip() or "0")
            last_touch=max(last_touch, t)
        except Exception:
            pass
    return gen_ts >= last_touch

def guard_no_source_edits():
    changed = subprocess.run(["git","diff","--name-only"], text=True, capture_output=True).stdout.splitlines()
    touched = subprocess.run(["git","ls-files","-m"], text=True, capture_output=True).stdout.splitlines()
    candidates = set(filter(None, changed + touched))
    allowed_prefix=("contexter/",".contexter/")
    allowed_files={"PLAN.md","CONTEXTER.yaml","ctx.py"}
    outside=[c for c in candidates if not c.startswith(allowed_prefix) and c not in allowed_files]
    return outside

# --------------------------- emit CONTEXTPACK.md ---------------------------
def write_contextpack_md(entries, deps, cfg, totals, truncated):
    b, c = git_branch_commit()
    fm = [
        "---",
        "version: 1.0",
        f"generated: {totals['generated']}",
        f"encoder: {cfg['budgets']['encoder']}",
        f"token_limit: {cfg['budgets']['token_limit']}",
        f"branch: {b}",
        f"commit: {c}",
        f"limiter: {'truncated' if truncated else cfg['budgets']['limiter']}",
    ]
    links = cfg.get("links",{}).get("repos",[])
    if links:
        fm.append("links:")
        for r in links:
            fm.append(f"  - name: {r['name']}")
            fm.append(f"    pack_uri: {r['pack_uri']}")
    fm.append("---"); fm.append("")

    md=[]
    md += fm
    md += ["# CONTEXTPACK","",
           "## SUMMARY",
           f"- Files packed: {totals['files_packed']}",
           f"- Tokens (approx): {totals['tokens_total']}",
           f"- Truncated: {'yes' if truncated else 'no'}",
           '- Policy: no_code_edits=true; abstention="Correct > Abstain >> Confidently wrong"',
           ""]
    if cfg["pack"].get("dependencies",True):
        emit_dependencies(md, deps)
    md.append("## FILES")
    for e in entries:
        emit_file_section(md, e["path"], e["lang"], e["lines"], cfg, e["truncated"])
    md += ["## METRICS",
           f"- files_packed: {totals['files_packed']}",
           f"- tokens_total: {totals['tokens_total']}",
           f"- duration_ms: {totals['duration_ms']}",
           f"- truncation_reason: {'over_budget' if truncated else 'none'}",
           ""]
    if totals.get("dep_missing_count") is not None:
        md.append(f"- dep_missing (warn): {totals['dep_missing_count']}")
    if totals.get("fresh_ok") is not None:
        md.append(f"- fresh_since_last_commit: {'yes' if totals['fresh_ok'] else 'no'}")
    md.append("")
    md += ["## NOTES",
           "- Use CONTEXTPACK as the context of truth.",
           "- Re-run `python3 ctx.py run` after meaningful code changes.",
           ""]
    write(PACKDIR/"CONTEXTPACK.md","\n".join(md))

# --------------------------- commands ---------------------------
def cmd_run(args):
    t0=time.time()
    cfg=load_cfg()

    # rare facts
    miss=verify_rare_facts(cfg)
    if miss:
        append_plan(["## QUESTIONS", f"- Missing rare facts: {', '.join(miss)}", "Stopping."])
        print("ABSTAIN (rare_facts missing)")
        sys.exit(2)

    files=allowed_files(cfg)
    entries,deps,total_toks = build_entries(files, cfg)
    truncated = enforce_budget(entries, cfg) or (total_toks > cfg["budgets"]["token_limit"])

    totals={"generated":now_iso(),"files_packed":len(entries),"tokens_total":total_toks}

    # dependency sanity
    ok_deps, missing = dep_sanity_check(deps, cfg)
    totals["dep_missing_count"] = len(missing) if missing else 0

    # freshness
    fresh_ok = True
    if cfg.get("evals",{}).get("pack_freshness", True):
        fresh_ok = eval_pack_freshness(files, totals["generated"])
    totals["fresh_ok"] = fresh_ok

    # write the pack regardless (so Codex has context)
    write_contextpack_md(entries, deps, cfg, totals, truncated)

    gates_ok = ok_deps and fresh_ok
    totals["duration_ms"]=int((time.time()-t0)*1000)
    append_plan([
        "## PROGRESS",
        f"- files: {len(entries)}, deps: {len(deps)}, dep_missing: {totals['dep_missing_count']}, fresh: {fresh_ok}",
        f"- truncated: {truncated}, tokens_total: {total_toks}, duration_ms: {totals['duration_ms']}",
        f"- wrote: contexter/pack/CONTEXTPACK.md",
        ""
    ])

    # guard
    outside = guard_no_source_edits()
    if outside:
        print("GATE_FAILED (guard_no_source_edits):", outside[:5])
        sys.exit(3)

    # dep sanity strictly enforced only if mode=strict
    if not gates_ok and (cfg.get("deps",{}).get("sanity_mode","warn").lower()=="strict"):
        print("GATE_FAILED (deps or freshness)")
        sys.exit(3)

    print("DONE")

def cmd_watch(args):
    cfg=load_cfg()
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
    cfg=load_cfg()
    links = cfg.get("links",{}).get("repos",[])
    lines=["# HUB GRAPH"]
    broken=[]
    for r in links:
        uri=r["pack_uri"]
        p=(ROOT/uri).resolve()
        if not p.exists():
            broken.append(uri); continue
        txt=read(p)
        for m in re.finditer(r'^- (.+?) -> (.+?) \((http|queue)\)', txt, re.M):
            lines.append(f"- this:? -> {r['name']}:{m.group(2)} ({m.group(3)})")
    for b in broken:
        lines.append(f"- BROKEN LINK: {b}")
    write(CTX/"hub/graph.md","\n".join(lines))
    print("hub graph written.")

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
