#!/usr/bin/env python3
"""把 CLI 依赖的标准库闭包复制进 vendor/python/lib。

用途：用户机器没有 Python、或 Python 版本不一致时，插件仍能运行。
本脚本需要在一个能跑通的 Python 上执行（构建期执行一次，产物随包分发）。

用法：
    python3 tools/vendor-python.py            # 生成 vendor/python/lib
    python3 tools/vendor-python.py --check    # 只检查是否已生成
"""
import json
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "vendor" / "services"
DST = ROOT / "vendor" / "python" / "lib"

# 无论追踪结果如何都必须带的包
ALWAYS = ("encodings", "json", "re", "sqlite3", "hashlib", "os", "io")

TRACKER = r"""
import json, os, sys
sys.path.insert(0, os.environ["SV"])
for m in ("shiban_cli", "shiban_core", "shiban_corpus", "shiban_asset", "shiban_lesson"):
    __import__(m)
names = sorted({m.split(".")[0] for m in sys.modules
                if m.split(".")[0] in sys.stdlib_module_names})
print(json.dumps(names))
"""


def closure() -> list[str]:
    out = subprocess.run([sys.executable, "-c", TRACKER], capture_output=True, text=True,
                         env={**os.environ, "SV": str(SERVICES)})
    if out.returncode != 0:
        raise SystemExit(f"依赖追踪失败：{out.stderr[-400:]}")
    return sorted(set(json.loads(out.stdout)) | set(ALWAYS))


def build() -> int:
    std = sysconfig.get_paths()["stdlib"]
    if DST.exists():
        shutil.rmtree(DST)
    DST.mkdir(parents=True)
    mods = closure()
    copied = 0
    for name in mods:
        pkg = os.path.join(std, name)
        if os.path.isdir(pkg):
            shutil.copytree(pkg, DST / name,
                            ignore=shutil.ignore_patterns("__pycache__", "test", "tests",
                                                          "idlelib", "tkinter", "turtledemo"))
            copied += 1
        elif os.path.isfile(pkg + ".py"):
            shutil.copy2(pkg + ".py", DST / f"{name}.py")
            copied += 1
    size = sum(f.stat().st_size for f in DST.rglob("*") if f.is_file())
    (ROOT / "vendor" / "python" / "MANIFEST.json").write_text(json.dumps({
        "python": sys.version.split()[0],
        "modules": mods,
        "files": copied,
        "bytes": size,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已生成 {DST}：{copied} 个模块，{size/1024/1024:.1f} MB")
    return 0


def check() -> int:
    man = ROOT / "vendor" / "python" / "MANIFEST.json"
    if not man.is_file():
        print("未生成（将回退到系统 Python）")
        return 1
    info = json.loads(man.read_text(encoding="utf-8"))
    print(f"已生成：python {info['python']}，{info['files']} 个模块，"
          f"{info['bytes']/1024/1024:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv else build())
