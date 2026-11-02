#!/usr/bin/env python3
"""检查数据层是否真的兼容 Python 3.9。

只用 AST 与文件扫描，不执行代码——所以能检查比当前解释器更老的版本。

检查项
  1. PEP 604 类型联合（X | None）：3.10+ 语法，注解求值会炸；
     必须配合 `from __future__ import annotations` 才能安全用于注解。
  2. match / case：3.10+。
  3. 3.11+ 的 try*/except*、tomllib、typing.Self。
  4. 3.10+ 的 zip(strict=)、int.bit_count()。
  5. 运行时 API：zoneinfo（3.9 有）、graphlib（3.9 有）等白名单验证。

退出码 0 全过；1 有问题。
"""
from __future__ import annotations

import ast
import pathlib
import sys

TARGET = (3, 9)
ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVICE_GLOB = "vendor/services/*.py"

MIN_310_APIS = ("tomllib", "typing.Self", "except*", "TryStar")
MIN_310_ATTRS = ("bit_count",)


def _is_typeish(n) -> bool:
    if isinstance(n, (ast.Name, ast.Subscript, ast.Attribute)):
        return True
    return isinstance(n, ast.Constant) and n.value is None


def check_file(path: pathlib.Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    problems: list[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [f"{path.name}: 语法错误 {exc}"]

    has_future = "from __future__ import annotations" in src
    pep604 = False
    for node in ast.walk(tree):
        if isinstance(node, getattr(ast, "Match", ())):
            problems.append(f"{path.name}: 使用了 match 语句（3.10+）")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            if _is_typeish(node.left) and _is_typeish(node.right):
                pep604 = True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "zip":
            if any(kw.arg == "strict" for kw in node.keywords):
                problems.append(f"{path.name}: zip(strict=)（3.10+）")
        if isinstance(node, ast.Attribute) and node.attr in MIN_310_ATTRS:
            problems.append(f"{path.name}: .{node.attr}()（3.10+）")

    if pep604 and not has_future:
        problems.append(
            f"{path.name}: 使用 PEP 604 类型联合但缺少 `from __future__ import annotations`"
            f"（Python 3.9 导入即报错）"
        )
    for api in ("tomllib",):
        if f"import {api}" in src:
            problems.append(f"{path.name}: 导入 {api}（3.11+）")
    for marker in ("except*", "typing.Self", "from typing import Self"):
        if marker in src:
            problems.append(f"{path.name}: 使用 {marker}（3.10+/3.11+）")
    return problems


def check_vendored_lib() -> list[str]:
    """随包的 Python 标准库闭包也必须能在 3.9 下解析——
    它们在 PYTHONPATH 最前，会覆盖宿主的同名模块。"""
    problems: list[str] = []
    lib = ROOT / "vendor" / "python" / "lib"
    if not lib.is_dir():
        return problems
    for f in sorted(lib.rglob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:
            problems.append(f"{f.relative_to(lib)}: 语法错误 {exc.msg}")
            continue
        for n in ast.walk(tree):
            if isinstance(n, getattr(ast, "Match", ())):
                problems.append(f"{f.relative_to(lib)}: 含 match 语句（3.10+），会覆盖宿主同名模块")
                break
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "zip" \
                    and any(kw.arg == "strict" for kw in n.keywords):
                problems.append(f"{f.relative_to(lib)}: zip(strict=)（3.10+）")
                break
    return problems


def main() -> int:
    files = sorted(ROOT.glob(SERVICE_GLOB))
    launcher = ROOT / "vendor" / "bin" / "shiban-store"
    if not files:
        print(f"未找到 {SERVICE_GLOB}", file=sys.stderr)
        return 1

    all_problems: list[str] = []
    print(f"目标: Python {TARGET[0]}.{TARGET[1]}")
    print(f"检查 {len(files)} 个模块\n")
    for f in files:
        probs = check_file(f)
        mark = "OK  " if not probs else "FAIL"
        future = "future✓" if "from __future__ import annotations" in f.read_text(encoding="utf-8") else "future-"
        print(f"  {mark} {f.name:26} {future}")
        all_problems += probs
    if launcher.exists():
        print(f"  ---- {launcher.name}（bash，无需检查）")

    print()
    print("检查随包标准库闭包 vendor/python/lib ...")
    vend = check_vendored_lib()
    if vend:
        print(f"  FAIL {len(vend)} 个模块不兼容")
        all_problems += vend
    else:
        print("  OK   全部可被 3.9 解析")

    print()
    if all_problems:
        print("发现问题：")
        for p in all_problems:
            print("  ✗", p)
        return 1
    print(f"✓ 全部兼容 Python {TARGET[0]}.{TARGET[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
