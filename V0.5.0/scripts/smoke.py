#!/usr/bin/env python3
"""轻量冒烟：每个模块跑一次最小路径，写可追溯记录。

用法： python3 scripts/smoke.py
产物： $SHIBAN_ROOT/logs/smoke-<时间>.jsonl   （一行一个模块结果）
退出码：0 全部 OK；1 有失败。
"""
import json, os, subprocess, sys, tempfile, time, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SV = ROOT / "vendor" / "services"
MODULES = ["shiban_core", "shiban_corpus", "shiban_asset", "shiban_lesson"]
CLI = SV / "shiban_cli.py"

def run(cmd, root, timeout=120):
    env = dict(os.environ, SHIBAN_ROOT=root, PYTHONIOENCODING="utf-8")
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return {"ok": p.returncode == 0, "code": p.returncode,
                "out": (p.stdout or "").strip()[-400:], "err": (p.stderr or "").strip()[-400:],
                "ms": int((time.time() - t0) * 1000)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": -1, "out": "", "err": "timeout", "ms": timeout * 1000}

def main():
    stamp = time.strftime("%Y%m%dT%H%M%S")
    root = tempfile.mkdtemp(prefix=f"shiban-smoke-{stamp}-")
    logdir = Path(root) / "logs"; logdir.mkdir(parents=True, exist_ok=True)
    log = logdir / f"smoke-{stamp}.jsonl"
    results, failed = [], 0

    steps = [("init", [sys.executable, str(CLI), "init"]),
             ("doctor", [sys.executable, str(CLI), "doctor"])]
    for name, cmd in steps:
        r = run(cmd, root); r["step"] = name; results.append(r)
        failed += 0 if r["ok"] else 1

    for mod in MODULES:
        f = SV / f"{mod}.py"
        if not f.exists():
            results.append({"step": mod, "ok": None, "skipped": "文件不存在"}); continue
        r = run([sys.executable, str(f)], root); r["step"] = mod + ".selftest"
        results.append(r); failed += 0 if r["ok"] else 1

    with log.open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps({"at": stamp, **r}, ensure_ascii=False) + "\n")

    width = max(len(r["step"]) for r in results)
    for r in results:
        state = "OK " if r["ok"] else ("SKIP" if r.get("ok") is None else "FAIL")
        print(f"  {state}  {r['step']:<{width}}  {r.get('ms','')}ms  {r.get('err','')[:80]}")
    print(f"\n记录：{log}")
    print(f"汇总：{len(results)} 步，失败 {failed}")
    shutil.rmtree(root, ignore_errors=True)
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
