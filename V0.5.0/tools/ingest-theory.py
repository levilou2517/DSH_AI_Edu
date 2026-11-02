#!/usr/bin/env python3
"""生成理论库的**引证清单**（不复制全文）。

原则：
  * 随包分发的是**提炼后的框架**（framework/）与**短引证**（≤40 字），不是论文全文；
  * 全文属于第三方版权，只留在维护者本机的源库与教师自己的 derived 区；
  * 每条框架论断都要能回指到具体文献与页码，让人可以自行核验。

源：../理论库/{文献,标准}
产物：
  framework/theory/builtin/citations.json   文献登记（标题、页码范围、哈希），不含正文
  framework/theory/builtin/INDEX.md         人读索引
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT.parent / "理论库"
DST = ROOT / "framework" / "theory" / "builtin"
CIT = DST / "citations.json"
PAGE_RE = re.compile(r"<!--\s*p\.(\d+)\s*-->")


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# 正文首个标题若是 PDF 转换残留（纯数字、泛化词），以文件名为准
_GENERIC = {"辽宁师范大学硕士学位论文", "硕士学位论文", "博士学位论文", "目录", "摘要"}


def title_of(md: Path) -> str:
    stem = md.stem
    for line in md.read_text(encoding="utf-8", errors="replace").splitlines()[:12]:
        if line.startswith("# "):
            head = line[2:].strip()
            if re.fullmatch(r"[\d_\-. ]+", head or ""):
                break
            if head in _GENERIC:
                break
            # 文件名比正文标题更长、且正文标题只是泛称时，用文件名
            if len(head) < len(stem) * 0.5:
                break
            return head
    return stem


def main() -> int:
    if not SRC.is_dir():
        print(f"[skip] 源库不存在：{SRC}")
        return 0
    old = {}
    if CIT.is_file():
        for item in json.loads(CIT.read_text(encoding="utf-8")).get("items", []):
            old[item["source_file"]] = item

    items, seq = [], 1
    for group, kind in (("文献", "literature"), ("标准", "standard")):
        d = SRC / group
        if not d.is_dir():
            continue
        for md in sorted(d.glob("*.md")):
            if md.name == "README.md":
                continue
            key = f"{group}/{md.name}"
            prev = old.get(key)
            tid = prev["id"] if prev else f"T-BUILTIN-{seq:03d}"
            if not prev:
                seq += 1
            else:
                # 保证已分配过的编号不再被别的文件占用
                seq = max(seq, int(tid.rsplit("-", 1)[1]) + 1)
            text = md.read_text(encoding="utf-8", errors="replace")
            pages = [int(x) for x in PAGE_RE.findall(text)]
            items.append({
                "id": tid,
                "source": "builtin",
                "group": kind,
                "source_file": key,
                "title": title_of(md),
                "pages": {"count": len(pages), "first": min(pages) if pages else None,
                          "last": max(pages) if pages else None},
                "sha256": sha256(md),
                "full_text_shipped": False,
            })

    present = {i["source_file"] for i in items}
    for key, prev in old.items():
        if key not in present:
            prev["status"] = "missing"
            items.append(prev)

    items.sort(key=lambda i: i["id"])
    DST.mkdir(parents=True, exist_ok=True)
    CIT.write_text(json.dumps({
        "schema": "shiban.theory-citations/1",
        "note": "仅登记文献元数据，不随包分发全文。正文留在维护者源库或教师 derived 区。",
        "items": items,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = ["# 内置理论库 · 引证清单", "",
             f"> 共 {len(items)} 项。**本文件只登记文献，不含全文**；"
             "框架论断通过这些编号回指原文。", "",
             "| 编号 | 标题 | 类别 | 页数 |", "|---|---|---|---|"]
    for i in items:
        flag = " ⚠missing" if i.get("status") == "missing" else ""
        lines.append(f"| `{i['id']}` | {i['title'][:44]}{flag} | {i['group']} | "
                     f"{i['pages']['count']} |")
    (DST / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"登记 {len(items)} 项（不含全文）→ {CIT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
