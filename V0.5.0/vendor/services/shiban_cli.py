#!/usr/bin/env python3
"""shiban-store — 师伴命令行入口（v0.5.0）。

一条通路：Agent 与脚本只经本 CLI 访问数据；不直接编辑 $SHIBAN_ROOT 下的文件。

  shiban-store init | doctor | version
  shiban-store artifact put|get|list|confirm|discard|archive|stale|section
  shiban-store ctx pack --for <原子> ...
  shiban-store corpus import|list|search|read|verify|remove
  shiban-store asset import|list|get|reuse|compose|suggest|triage
  shiban-store lesson validate|render|template
  shiban-store evidence save|list|read
  shiban-store graph

退出码：0 成功；2 输入/校验错误；1 未预期异常。
所有输出为 UTF-8 JSON（--human 换成人读摘要）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Windows/中文 locale 下 stdout 默认是 GBK，会被按 UTF-8 解析的上游打断。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass

import shiban_core as core  # noqa: E402
from shiban_core import ShibanError  # noqa: E402

VERSION_FILE = HERE.parent.parent / "VERSION"


def _version() -> str:
    """版本唯一真源是 package.json；VERSION 文件为便于人读的镜像。"""
    return core.package_meta()["version"]


def _load_json_arg(value: str | None, flag: str) -> dict:
    """接受行内 JSON、@文件、或 - 表示 stdin。"""
    if value is None:
        return {}
    if value == "-":
        text = sys.stdin.read()
    elif value.startswith("@"):
        text = Path(value[1:]).read_text(encoding="utf-8")
    else:
        text = value
    if not text.strip():
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ShibanError("bad_json", f"{flag} 不是合法 JSON：{exc.msg}（第 {exc.lineno} 行）")
    if not isinstance(parsed, dict):
        raise ShibanError("bad_json", f"{flag} 必须是 JSON 对象")
    return parsed


def _emit(obj, human: bool = False, label: str = "") -> None:
    if human:
        _human(obj, label)
        return
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def _human(obj, label: str = "") -> None:
    """极简人读输出：列表显示为一行一条，其他退回紧凑 JSON。"""
    if label:
        print(label)
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        for row in obj:
            ident = row.get("id") or row.get("name") or row.get("asset_id") or row.get("corpus_id") or ""
            rest = " ".join(
                f"{k}={row[k]}" for k in ("kind", "status", "rev", "topic", "title")
                if row.get(k) not in (None, "", [])
            )
            print(f"  {ident}  {rest}".rstrip())
        print(f"  （共 {len(obj)} 条）")
        return
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- #
# ctx pack 配方
# --------------------------------------------------------------------------- #

def _recipe_dir() -> Path:
    """配方随包：framework/ctx-recipes/；教师可在 $SHIBAN_ROOT/recipes/ 覆盖。"""
    override = Path(core.root()) / "recipes"
    if override.is_dir():
        return override
    return HERE.parent.parent / "framework" / "ctx-recipes"


def _pack(atom: str, extra: dict) -> dict:
    """按配方组装上下文包：返回"恰好够用"的一份 JSON。"""
    scope = extra.get("scope")
    lesson_id = extra.get("lesson")
    limit = int(extra.get("limit") or 5)

    pack: dict = {"for": atom, "root": core.root(), "version": _version()}

    # 1) 教师偏好（所有原子都带）。只认 payload.kind=="preference" 或未声明 kind 的条目；
    #    class-profile 留下的画像条目（kind="class_profile"）走 profile 字段，不混进偏好。
    pref_items, profile_items = [], []
    for art in core.list_artifacts(kind="pref", status="confirmed"):
        detail = core.get(art["id"], "full") or {}
        for item in ((detail.get("payload") or {}).get("preferences") or []):
            if item.get("kind") == "class_profile":
                profile_items.append(item)
            else:
                pref_items.append(item)
    if pref_items:
        pack["preferences"] = pref_items
    if profile_items:
        pack["profile"] = {"source": "pref", "entries": profile_items}

    # 2) 输入产物
    if lesson_id:
        env = core.get(lesson_id, "full")
        if env is None:
            raise ShibanError("not_found", f"教案不存在：{lesson_id}",
                              "先用 artifact list --kind les 查现有 id。")
        if atom in ("quiz", "class-eval"):
            # 只给下游需要的结构，不给整份正文
            payload = env.get("payload") or {}
            pack["lesson"] = {
                "id": env.get("id"),
                "topic": (env.get("subject_line") or {}).get("topic"),
                "objectives": payload.get("S4") or [],
                "scaffolds": [
                    {"no": s.get("no"), "name": s.get("name"), "minutes": s.get("minutes"),
                     "intent": s.get("intent")}
                    for s in (payload.get("S8") or [])
                ],
                "citations": env.get("citations") or [],
            }
        else:
            pack["lesson"] = core.get(lesson_id, "digest")

    # 3) 语料命中
    if extra.get("kw"):
        try:
            import shiban_corpus as corpus
            pack["corpus"] = corpus.search(extra["kw"], corpus_id=extra.get("corpus"),
                                           limit=limit)
        except ImportError:
            pack["corpus"] = []
            pack.setdefault("degrade", []).append(
                {"what": "corpus", "reason": "corpus 模块不可用"})

    # 4) 历史遗留（上次未消费的建议与待办）
    carry = []
    for kind in ("mev", "ev"):
        for item in core.list_artifacts(kind=kind, scope=scope) if scope else []:
            full = core.get(item["id"], "full") or {}
            payload = full.get("payload") or {}
            for cand in payload.get("scaffold_candidates_for_next_lesson") or []:
                carry.append({"from": item["id"], "type": "scaffold_candidate",
                              "summary": cand.get("scaffold_type") or cand.get("level_gap"),
                              "status": "not_used"})
            for todo in payload.get("todos") or []:
                if todo.get("status") != "done":
                    carry.append({"from": item["id"], "type": "todo",
                                  "text": todo.get("text"), "status": todo.get("status")})
    if carry:
        pack["carry_over"] = carry[:20]

    # 5) 已有素材（先查后建）
    if extra.get("kp"):
        try:
            import shiban_asset as asset
            pack["assets"] = asset.suggest(knowledge_point=extra["kp"], limit=limit)
        except ImportError:
            pass

    # 6) 理论依据：只给框架文件名与关键引证编号，不给正文（控制体积）
    try:
        import shiban_theory as theory
        recipe_path = _recipe_dir() / f"{atom}.json"
        wanted = []
        if recipe_path.is_file():
            try:
                wanted = (json.loads(recipe_path.read_text(encoding="utf-8"))
                          .get("theory", {}).get("digests") or [])
            except ValueError:
                wanted = []
        if wanted:
            pack["theory"] = {
                "digests": [
                    {"file": f"framework/theory/builtin/digests/{n}",
                     "read_with": f"shiban-store theory explain --file {n}"}
                    for n in wanted
                ],
                "stats": theory.stats(),
                "hint": "断言理论依据必须带页码：theory cite --id <编号> --page <页>。"
                        "不要凭记忆写页码；标〔推断〕的不是文献结论。",
            }
    except ImportError:
        pass

    # 7) 配方本身（字段说明，供 Agent 对照）
    recipe = _recipe_dir() / f"{atom}.json"
    if recipe.is_file():
        try:
            pack["recipe"] = json.loads(recipe.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    if not pack.get("corpus"):
        pack.setdefault("degrade", []).append(
            {"what": "corpus", "reason": "未导入语料或未命中，引用不得编造页码",
             "affects": ["citations"]})
    return pack


# --------------------------------------------------------------------------- #
# 命令实现
# --------------------------------------------------------------------------- #

def cmd_init(args) -> dict:
    layout = core.ensure_layout()
    out = {"ok": True, "version": _version(), "root": layout["root"]}
    if layout.get("_restock"):
        out["notice"] = "载体版本与运行时不一致，已重写载体重建表。"
    return out


def cmd_doctor(args) -> dict:
    """环境自检：数据根可写、sqlite 版本与 FTS5、python、可选工具。"""
    import sqlite3
    import shutil
    layout = core.ensure_layout()
    checks = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": str(detail)})

    root_dir = layout["root"]
    add("SHIBAN_ROOT", True, root_dir)
    try:
        probe = os.path.join(root_dir, ".write-probe")
        Path(probe).write_text("ok", encoding="utf-8")
        os.remove(probe)
        add("数据根可写", True)
    except OSError as exc:
        add("数据根可写", False, exc)

    add("python", True, f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        f" ({sys.executable})")
    add("sqlite", sqlite3.sqlite_version >= "3.35", sqlite3.sqlite_version + "（需 ≥3.35 才有 trigram）")

    fts5 = False
    try:
        probe_conn = sqlite3.connect(":memory:")
        probe_conn.execute("CREATE VIRTUAL TABLE _p USING fts5(x)")
        probe_conn.close()
        fts5 = True
    except sqlite3.OperationalError:
        pass
    add("FTS5", fts5, "全文检索依赖")

    add("pdftotext", bool(shutil.which("pdftotext")),
        "缺失则 PDF 导入不可用，改用已转换的 .md")
    add("chrome/chromium", bool(shutil.which("google-chrome") or shutil.which("chromium")
                                or shutil.which("chromium-browser")),
        "缺失则教案只能导出 HTML，不能转 PDF")
    add("prince", bool(shutil.which("prince")), "可选：更好的打印版式")

    persistent = layout["corpus"]
    add("corpus 目录", True, persistent)
    corpora = 0
    try:
        mc = Path(persistent)
        corpora = sum(1 for p in mc.iterdir() if (p / "manifest.json").is_file()) if mc.is_dir() else 0
    except OSError:
        pass
    add("已导入语料", corpora > 0, f"{corpora} 本（空壳属正常，可 corpus import 导入）")

    return {"ok": all(c["ok"] for c in checks if c["check"] in
                      ("数据根可写", "python", "sqlite", "FTS5")),
            "version": _version(), "root": root_dir, "checks": checks}


def cmd_version(args) -> dict:
    meta = core.package_meta()
    presets = meta.get("shiban") or {}
    return {"name": meta["name"], "version": meta["version"],
            "preset_id": presets.get("presetId"), "root": core.root()}


def cmd_artifact(args) -> dict:
    action = args.action
    if action == "put":
        envelope = _load_json_arg(args.envelope, "--envelope")
        if args.kind:
            envelope["kind"] = args.kind
        if args.payload:
            envelope["payload"] = _load_json_arg(args.payload, "--payload")
        if args.id:
            envelope["id"] = args.id
        return core.put(envelope, expected_rev=args.expect_rev)
    if action == "get":
        view = args.view
        if view == "section":
            if not args.name:
                raise ShibanError("bad_args", "--view section 需要 --name")
            got = core.get_section(args.id, args.name)
            if got is None:
                raise ShibanError("not_found", f"{args.id} 没有节 {args.name}")
            return got
        got = core.get(args.id, view)
        if got is None:
            raise ShibanError("not_found", f"产物不存在：{args.id}")
        return got
    if action == "list":
        return core.list_artifacts(kind=args.kind, scope=args.scope, status=args.status)
    if action == "confirm":
        return core.confirm(args.id, _load_json_arg(args.verdict, "--verdict") or None)
    if action == "discard":
        return core.discard(args.id, args.reason or "")
    if action == "archive":
        return core.archive(args.id)
    if action == "stale":
        return {"affected": core.mark_stale(args.id)}
    if action == "section":
        value = _load_json_arg(args.value, "--value")
        return core.set_section(args.id, args.name, value)
    raise ShibanError("bad_args", f"未知 artifact 子命令：{action}")


def cmd_ctx(args) -> dict:
    if args.action != "pack":
        raise ShibanError("bad_args", f"未知 ctx 子命令：{args.action}")
    extra = {"scope": args.scope, "lesson": args.lesson, "kw": args.kw,
             "corpus": args.corpus, "kp": args.kp, "limit": args.limit}
    return _pack(args.for_atom, extra)


def cmd_corpus(args) -> dict:
    import shiban_corpus as corpus
    action = args.action
    if action == "import":
        meta = _load_json_arg(args.meta, "--meta")
        return corpus.import_file(args.file, meta, page_offset=args.page_offset,
                                  dry_run=args.dry_run)
    if action == "list":
        return corpus.list_corpora()
    if action == "search":
        hits = corpus.search(args.kw, corpus_id=args.corpus, limit=args.limit)
        if getattr(args, "cite", False):
            # 直接给出可贴进 lesson.json citations[] 的结构
            return [{
                "corpus_id": h.get("corpus_id"),
                "book_page": h.get("book_page"),
                "pdf_page": h.get("pdf_page"),
                "quote": (h.get("snippet") or "")[:80],
                "display": corpus.cite(h),
            } for h in hits]
        return hits
    if action == "offset":
        return corpus.infer_page_offset(args.corpus)
    if action == "read":
        return corpus.read_page(args.corpus, book_page=args.p, pdf_page=args.pdf_page,
                                around=args.around or 0)
    if action == "verify":
        return corpus.verify(args.corpus)
    if action == "remove":
        return corpus.remove(args.corpus, force=args.force)
    raise ShibanError("bad_args", f"未知 corpus 子命令：{action}")


def _check_theory(payload: dict) -> list:
    """核对 payload 里的理论引用：编号存在、页码在范围内、引文可复现。"""
    cites = payload.get("cites_theory") or payload.get("citations_theory") or []
    if not cites:
        return []
    try:
        import shiban_theory as theory
    except ImportError:
        return [{"ok": False, "reason": "theory 模块不可用"}]
    return theory.verify_citations(cites)


def _check_citations(payload: dict) -> list:
    """逐条核对 citations 能否被 corpus 复现——这是"引用可追溯"的唯一硬证据。"""
    out = []
    try:
        import shiban_corpus as corpus
    except ImportError:
        return [{"ok": False, "reason": "corpus 模块不可用"}]
    for cite in (payload.get("citations") or []):
        cid = cite.get("corpus_id")
        quote = (cite.get("quote") or "").strip()
        entry = {"corpus_id": cid, "book_page": cite.get("book_page"), "ok": False}
        if not cid or not quote:
            entry["reason"] = "缺 corpus_id 或 quote"
            out.append(entry)
            continue
        page = cite.get("book_page")
        try:
            if page is None:
                hits = corpus.search(quote[:20], corpus_id=cid, limit=5)
                found = any(quote[:20] in (h.get("snippet") or "") for h in hits)
                entry["reason"] = None if found else "语料中检索不到该引文"
                entry["ok"] = found
            else:
                pg = corpus.read_page(cid, book_page=page)
                text = "".join(b.get("text", "") for b in (pg.get("blocks") or []))
                found = quote[:20] in text
                entry["reason"] = None if found else f"第 {page} 页找不到该引文"
                entry["ok"] = found
        except Exception as exc:  # noqa: BLE001
            entry["reason"] = f"{type(exc).__name__}: {exc}"
        out.append(entry)
    return out



def cmd_asset(args) -> dict:
    import shiban_asset as asset
    action = args.action
    if action == "import":
        return asset.import_file(args.file, title=args.title, category=args.category,
                                 stage=args.stage, kp=args.kp, origin=args.origin,
                                 license=args.license_name, provenance=args.provenance or "",
                                 interface=_load_json_arg(args.interface, "--interface") or None,
                                 dry_run=args.dry_run)
    if action == "list":
        return asset.list_assets(kind=args.kind, kp=args.kp, category=args.category,
                                 stage=args.stage)
    if action == "get":
        got = asset.get(args.id)
        if got is None:
            raise ShibanError("not_found", f"素材不存在：{args.id}")
        return got
    if action == "reuse":
        return asset.reuse(args.id)
    if action == "compose":
        spec = _load_json_arg(args.spec, "--spec") if args.spec else None
        if args.spec_file:
            spec = _load_json_arg("@" + args.spec_file, "--spec-file")
        if args.spec_schema:
            return asset.compose_spec_schema()
        return asset.compose(spec or {})
    if action == "suggest":
        return asset.suggest(knowledge_point=args.kp, kind=args.kind, limit=args.limit)
    if action == "triage":
        return asset.triage(args.path, dry_run=args.dry_run)
    raise ShibanError("bad_args", f"未知 asset 子命令：{action}")


def cmd_lesson(args) -> dict:
    import shiban_lesson as lesson
    if args.action == "template":
        payload = lesson.empty_lesson()
        out = Path(args.out) if args.out else None
        if out:
            if out.exists() and not args.force:
                raise ShibanError("exists", f"{out} 已存在（--force 覆盖）")
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
            return {"ok": True, "path": str(out)}
        return payload
    if args.action == "validate":
        payload = _load_json_arg("@" + args.file if args.file else None, "--file")
        result = lesson.validate(payload, strict=args.strict)
        if getattr(args, "check_citations", False):
            result["citation_check"] = _check_citations(payload)
            if any(not c["ok"] for c in result["citation_check"]):
                result["ok"] = False
        if getattr(args, "check_theory", False):
            result["theory_check"] = _check_theory(payload)
            if any(not c["ok"] for c in result["theory_check"]):
                result["ok"] = False
        return result
    if args.action == "render":
        payload = _load_json_arg("@" + args.file if args.file else None, "--file")
        result = lesson.validate(payload, strict=False)
        if not result["ok"]:
            raise ShibanError("invalid_lesson",
                              "教案未通过校验，先修正再渲染",
                              "; ".join(e["code"] for e in result["errors"][:5]))
        return _render_lesson(lesson, payload, args)
    raise ShibanError("bad_args", f"未知 lesson 子命令：{args.action}")


def _render_lesson(lesson, payload: dict, args) -> dict:
    """渲染教案：md / html / pdf。PDF 引擎按可用性探测，缺失时明确报告而不报错。"""
    import shutil
    import subprocess

    stem = (payload.get("meta") or {}).get("title") or "lesson"
    stem = "".join(ch for ch in stem if ch not in '/\\:*?"<>|').strip() or "lesson"
    out_dir = Path(args.out_dir) if args.out_dir else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)
    want = {x.strip() for x in (args.formats or "md,html,pdf").split(",") if x.strip()}
    style = args.style or "template"
    produced, skipped = {}, {}

    md_path = out_dir / f"{stem}.md"
    if "md" in want:
        md_path.write_text(lesson.render_markdown(payload, style=style), encoding="utf-8")
        produced["md"] = str(md_path)

    html_path = out_dir / f"{stem}.html"
    if "html" in want or "pdf" in want:
        html_path.write_text(lesson.render_html(payload, style=style, title=stem),
                            encoding="utf-8")
        if "html" in want:
            produced["html"] = str(html_path)

    if "pdf" in want:
        engine = None
        for name, probe in (("prince", "prince"),
                            ("chrome", "google-chrome"),
                            ("chromium", "chromium"),
                            ("chromium", "chromium-browser")):
            if shutil.which(probe):
                engine = (name, probe)
                break
        if engine is None:
            skipped["pdf"] = "no_engine（未找到 prince / chrome / chromium，只生成了 HTML）"
        else:
            pdf_path = out_dir / f"{stem}.pdf"
            name, exe = engine
            try:
                if name == "prince":
                    cmd = [exe, str(html_path), "-o", str(pdf_path)]
                else:
                    cmd = [exe, "--headless", "--disable-gpu", "--no-sandbox",
                           f"--print-to-pdf={pdf_path}", "--no-pdf-header-footer",
                           html_path.as_uri()]
                subprocess.run(cmd, check=True, capture_output=True, timeout=180)
                if pdf_path.is_file() and pdf_path.stat().st_size > 0:
                    produced["pdf"] = str(pdf_path)
                    produced["pdf_engine"] = name
                else:
                    skipped["pdf"] = f"{name} 未产出有效文件"
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
                skipped["pdf"] = f"{name} 失败：{type(exc).__name__}"

    return {"ok": True, "style": style, "out_dir": str(out_dir),
            "produced": produced, "skipped": skipped}



def cmd_ask(args) -> dict:
    """提问日志：暂存 / 强制暂停 / 回答，全部落盘可追溯。"""
    action = args.action
    if action == "log":
        if args.event not in ("queue", "pause", "answer", "unblock", "over_budget"):
            raise ShibanError("bad_args", f"未知事件：{args.event}")
        payload = {
            "atom": args.for_atom,
            "scope": args.scope,
            "round": args.round,
            "questions": _load_list(args.questions, "--questions"),
            "answers": _load_list(args.answers, "--answers"),
            "pending": args.pending,
            "note": args.note or "",
        }
        return core.log_ask(args.event, {k: v for k, v in payload.items() if v is not None})
    if action == "list":
        return core.read_ask_log(limit=args.limit)
    if action == "stats":
        return core.ask_stats()
    raise ShibanError("bad_args", f"未知 ask 子命令：{action}")


def _load_list(value, flag: str) -> list | None:
    if value is None:
        return None
    if value == "-":
        value = sys.stdin.read()
    elif value.startswith("@"):
        value = Path(value[1:]).read_text(encoding="utf-8")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ShibanError("bad_json", f"{flag} 不是合法 JSON：{exc.msg}")
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise ShibanError("bad_json", f"{flag} 必须是数组或对象")
    return parsed



def cmd_theory(args) -> dict:
    """理论库：内置（随包登记）+ 补充（derived，永不覆盖）。"""
    import shiban_theory as theory
    action = args.action
    if action == "list":
        return theory.list_items(source=args.source, query=args.query)
    if action == "stats":
        return theory.stats()
    if action == "pages":
        return theory.pages_of(args.id)
    if action == "read":
        return theory.read_page(args.id, int(args.page))
    if action == "search":
        return theory.search(args.kw, limit=args.limit or 10)
    if action == "cite":
        return theory.cite(args.id, int(args.page), quote=args.quote or "")
    if action == "verify":
        cites = _load_list(args.cites, "--cites") if args.cites else None
        if cites is None:
            raise ShibanError("bad_args", "verify 需要 --cites '<json数组>'")
        return theory.verify_citations(cites)
    if action == "audit":
        return theory.audit_digests()
    if action == "add":
        return theory.add_derived(args.file, title=args.title or "",
                                  meta=_load_json_arg(args.meta, "--meta") or None)
    raise ShibanError("bad_args", f"未知 theory 子命令：{action}")



def cmd_theory_explain(args) -> dict:
    """输出提炼框架全文（供 Agent 阅读；体积受控，几 KB）。"""
    digest_dir = HERE.parent.parent / "framework" / "theory" / "builtin" / "digests"
    name = args.file
    if not name.endswith(".md"):
        name += ".md"
    path = digest_dir / name
    if not path.is_file():
        available = sorted(p.name for p in digest_dir.glob("*.md") if p.name != "README.md")
        raise ShibanError("not_found", f"框架不存在：{name}",
                          f"可用：{', '.join(available) or '（尚未生成）'}")
    return {"file": str(path), "bytes": path.stat().st_size,
            "text": path.read_text(encoding="utf-8")}



def cmd_migrate(args) -> dict:
    """迁移历史积累的素材。**只在部署时显式执行，开发阶段保持空包。**"""
    import shiban_migrate as migrate
    if args.action == "sources":
        return {"history": migrate.discover_sources(), "current": core.root(),
                "hint": "找到要迁的源后：migrate run --from <路径>（先干跑，再加 --yes）"}
    if args.action == "run":
        source = args.from_path
        if not source:
            found = [h for h in migrate.discover_sources()
                     if h["files"] > 0 and h.get("migratable", True)]
            if not found:
                return {"ok": True,
                        "note": "没有可迁移的数据根（只迁移 v0.5.0 及以后版本的素材）",
                        "current": core.root()}
            source = found[0]["path"]
        return migrate.run_migration(source, dry_run=not args.yes, force=args.force)
    raise ShibanError("bad_args", f"未知 migrate 子命令：{args.action}")


def cmd_info(args) -> dict:
    """安装位置与数据根：两者都由 __file__ 动态推导，随 DSH 安装位置变化。"""
    meta = core.package_meta()
    return {
        "package": meta["name"],
        "version": meta["version"],
        "preset_id": (meta.get("shiban") or {}).get("presetId"),
        "preset_name": (meta.get("shiban") or {}).get("presetName"),
        "package_dir": core.pkg_dir(),
        "legacy_root": core.legacy_root(),
        "data_root": core.root(),
        "python": sys.version.split()[0],
        "vendored_python": (Path(core.pkg_dir()) / "vendor" / "python" / "lib").is_dir(),
    }



def cmd_evidence(args) -> dict:
    if args.action == "save":
        if args.file:
            text = Path(args.file).read_text(encoding="utf-8")
        elif args.stdin:
            text = sys.stdin.read()
        else:
            text = args.text or ""
        return core.save_evidence(args.name, text)
    if args.action == "list":
        return core.list_evidence()
    if args.action == "read":
        return core.read_evidence(args.name)
    raise ShibanError("bad_args", f"未知 evidence 子命令：{args.action}")


def cmd_graph(args) -> dict:
    return core.graph_query()


# --------------------------------------------------------------------------- #
# 参数解析
# --------------------------------------------------------------------------- #

def build_parser(argv_in=None) -> argparse.ArgumentParser:
    # --human 允许出现在任何子命令之后：先在本层扫一遍，再从 argv 里摘掉。
    argv = list(sys.argv[1:] if argv_in is None else argv_in)
    human_flag = "--human" in argv
    argv = [x for x in argv if x != "--human"]

    ap = argparse.ArgumentParser(prog="shiban-store", description="师伴数据层 CLI（v0.5.0）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="初始化数据根").set_defaults(fn=cmd_init)
    sub.add_parser("doctor", help="环境自检").set_defaults(fn=cmd_doctor)
    sub.add_parser("version", help="版本").set_defaults(fn=cmd_version)
    sub.add_parser("graph", help="引用图概览").set_defaults(fn=cmd_graph)

    a = sub.add_parser("artifact", help="产物读写")
    asp = a.add_subparsers(dest="action", required=True)
    p = asp.add_parser("put"); p.add_argument("--envelope"); p.add_argument("--kind")
    p.add_argument("--payload"); p.add_argument("--id"); p.add_argument("--expect-rev", type=int)
    p = asp.add_parser("get"); p.add_argument("--id", required=True)
    p.add_argument("--view", choices=["index", "digest", "section", "full"], default="index")
    p.add_argument("--name")
    p = asp.add_parser("list"); p.add_argument("--kind"); p.add_argument("--scope")
    p.add_argument("--status")
    p = asp.add_parser("confirm"); p.add_argument("--id", required=True); p.add_argument("--verdict")
    p = asp.add_parser("discard"); p.add_argument("--id", required=True); p.add_argument("--reason")
    p = asp.add_parser("archive"); p.add_argument("--id", required=True)
    p = asp.add_parser("stale"); p.add_argument("--id", required=True)
    p = asp.add_parser("section"); p.add_argument("--id", required=True)
    p.add_argument("--name", required=True); p.add_argument("--value", required=True)
    a.set_defaults(fn=cmd_artifact)

    c = sub.add_parser("ctx", help="上下文包")
    csp = c.add_subparsers(dest="action", required=True)
    p = csp.add_parser("pack")
    p.add_argument("--for", dest="for_atom", required=True)
    p.add_argument("--lesson"); p.add_argument("--scope"); p.add_argument("--kw")
    p.add_argument("--corpus"); p.add_argument("--kp"); p.add_argument("--limit", type=int, default=5)
    c.set_defaults(fn=cmd_ctx)

    co = sub.add_parser("corpus", help="语料")
    csp = co.add_subparsers(dest="action", required=True)
    p = csp.add_parser("import"); p.add_argument("--file", required=True)
    p.add_argument("--meta"); p.add_argument("--page-offset", type=int)
    p.add_argument("--dry-run", action="store_true")
    csp.add_parser("list")
    p = csp.add_parser("search"); p.add_argument("--kw", required=True)
    p.add_argument("--corpus"); p.add_argument("--limit", type=int, default=10)
    p.add_argument("--cite", action="store_true", help="输出可直接贴进 lesson.json 的引用")
    csp.add_parser("offset").add_argument("--corpus", required=True)
    p = csp.add_parser("read"); p.add_argument("--corpus", required=True)
    p.add_argument("--p", type=int); p.add_argument("--pdf-page", type=int)
    p.add_argument("--around", type=int, default=0)
    p = csp.add_parser("verify"); p.add_argument("--corpus", required=True)
    p = csp.add_parser("remove"); p.add_argument("--corpus", required=True)
    p.add_argument("--force", action="store_true")
    co.set_defaults(fn=cmd_corpus)

    s = sub.add_parser("asset", help="素材")
    asp = s.add_subparsers(dest="action", required=True)
    p = asp.add_parser("import"); p.add_argument("--file", required=True)
    p.add_argument("--title", required=True); p.add_argument("--category", default="other")
    p.add_argument("--stage", default="任意"); p.add_argument("--kp")
    p.add_argument("--origin", default="imported-web")
    p.add_argument("--license", dest="license_name", default="unknown")
    p.add_argument("--provenance"); p.add_argument("--interface")
    p.add_argument("--dry-run", action="store_true")
    p = asp.add_parser("list"); p.add_argument("--kind"); p.add_argument("--kp")
    p.add_argument("--category"); p.add_argument("--stage")
    p = asp.add_parser("get"); p.add_argument("--id", required=True)
    p = asp.add_parser("reuse"); p.add_argument("--id", required=True)
    p = asp.add_parser("compose"); p.add_argument("--spec"); p.add_argument("--spec-file")
    p.add_argument("--spec-schema", action="store_true")
    p = asp.add_parser("suggest"); p.add_argument("--kp"); p.add_argument("--kind")
    p.add_argument("--limit", type=int, default=10)
    p = asp.add_parser("triage"); p.add_argument("--path", required=True)
    p.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_asset)

    l = sub.add_parser("lesson", help="教案")
    lsp = l.add_subparsers(dest="action", required=True)
    p = lsp.add_parser("template"); p.add_argument("--out"); p.add_argument("--force", action="store_true")
    p = lsp.add_parser("validate"); p.add_argument("--file", required=True)
    p.add_argument("--check-theory", action="store_true",
                   help="逐条核对 cites_theory 的编号、页码与引文")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--check-citations", action="store_true",
                   help="逐条核对 citations 能否被 corpus 复现")
    p = lsp.add_parser("render"); p.add_argument("--file", required=True)
    p.add_argument("--style", default="template", choices=["template", "competition"])
    p.add_argument("--out-dir"); p.add_argument("--formats", default="md,html,pdf")
    l.set_defaults(fn=cmd_lesson)

    mi = sub.add_parser("info", help="安装位置与数据根")
    mi.set_defaults(fn=cmd_info)

    mg = sub.add_parser("migrate", help="迁移历史素材（部署时显式执行）")
    msp = mg.add_subparsers(dest="action", required=True)
    msp.add_parser("sources")
    p = msp.add_parser("run"); p.add_argument("--from", dest="from_path")
    p.add_argument("--yes", action="store_true", help="真正执行（默认只干跑）")
    p.add_argument("--force", action="store_true", help="覆盖同名文件")
    mg.set_defaults(fn=cmd_migrate)

    th = sub.add_parser("theory", help="理论库（内置 + 补充）")
    tsp = th.add_subparsers(dest="action", required=True)
    p = tsp.add_parser("list"); p.add_argument("--source", choices=["builtin", "derived"])
    p.add_argument("--query")
    tsp.add_parser("stats")
    p = tsp.add_parser("pages"); p.add_argument("--id", required=True)
    p = tsp.add_parser("read"); p.add_argument("--id", required=True); p.add_argument("--page", required=True)
    p = tsp.add_parser("search"); p.add_argument("--kw", required=True); p.add_argument("--limit", type=int)
    p = tsp.add_parser("cite"); p.add_argument("--id", required=True)
    p.add_argument("--page", required=True); p.add_argument("--quote")
    p = tsp.add_parser("verify"); p.add_argument("--cites", required=True)
    p = tsp.add_parser("add"); p.add_argument("--file", required=True)
    p.add_argument("--title"); p.add_argument("--meta")
    p = tsp.add_parser("explain"); p.add_argument("--file", required=True)
    tsp.add_parser("audit")
    p.set_defaults(fn=cmd_theory_explain)
    th.set_defaults(fn=cmd_theory)

    k = sub.add_parser("ask", help="提问日志（暂存/暂停/回答）")
    ksp = k.add_subparsers(dest="action", required=True)
    p = ksp.add_parser("log"); p.add_argument("--event", required=True,
        choices=["queue", "pause", "answer", "unblock", "over_budget"])
    p.add_argument("--for", dest="for_atom"); p.add_argument("--scope")
    p.add_argument("--round", type=int); p.add_argument("--questions"); p.add_argument("--answers")
    p.add_argument("--pending", type=int); p.add_argument("--note")
    p = ksp.add_parser("list"); p.add_argument("--limit", type=int, default=100)
    ksp.add_parser("stats")
    k.set_defaults(fn=cmd_ask)

    e = sub.add_parser("evidence", help="原始证据（L0，只追加）")
    esp = e.add_subparsers(dest="action", required=True)
    p = esp.add_parser("save"); p.add_argument("--name", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--file"); g.add_argument("--text"); g.add_argument("--stdin", action="store_true")
    esp.add_parser("list")
    p = esp.add_parser("read"); p.add_argument("--name", required=True)
    e.set_defaults(fn=cmd_evidence)

    return ap, human_flag


def main(argv: list[str] | None = None) -> int:
    ap, human = build_parser(argv)
    args = ap.parse_args([x for x in (sys.argv[1:] if argv is None else argv) if x != "--human"])
    try:
        result = args.fn(args)
    except ShibanError as exc:
        sys.stderr.write(f"[error] {exc.code}: {exc}\n")
        if getattr(exc, "hint", ""):
            sys.stderr.write(f"[hint ] {exc.hint}\n")
        return 2
    except FileNotFoundError as exc:
        sys.stderr.write(f"[error] not_found: {exc}\n")
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 —— 兜底：不让 traceback 干扰 JSON 消费者
        sys.stderr.write(f"[error] internal: {type(exc).__name__}: {exc}\n")
        if os.environ.get("SHIBAN_DEBUG"):
            import traceback
            traceback.print_exc()
        return 1

    if result == 0:
        return 0
    _emit(result, human=human, label=getattr(args, "cmd", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
