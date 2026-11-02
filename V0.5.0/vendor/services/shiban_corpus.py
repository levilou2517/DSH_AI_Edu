"""师伴 Shiban · 语料层（corpus）

教师自行导入教材 / 课标 / 论文（版权原因不随包分发），并做「带页码锚点」的全文检索，
使 Agent 引用教材时可给出 ``教材P.55 / PDF页64 / 原文片段`` 并被人工复核。

数据流（导入 → 分页 → 索引 → 检索 → 引用）
--------------------------------------------
1. **导入** ``import_file``
   ``.pdf`` → ``pdftotext -layout``（可选依赖，用 ``shutil.which`` 探测；缺失抛
   ``E_NO_EXTRACTOR``）；``.md/.txt`` → 按 ``<!-- page:N -->`` 或 ``\\f`` 切页。
   页 -> ``blocks``（heading / paragraph / table / figure_caption / formula 启发式分类）。
   写入 ``$SHIBAN_ROOT/corpus/<corpus_id>/``：``manifest.json`` + ``pages/NNN.json``
   + ``source.*``（原件副本，用于校验）。全部原子写（tmp + ``os.replace``）。
2. **分页** ``read_page``
   双锚点：``pdf_page``（PDF 物理页）与 ``book_page = pdf_page - page_offset``
   （书上印刷页码）。md 无页码标记时整篇 1 页且 ``book_page=None``——**此时不得编页码**。
3. **索引** ``build_index``
   ``corpus/corpus.db``（与 ``shiban_core`` 的 graph.db 分开）内建 FTS5 表 ``fts``；
   ``body`` 用 ``tokenize_cn`` 做汉字 bigram + ASCII 整词小写后再入库（unicode61 分词），
   因此检索无需第三方分词器、``sqlite3`` 无需 trigram 支持。
4. **检索** ``search``
   多字词 → ``"tok1" AND "tok2" ...`` MATCH，``bm25`` 升序；
   单字 → ``LIKE`` 扫 pages（bigram 索引对单字无效）。
5. **引用** ``cite``
   把检索命中渲染成 ``【书名·教材P.55 / PDF页64】原文片段``，供教案 / 试题写入
   ``citations[]``（``corpus_id`` + ``book_page`` + ``quote``）。引用必须能被
   ``read_page`` 复现；``verify`` 与检索结果中的 ``low_quality`` 标记用于提示
   「该页抽取质量低，引用前请人工核对」。

约定
----
* 只依赖标准库；``pdftotext`` 可选。
* 共享常量读 ``contracts/constants.json``（``corpus_kinds`` / ``evidence_levels``）。
* 路径从 ``__file__`` 推算：``vendor/services/`` → 上两级 = 项目根。
* ``corpus_id`` 只允许 ``[\\w\\u4e00-\\u9fff.-]+``；任何输入路径做 realpath 越界检查。

自检::

    SHIBAN_ROOT=/tmp/xxx python3 vendor/services/shiban_corpus.py
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import traceback

__all__ = [
    "ShibanError",
    "corpus_root",
    "list_corpora",
    "get_corpus",
    "import_file",
    "build_index",
    "tokenize_cn",
    "search",
    "read_page",
    "verify",
    "remove",
    "cite",
    "infer_page_offset",
]

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))  # vendor/services -> 项目根
_CONSTANTS_PATH = os.path.join(_PROJECT_ROOT, "contracts", "constants.json")

# constants.json 不可读时的兜底（与契约保持一致）
_FALLBACK_CORPUS_KINDS = ("textbook", "standard", "paper", "reference", "personal")
_FALLBACK_EVIDENCE_LEVELS = ("rct", "quasi", "small-n", "review", "opinion", "unknown")

CORPUS_ID_RE = re.compile(r"^[\w\u4e00-\u9fff.-]+$", re.UNICODE)
BLOCK_TYPES = ("heading", "paragraph", "table", "figure_caption", "formula")

#: 汉字覆盖率下限（汉字数 / 非空字符数）
HAN_RATIO_MIN = 0.15
#: 有效字符（非空白字符）下限
MIN_EFFECTIVE_CHARS = 50
#: 引用片段长度（前后各截取），search 的 snippet 用同一参数
SNIPPET_RADIUS = 40
#: FTS5 默认 bm25 权重 k1=1.2 b=0.75；索引侧做轻微词频饱和压缩，避免长页被「重复词」刷屏
BM25_B = 0.75
MAX_INDEX_REPEAT = 8
MAX_FILE_BYTES = 300 * 1024 * 1024
MAX_PARAM = 500  # SQLite 变量个数保守上限
PDFTOTEXT_TIMEOUT = 300

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+")
_CN_NUM = "一二三四五六七八九十百零〇两"
_TERMINAL_PUNCT = tuple("。！？；…")
#: 中英文句末/分隔标点：出现即视为"该行已说完"
TERMINAL_PUNCT_ALL = tuple("。！？；…，、：.!?;,")
#: 优先于 table 识别的特征（图注 / 公式不会被误判成表格行）
#: 单位词：左侧不能紧跟字母（排除\"DNA\"里的\"na\"、\"primerase\"里的\"min\"），
#: 右侧不能紧跟字母或斜杠（"cm" 不吞 "cm/s" 的 "cm"）。
_UNIT_RE = re.compile(
    r"(?<![A-Za-z])(?:mol|kJ|pH|km|cm|mm|mL|mg|kg|min|m/s)(?![A-Za-z/])"
)
_STRONG_TABLE_RE = re.compile(
    r"图\s*[0-9０-９一二三四五六七八九十]|[＝≈×→]|" + _UNIT_RE.pattern
)


def _load_constants() -> dict:
    try:
        with open(_CONSTANTS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


_CONSTANTS = _load_constants()
CORPUS_KINDS = tuple(_CONSTANTS.get("corpus_kinds") or _FALLBACK_CORPUS_KINDS)
EVIDENCE_LEVELS = tuple(_CONSTANTS.get("evidence_levels") or _FALLBACK_EVIDENCE_LEVELS)


# ---------------------------------------------------------------------------
# 错误
# ---------------------------------------------------------------------------
class ShibanError(Exception):
    """带机器可读 ``code`` 与人类可读 ``hint`` 的语料层异常。"""

    def __init__(self, code, message, hint=""):
        super().__init__(f"[{code}] {message}" + (f"（提示：{hint}）" if hint else ""))
        self.code = code
        self.message = message
        self.hint = hint

    def to_dict(self) -> dict:
        return {"ok": False, "code": self.code, "message": self.message, "hint": self.hint}


def _err(code, message, hint=""):
    raise ShibanError(code, message, hint)


# ---------------------------------------------------------------------------
# 基础工具：路径 / 原子写 / JSON / 哈希
# ---------------------------------------------------------------------------
def _shiban_root() -> str:
    root = os.environ.get("SHIBAN_ROOT") or "~/.shiban"
    return os.path.abspath(os.path.expanduser(root))


def corpus_root() -> str:
    """返回 ``$SHIBAN_ROOT/corpus``（绝对路径，不创建）。"""
    return os.path.join(_shiban_root(), "corpus")


def _corpus_db_path() -> str:
    return os.path.join(corpus_root(), "corpus.db")


def _corpus_dir(corpus_id) -> str:
    """校验 corpus_id 并返回其目录（保证落在 corpus_root 内）。"""
    if not isinstance(corpus_id, str) or not corpus_id or len(corpus_id) > 80:
        _err("E_BAD_ID", f"corpus_id 非法：{corpus_id!r}", "只允许 [\\w\\u4e00-\\u9fff.-]+，长度 1..80")
    if (corpus_id in (".", "..") or not CORPUS_ID_RE.match(corpus_id)
            or corpus_id.startswith(".") or ".." in corpus_id):
        _err("E_BAD_ID", f"corpus_id 非法：{corpus_id!r}", "只允许 [\\w\\u4e00-\\u9fff.-]+，且不得含 '..' 或以其开头")
    root = os.path.realpath(corpus_root())
    target = os.path.realpath(os.path.join(root, corpus_id))
    if target != os.path.join(root, corpus_id) or os.path.dirname(target) != root:
        _err("E_BAD_ID", f"corpus_id 越界：{corpus_id!r}", "路径穿越被拒绝")
    return target


def _check_input_file(file_path) -> str:
    """输入文件做存在性 + realpath 检查（允许绝对路径，但不跟随可疑链接做越权写入）。"""
    if not isinstance(file_path, (str, os.PathLike)) or not str(file_path):
        _err("E_BAD_ARGS", "file_path 必须是非空字符串")
    path = os.path.abspath(os.path.expanduser(str(file_path)))
    if not os.path.exists(path):
        _err("E_NOT_FOUND", f"文件不存在：{path}", "确认路径正确、文件可读")
    if not os.path.isfile(path):
        _err("E_NOT_FILE", f"不是普通文件：{path}")
    if os.path.getsize(path) > MAX_FILE_BYTES:
        _err("E_TOO_LARGE", f"文件过大：{os.path.getsize(path)} 字节",
             f"上限 {MAX_FILE_BYTES} 字节；请拆分后导入")
    return os.path.realpath(path)


def _ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def _atomic_write_bytes(path: str, data: bytes) -> None:
    parent = os.path.dirname(path) or "."
    _ensure_dir(parent)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix="." + os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_write_text(path: str, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _write_json(path: str, obj) -> None:
    _atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def _read_json(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().replace(microsecond=0).isoformat()


def _safe_page_file(n: int) -> str:
    return f"{int(n):03d}.json"


def _page_files(cdir: str) -> list:
    pdir = os.path.join(cdir, "pages")
    try:
        names = sorted(n for n in os.listdir(pdir) if n.endswith(".json") and n[:-5].isdigit())
    except OSError:
        return []
    return [os.path.join(pdir, n) for n in names]


def _load_pages(cdir: str) -> list:
    pages = []
    for path in _page_files(cdir):
        try:
            pages.append(_read_json(path))
        except (OSError, ValueError):
            continue
    pages.sort(key=lambda p: p.get("pdf_page") or 0)
    return pages


def _page_plain_text(page: dict) -> str:
    return "\n".join(b.get("text", "") for b in page.get("blocks") or [] if b.get("text"))


# ---------------------------------------------------------------------------
# 切词
# ---------------------------------------------------------------------------
def tokenize_cn(text: str) -> str:
    """混合切词：汉字连续段 → 相邻二字 bigram（段长 1 保留单字）；ASCII 词 → 小写整词。

    「DNA半保留复制」→ ``"dna 半保 保留 留复 复制"``（「DNA」后被「半」截断，
    按规则不跨词边界生成「a半」）。
    """
    if not isinstance(text, str) or not text:
        return ""
    out = []
    for m in _TOKEN_RE.finditer(text):
        seg = m.group(0)
        if seg[0].isascii():
            out.append(seg.lower())
        elif len(seg) == 1:
            out.append(seg)
        else:
            out.extend(seg[i:i + 2] for i in range(len(seg) - 1))
    return " ".join(out)


def _index_body(text: str) -> str:
    """入库正文：bigram 序列 + 词频饱和压缩（同一 token 每页最多 MAX_INDEX_REPEAT 次）。"""
    counts = {}
    kept = []
    for tok in tokenize_cn(text).split(" "):
        if not tok:
            continue
        n = counts.get(tok, 0)
        counts[tok] = n + 1
        if n < MAX_INDEX_REPEAT:
            kept.append(tok)
    return (" " + " ".join(kept) + " ") if kept else ""


def _match_expr(keyword: str) -> str:
    tokens = []
    for tok in tokenize_cn(keyword).split(" "):
        tok = tok.replace('"', "").strip()
        if tok and tok not in tokens:
            tokens.append(tok)
    return " AND ".join(f'"{t}"' for t in tokens)


# ---------------------------------------------------------------------------
# PDF 抽取
# ---------------------------------------------------------------------------
def _extract_pdf_pages(path) -> list[dict]:
    """用 ``pdftotext -layout`` 抽取 PDF，按 ``\\f`` 切页。

    返回 ``[{"pdf_page": 1, "text": "..."}, ...]``。``pdftotext`` 不存在时抛
    ``E_NO_EXTRACTOR``。注意 pdftotext 通常在每页末尾补一个 ``\f``，故按 ``\\f``
    切分后末尾的空片段必须丢弃，否则会多出一张空白页。
    """
    exe = shutil.which("pdftotext")
    if not exe:
        _err(
            "E_NO_EXTRACTOR",
            "未找到 pdftotext，无法从 PDF 抽取文本",
            "安装 poppler-utils（Debian/Ubuntu: `apt install poppler-utils`；macOS: "
            "`brew install poppler`；Windows 安装 poppler 并把 bin 加入 PATH）；"
            "或先用其它工具转成 .md，并用 `<!-- page:N -->` 标注页码后导入 .md",
        )
    path = str(path)
    cmd = [exe, "-layout", "-enc", "UTF-8", path, "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False, timeout=PDFTOTEXT_TIMEOUT)
    except OSError as exc:
        _err("E_EXTRACTOR_FAILED", f"无法运行 pdftotext：{exc}", "确认 poppler-utils 安装完整")
    except subprocess.TimeoutExpired:
        _err("E_EXTRACTOR_FAILED", f"pdftotext 超时（>{PDFTOTEXT_TIMEOUT}s）", "PDF 过大或已损坏")
    if proc.returncode != 0:
        msg = (proc.stderr or b"").decode("utf-8", "replace").strip() or f"exit {proc.returncode}"
        _err("E_EXTRACTOR_FAILED", f"pdftotext 失败：{msg}",
             "文件可能加密或损坏；可用密码解除后再导入，或改用 .md")
    stdout = proc.stdout or b""
    text = stdout.decode("utf-8", "replace")
    # 部分 PDF（如 LaTeX 默认编码）没有 ToUnicode 映射，pdftotext 会吐 Latin-1 字节；
    # UTF-8 解码失败过多时改按 Latin-1 解，避免整页变 \ufffd 被误判为"无文本/扫描件"
    if text.count("\ufffd") > max(3, len(text) // 100):
        alt = stdout.decode("latin-1")
        if alt.count("\ufffd") < text.count("\ufffd"):
            text = alt
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.endswith("\f"):
        text = text[:-1]
    chunks = text.split("\f")
    return [
        {"pdf_page": i, "text": chunk.replace("\x00", "").rstrip()}
        for i, chunk in enumerate(chunks, start=1)
    ]


def _check_pdf_signature(path: str) -> None:
    with open(path, "rb") as fh:
        head = fh.read(1024)
    if b"%PDF-" not in head:
        _err("E_BAD_PDF", f"不像 PDF 文件（缺少 %PDF- 头）：{os.path.basename(path)}",
             "确认扩展名与实际格式一致；纯文本请改名为 .md/.txt")
    if b"/Encrypt" in head:
        _err("E_ENCrypted_PDF", "PDF 已加密，pdftotext 可能无法抽取",
             "先解除密码保护再导入，或提供已转好的 .md")


# ---------------------------------------------------------------------------
# 文本 → 分页 / 分块（启发式，规则见各函数 docstring）
# ---------------------------------------------------------------------------
#: 形式 A：``<!-- page:N -->``（N=教材页）/ ``<!-- page:pdf=64 book=55 -->`` / ``<!-- page:pdf=64 -->``
_PAGE_MARK_A = re.compile(
    r"^<!--\s*page\s*:\s*(?:pdf\s*=\s*)?(\d+)\s*(?:[,;\s]+book\s*=\s*(\d+))?\s*-->$", re.I)
#: 形式 B：``<!-- pdf=64 book=55 -->``（pdf 可省）
_PAGE_MARK_B = re.compile(r"^<!--\s*(?:pdf\s*=\s*(\d+)[,\s]+)?book\s*=\s*(\d+)\s*-->$", re.I)
#: 兼容旧名（其余代码按列表遍历）
_PAGE_MARK_RES = (_PAGE_MARK_A, _PAGE_MARK_B)
_CODE_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_HTML_BLOCK_RE = re.compile(r"^<(?!!/)[A-Za-z][^>]*>$")
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+\S")


def _split_marked_text(text: str) -> list[dict]:
    """把 .md / .txt 切成页，支持三种写法（可混用）：

    1. ``<!-- page:N -->``：**N 是教材页码（book_page）**。``pdf_page`` 由调用方按出现顺序
       编号（1、2、3…），``page_offset`` 随之推断（1、57、58 → 1、2、3 页、offset 56）；
    2. ``<!-- page:pdf=64 book=55 -->`` / ``<!-- pdf=64 book=55 -->``：显式双锚点；
    3. ``\f``（分页符）：等价于"下一页开始"，不携带页码信息。

    页码标记只在**非代码块**的行上生效（避免把 Markdown 示例里的标记当成真页码）。
    一处页码标记都没有时：有 ``\f`` 按 ``\f`` 切页，否则整篇 1 页、``book_page=None``
    ——**不臆造页码**（引用时只给 PDF 页）。

    返回项：``{"label": pdf 标签或 None, "declared_book": 教材页码或 None, "lines": [...]}``；
    ``label`` 仅表示"这一页声明了 pdf 值"。``declared_book`` 是**教材页码**，因此
    ``import_file`` 会把它直接用作 ``book_page``，而不是再用 pdf 顺序号覆盖。
    """
    # 把行内的 \f（"正文\f下一页"）也拆成独立事件：前面部分当正文，\f 当分页
    raw_lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = []
    for ln in raw_lines:
        if "\f" in ln:
            parts = ln.split("\f")
            for k, part in enumerate(parts):
                if k:
                    lines.append("\f")
                if part.strip():
                    lines.append(part)
        else:
            lines.append(ln)

    def marker_of(stripped: str):
        """返回 ``(pdf_label | None, book_page | None)`` 或 ``None``。"""
        m = _PAGE_MARK_A.match(stripped)
        if m:
            first, book_part = m.groups()
            if re.match(r"^<!--\s*page\s*:\s*pdf", stripped, re.I):
                # page:pdf=64 [book=55] → pdf 标签（及可选教材页）
                return int(first), (int(book_part) if book_part else None)
            # page:N → N 是教材页码
            return None, int(first)
        m = _PAGE_MARK_B.match(stripped)  # <!-- pdf=64 book=55 -->
        if m:
            return (int(m.group(1)) if m.group(1) else None), int(m.group(2))
        return None

    def new_page():
        return {"label": None, "declared_book": None, "lines": []}

    pages = []
    cur = new_page()
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if _CODE_FENCE_RE.match(stripped):
            in_fence = not in_fence
            cur["lines"].append(line)
            continue
        if not in_fence:
            # 注意：str.strip() 会把 \x0c 当空白删掉（"\f".strip() == ""），
            # 所以不能依赖 stripped，必须直接判断该行是否只由 \x0c 构成。
            if line and not line.replace("\x0c", "").strip():
                pages.append(cur)
                cur = new_page()
                continue
            found = marker_of(stripped)
            if found is not None:
                # 语义：标记之后的正文属于新页（上一页若有内容则封存）。
                # 若当前页除声明外没有任何正文（例如 `page:1` 打头、或连续两个标记），
                # 视为"版本标记的重复"，就地更新页码而不另开一页。
                if any(ln.strip() for ln in cur["lines"]):
                    pages.append(cur)
                    cur = new_page()
                cur["label"], cur["declared_book"] = found
                continue
        cur["lines"].append(line)
    pages.append(cur)

    out = [pg for pg in pages if "".join(pg["lines"]).strip() or pg["declared_book"] is not None]
    return out or [new_page()]


def _is_control_line(line: str) -> bool:
    """页码标记 / 代码围栏 / HTML 块行：不参与成块，也不参与质量统计。"""
    s = line.strip()
    if not s:
        return False
    if s == "\f" or _CODE_FENCE_RE.match(s) or _HTML_BLOCK_RE.match(s):
        return True
    return any(r.match(s) for r in _PAGE_MARK_RES)


def _is_blank_or_noise(line: str) -> bool:
    """空行 / 页码标记 / 代码围栏 / 成块 HTML 行：不参与成块，也不计入质量统计。"""
    return not line.strip() or _is_control_line(line)


def _line_features(line: str) -> dict:
    """单行特征：地面比例（>=2 字汉字连续段 / 行长）、2+ 位 ASCII 单词数、多列对齐空格数。

    「地面比例」低 = 该行由大量短词拼成（表格数据行 ``样本  数量  比例`` 的典型形态）；
    正常中文行几乎都是连续汉字长串，比值很高。这是「是否表格」最便宜可靠的信号。
    """
    s = line.strip()
    if not s:
        return {"ground": 0.0, "ascii_words": 0, "gaps": 0}
    runs = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]{2,}", s)
    ground = sum(len(r) for r in runs) / max(1, len(s))
    ascii_words = len(re.findall(r"(?<![A-Za-z0-9])[A-Za-z0-9]{2,}(?![A-Za-z0-9])", s))
    gaps = sum(1 for g in re.findall(r" {2,}", line) if len(g) >= 2) + line.count("\t")
    return {"ground": ground, "ascii_words": ascii_words, "gaps": gaps}


def _grounded(s: str) -> bool:
    """是否为「正常中文正文/标题」形态：含 >=2 字汉字连续段且地面比例 >= 0.5。

    用于把表格行、页眉页脚、公式行与正文区分开；单个汉字词（如 ``左  中  右``）不算地面。
    """
    return _line_features(s)["ground"] >= 0.5


def _is_margin_line(line: str) -> bool:
    """页边页码：裸数字、``·56·``、``— 56 —``、``第 56 页``。"""
    s = line.strip()
    if re.fullmatch(r"[0-9]{1,4}", s):
        return True
    if re.fullmatch(r"[•·\-—–~]\s*[0-9]{1,4}\s*[•·\-—–~]", s):
        return True
    return bool(re.fullmatch(r"第\s*[0-9]{1,4}\s*页", s))


def _is_heading_like(s: str) -> bool:
    """标题形态（与语种无关的粗判）：``第X章/节``、``【栏目】``、Markdown 标题、``Section N …``、
    ``Chapter N …``。用于把"编号开头"的标题行从表格/页眉启发式里排除。
    """
    if not s:
        return False
    return bool(_MD_HEADING_RE.match(s)
                or re.match(rf"^第\s*[{_CN_NUM}0-9]+\s*[章节单元]", s)
                or s.startswith("【")
                or re.match(r"(?i)^(?:section|chapter|part|unit|lesson|第\s*[0-9]+\s*[章节课])\b", s))


def _is_table_row(line: str) -> bool:
    """表格行判定。强特征（``图X-Y`` / ``＝ ≈ × →`` / 单位词）优先：命中即**不是**表格行。

    否则命中任一即为表格行：
      1. 行内 >=2 个 ``|``（Markdown / 排版表格）；
      2. 含 ``\t``；
      3. 「多列脚手架」：>=2 处 2+ 连续空格，且（>=2 个 2+ 位 ASCII 单词 或 地面比例 < 0.5），
         且该行本身不是正常中文地面（排除「这  是  一句话」这类疏排正文）。
    """
    s = line.strip()
    if not s:
        return False
    if _STRONG_TABLE_RE.search(s):
        return False
    if _is_heading_like(s):
        return False  # 标题行（"Section 1 DNA structure"）不是表格
    if s.count("|") >= 2 or "\t" in line:
        return True
    f = _line_features(line)
    if f["gaps"] >= 2 and not _grounded(s):
        if f["ascii_words"] >= 2 or f["ground"] < 0.5:
            return True
    # pdftotext 有时把表格压平成 "control 40 0.50" 这类无对齐空格的单行
    return _is_data_row(s) and f["ground"] < 0.5


def _is_heading_line(s: str) -> bool:
    """标题行判定（均为可解释的版面启发式，按顺序命中即返回）。"""
    if not s:
        return False
    if _MD_HEADING_RE.match(s):
        return True
    if len(s) > 40:
        return False
    if re.search(r"[。！？；]", s) or s.endswith(("，", "、", "：", ":")):
        return False
    if re.match(rf"^第\s*[{_CN_NUM}0-9]+\s*[章单元]", s):
        return True
    if re.match(rf"^第\s*[{_CN_NUM}0-9]+\s*[节课讲]", s):
        return True
    if s.startswith("【") and len(s) >= 3:
        return True
    if re.match(r"^图\s*[0-9０-９一二三四五六七八九十:：]", s):
        return False  # 图注不是标题
    # 全角标题：2..16 字、首字符非 ASCII、无标点/括号/表格符、非纯数字或纯符号
    if 2 <= len(s) <= 16 and not s[0].isascii() \
            and not re.search(r"[，,、：:；;。！？（）()\[\]{}|＝=　]", s) \
            and not re.fullmatch(r"[0-9\s.\-—–]+", s) \
            and re.search(r"[\u4e00-\u9fffA-Za-z]", s):
        return True
    return False


def _is_caption(s: str) -> bool:
    """图注行：含 ``图X-Y`` / ``图 X.Y``（中文数字序号也算），或以 ``图 `` 开头。"""
    return bool(re.search(r"图\s*[0-9０-９一二三四五六七八九十]+(?:[-－—.．][0-9０-９]+)?", s)
                or re.match(r"^图\s*[:：\s]", s))


def _classify_line(s: str) -> str:
    """单行类型：figure_caption / heading / formula / paragraph（按优先级）。

    * ``figure_caption`` 最先判：`「图3-2 DNA半保留复制过程」`这类短行否则会被"全角短标题"
      规则吞成 heading。
    * ``formula`` 其次：``c = a ＝ b × 0.5 mol`` 这类无汉字行也不能当标题。
    """
    if _is_caption(s):
        return "figure_caption"
    if _is_heading_like(s) or _is_heading_line(s):
        return "heading"
    if re.search(r"[＝≈×→]", s) or _UNIT_RE.search(s):
        # 正常中文长句里偶含「→ / pH」等取样词时让位于段落：>36 字且 <=1 个数学符号且为中文地面
        if len(s) > 36 and len(re.findall(r"[＝≈×→]", s)) <= 1 and _grounded(s):
            return "paragraph"
        return "formula"
    return "paragraph"


def _join_or_new(prev_text: str, nxt: str):
    """判断下一行是否应与上一行拼接：返回 ``(True, merged)`` 或 ``(False, nxt)``。

    * 行尾连字符 ``-`` + 小写开头 → 去连字符直拼（PDF 换行断词）；
    * 上一行 >=60 字且未以句末标点结束 → 视为同一段落被版面折断，直拼。
    """
    tail = prev_text.rstrip()
    if not tail:
        return False, nxt
    if tail.endswith("-") and re.match(r"^[a-z]", nxt):
        return True, tail[:-1] + nxt
    if len(tail) >= 60 and not tail.endswith(TERMINAL_PUNCT_ALL) \
            and not tail.endswith((":", "：")):
        # ASCII 词之间补空格（pdftotext -layout 断行会吃掉词边界），CJK 直拼
        glue = " " if tail[-1:].isascii() and nxt[:1].isascii() and not tail.endswith(" ") else ""
        return True, tail + glue + nxt
    return False, nxt


#: 英文"数据行"判定阈值：短词数 / 短词总长。正常英文句 < 0.3，表格数据行 > 0.4
DATA_ROW_DENSITY = 0.36


def _dense_features(s: str) -> dict:
    """短词密度：``short_tokens / token_chars``。

    ``control 40 0.50`` → 3/5+2+4≈0.5（数据行）；
    ``A mixture was heated and then cooled`` → 10/30≈0.33（自然语言）。
    """
    tokens = re.findall(r"[A-Za-z0-9]+(?:\.[0-9]+)?", s)
    token_chars = sum(len(t) for t in tokens)
    short = sum(1 for t in tokens if len(t) <= 4)
    return {"ground": len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]{2,}", s)) / max(1, len(s)),
            "density": short / max(1, token_chars),
            "tokens": len(tokens)}


def _is_data_row(s: str) -> bool:
    """数据行形态（表格数据 / 页脚统计行）：2+ 个 2+ 位词（数字也算）、无中文句读、
    行较短、地面比例低。这类行既不是页眉页脚，也不该被当作段落。
    """
    s = (s or "").strip()
    if not s or len(s) >= 60 or re.search(r"[。！？；，、]", s):
        return False
    # 中文正文几乎总含 2 字以上汉字连续段：地面比例够高就不是数据行
    if _line_features(s)["ground"] >= 0.5:
        return False
    # 纯英文数据行要看"密度"：短词数占比低（如 "A mixture was heated and then cooled"）属正文
    f = _dense_features(s)
    has_number = bool(re.search(r"(?<![A-Za-z])[0-9]+(?:\.[0-9]+)?(?![A-Za-z])", s))
    return f["ground"] < 0.6 and f["density"] >= DATA_ROW_DENSITY and has_number


def _is_running_head(s: str) -> bool:
    """页眉页脚候选：``<=40 字的短行``，且不是表格行 / 图注 / 公式。

    **不排除标题行**——版式页眉常常就是「第3章 基因的本质」这样的章节名。
    中文正文段落（>=40 字，或以句末标点收尾且 >20 字）因此不会被误删；
    且 ``_trim_margins`` 只从页首 / 页尾**连续**剥离，中间的小标题不受影响。
    """
    s = (s or "").strip()
    if not s or len(s) > 40:
        return False
    # 以句末标点结尾 = 完整句子，不是页眉页脚（页脚通常是"·56·"或裸数字，已在别处处理）
    if s.endswith(("。", "！", "？", "；", ".", "!", "?", ";")):
        return False
    # Markdown 标题是**文档结构**而非版式页眉，永不当页眉页脚处理
    if _MD_HEADING_RE.match(s):
        return False
    # 短英文/短中文行（<=28 字）即使缺乏中文"地面"也算候选（如 "Chapter 3 The Nature of the Gene"）；
    # 正文句子几乎不会这么短、且不含句读。
    if len(s) <= 28 and not re.search(r"[。！？；]", s):
        return True
    if _is_data_row(s):
        return False
    if _is_table_row(s) or _is_caption(s) or _classify_line(s) == "formula":
        return False
    # 中文标题形态（"第3章 …"、"【…】"）属于内容而不是页眉，单段即排除；
    # 英文 "Chapter 3 …" / "Section 1 …" 在中文教材里几乎只会出现在页眉，
    # 且其后的真标题（"Section 1 DNA structure"）仍受"跨页重复"约束，不会被误删。
    return not (s.startswith(("第", "【")) and _is_heading_like(s))


def _heading_number(s: str):
    """标题的编号键：``第3章 基因的本质`` → ``("章", "3")``；``第1节 DNA…`` → ``("节", "1")``。

    仅对 ``第X章 / 第X节 / 第X单元`` 形态生效，用于页眉识别；其它返回 ``None``。
    """
    m = re.match(rf"^第\s*([{_CN_NUM}0-9]+)\s*([章节单元])", s or "")
    if not m:
        return None
    return (m.group(2), _cn_to_int(m.group(1)))


def _cn_to_int(text: str) -> int:
    """把 ``3`` / ``三`` / ``十二`` 形式的编号转成整数（失败返回 -1）。"""
    if not text:
        return -1
    if text.isdigit():
        return int(text)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
    if text == "十":
        return 10
    if "十" in text:
        left, _, right = text.partition("十")
        tens = digits.get(left, -1) if left else 1
        ones = digits.get(right, -1) if right else 0
        if tens < 0 or ones < 0:
            return -1
        return tens * 10 + ones
    value = 0
    for ch in text:
        if ch not in digits:
            return -1
        value = value * 10 + digits[ch]
    return value


def _split_columns(line: str) -> list:
    """把一行按「>=3 连续空格」切成若干列片段（页眉常是「左书名 + 右章名」两栏）。

    只有出现真正的列间大空白才切分；返回的每段都已 strip，空段丢弃。
    """
    s = (line or "").strip()
    if not s:
        return []
    segs = [seg.strip() for seg in re.split(r" {3,}", s) if seg.strip()]
    return segs


def _margin_candidates(page_lines: list) -> dict:
    """单页的页眉/页脚候选。

    返回 ``{"lines", "drop": {行号}, "front": [文本...], "back": [文本...]}``：

    * ``drop``：页边页码行（任意位置）+ 双区域页眉行（整行丢弃）；
    * ``front`` / ``back``：从页首 / 页尾起**连续**的候选文本，最多各 3 行；
      遇到第一个非候选行即停。双区域行（``左书名   右章名``）按列拆分，每段各算一个候选。
    """
    idx = [i for i, ln in enumerate(page_lines) if ln.strip() and not _is_margin_line(ln)]
    drop = {i for i, ln in enumerate(page_lines) if ln.strip() and _is_margin_line(ln)}
    front, back = [], []
    lane = 0
    i = 0
    while i < len(idx) and i < 3:
        ln = page_lines[idx[i]]
        segs = _split_columns(ln)
        if len(segs) > 1 and all(_is_running_head(seg) for seg in segs):
            drop.add(idx[i])
            front.append({"band": lane, "text": segs[0], "segs": segs})
            lane += 1
        elif _is_running_head(ln):
            front.append({"band": lane, "text": ln.strip(), "segs": [ln.strip()]})
            lane += 1
        else:
            break
        i += 1
    tail = idx[-3:] if len(idx) >= 3 else idx
    for pos in range(len(tail) - 1, -1, -1):
        ln = page_lines[tail[pos]]
        if tail[pos] in drop:
            continue
        segs = _split_columns(ln)
        if len(segs) > 1 and all(_is_running_head(seg) for seg in segs):
            drop.add(tail[pos])
            back.append({"band": lane, "text": segs[0], "segs": segs})
            lane += 1
        elif _is_running_head(ln):
            back.append({"band": lane, "text": ln.strip(), "segs": [ln.strip()]})
            lane += 1
        else:
            break
    return {"lines": page_lines, "drop": drop, "front": front, "back": back}


def _trim_margins(pages: list) -> list:
    """去掉页眉页脚行，返回逐页处理后的行列表（与输入同序）。

    一个页首/页尾行为「版式页眉页脚」需**同时**满足：

    1. **形态**（``_is_running_head``）：<=40 字短行，且不是表格 / 图注 / 公式 /
       Markdown 标题 / 数据行；``第3章 …`` / ``【…】`` 这类中文标题形态单段排除，
       ``Chapter 3 …`` / ``Section 1 …`` 允许作候选（中文教材里它们几乎只出现在页眉）；
    2. **位置**：只从页首 / 页尾**连续**剥离，最多各 3 行；``左书名   右章名`` 双区域页眉
       按列拆成两个候选；
    3. **同条带跨页重复**：候选文本须在 **band 0**（最靠近页边的那一段）上至少出现在 2 页，
       且文档 >=3 页。"Section 1 DNA structure" 落在 band 1 且只出现在第 1 页 →
       不是页眉，从它开始**不再向上/向下剥离**；"Textbook of Biology" 每页 band 0 都在 → 去掉。

    页边页码（裸数字 / ``第N页`` / ``·56·``）不分位置一律丢弃。
    单页调用时无法跨页确认：只去页码，其余候选一律保留（宁多留勿误删）。
    """
    cands = [_margin_candidates([ln.rstrip() for ln in page]) for page in pages]
    confirm = len(cands) >= 3

    def band_counts(key):
        counts = {}
        for cand in cands:
            for item in cand[key]:
                if item["band"] == 0:
                    counts[item["text"]] = counts.get(item["text"], 0) + 1
        return counts

    def strip_plan(items, counts):
        """返回应剥离的候选列表（连续前缀/后缀，直到遇到不再重复的候选）。"""
        plan = []
        for item in items:
            repeated = confirm and counts.get(item["text"], 0) >= 2
            headingish = item["text"].startswith(("第", "【")) and _is_heading_like(item["text"])
            if repeated and not headingish:
                plan.append(item)
                continue
            break
        return plan

    front_counts, back_counts = band_counts("front"), band_counts("back")
    out = []
    for cand in cands:
        lines = cand.pop("lines")
        drop = set(cand.pop("drop"))
        front = strip_plan(cand.pop("front"), front_counts)
        back = strip_plan(cand.pop("back"), back_counts)
        wanted_front = []
        wanted_back = []
        for item in front:
            wanted_front.extend(item["segs"])
        for item in back:
            wanted_back.extend(item["segs"])
        remaining = [ln for i, ln in enumerate(lines) if i not in drop]

        def take(seq, wanted, from_top):
            """在 seq 中按顺序移除 wanted 中的文本（整行相等，或列拆分后全部命中）。"""
            pool = [(k, ln) for k, ln in enumerate(seq) if ln is not None and ln.strip()]
            pos = 0 if from_top else -1
            for text in (wanted if from_top else list(reversed(wanted))):
                while pool:
                    pool_pos = 0 if from_top else -1
                    k, ln = pool[pool_pos]
                    cells = [c.strip() for c in re.split(r" {3,}", ln.strip()) if c.strip()]
                    if text in cells:
                        cells.remove(text)
                        if cells:
                            seq[k] = "  ".join(cells)  # 双区域行：只去掉命中的那一栏
                        else:
                            seq[k] = None
                        pool = [(kk, ll) for kk, ll in pool if kk != k]
                        break
                    pool.pop(pool_pos)
                else:
                    break
            return seq

        remaining = take(remaining, wanted_front, True)
        remaining = take(remaining, wanted_back, False)
        tidy = []
        for ln in remaining:
            if ln is None:
                continue
            if not ln.strip():
                if tidy and tidy[-1].strip():
                    tidy.append("")
                continue
            tidy.append(ln)
        while tidy and not tidy[-1].strip():
            tidy.pop()
        out.append(tidy)
    return out


def _is_continuation(prev_text: str, nxt: str) -> bool:
    """公式块之后紧跟的短段落：是否为同一句话被版面折断（是则直拼，不另立段落）。"""
    tail = prev_text.rstrip()
    if not tail or len(tail) > 60 or tail.endswith(TERMINAL_PUNCT_ALL):
        return False
    return not _is_heading_line(nxt) and not re.match(r"^(?:图|表)\s*[0-9０-９一二三四五六七八九十]", nxt)


def _blocks_from_text(text: str, *, trimmed: list | None = None) -> list[dict]:
    """把一段页文本切成 blocks。

    规则（按优先级，全部可解释、可单测）：

    1. **清场**：空行 / 页码标记 / 代码围栏 / 成块 HTML 行不进块，也不计入质量统计
       （见 ``_is_blank_or_noise``）；随后 ``_trim_margins`` 去页眉页脚。
    2. **表格**：连续 >=1 条表格行（见 ``_is_table_row``）合成一个 ``table`` 块，块内保留
       空行（跨页表格的空格行不丢）；表格行之间的空行不打断表格。
    3. **逐行分类**（见 ``_classify_line``）：
       ``heading`` / ``figure_caption`` / ``formula`` / ``paragraph``。
    4. **合并**：相邻同类型 ``paragraph`` / ``formula`` 行合并（续行按 ``_join_or_new``
       去连字符直拼或加换行）；``heading`` / ``figure_caption`` 一行一块，
       避免把「第1节…」「第2节…」粘成一块；相邻 ``table`` 块并入前一块。
    """
    if not isinstance(text, str) or not text.strip():
        return []
    if trimmed is not None:
        # import_file 已做跨页页眉页脚去噪（能区分"每页都有的页眉"与"只出现一次的节标题"）
        kept = [ln.rstrip() for ln in trimmed if not _is_blank_or_noise(ln)]
    else:
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        kept = [ln.rstrip() for ln in lines if not _is_blank_or_noise(ln)]
        kept = _trim_margins([kept])[0]  # 单页：保守模式，只去页码

    # 单元流：(kind, payload)；kind ∈ {table, line, blank}
    units = []
    for raw in kept:
        if not raw.strip():
            if units and units[-1][0] == "table":
                units.append(["blank", None])
            continue
        if _is_table_row(raw):
            row = raw.strip()
            if units and units[-1][0] == "table":
                units[-1][1].append(row)
            else:
                units.append(["table", [row]])
            continue
        s_line = raw.strip()
        btype = _classify_line(s_line)
        if btype == "paragraph" and units and units[-1][0] == "line" \
                and units[-1][1] == "formula" and _is_continuation(units[-1][2], s_line):
            units.append(["join", s_line])
            continue
        units.append(["line", btype, s_line])

    blocks = []
    for unit in units:
        kind = unit[0]
        payload = unit[1] if kind != "line" else unit[2]
        if kind == "blank":
            if blocks and blocks[-1]["type"] == "table":
                blocks[-1]["text"] += "\n"
            else:
                # 段落内空白行 = 版面换行断开的同一段：保留断开信息，避免丢内容
                if blocks and blocks[-1]["type"] in ("paragraph", "formula"):
                    blocks[-1].setdefault("_soft_breaks", 0)
                    blocks[-1]["_soft_breaks"] += 1
            continue
        if kind == "table":
            txt = "\n".join(payload).strip("\n")
            if not txt:
                continue
            if blocks and blocks[-1]["type"] == "table":
                blocks[-1]["text"] += "\n" + txt
            else:
                blocks.append({"type": "table", "text": txt})
            continue
        if kind == "join":
            if blocks:
                blocks[-1]["text"] += payload if payload.startswith(" ") else "\n" + payload
            continue
        btype = unit[1]
        prev = blocks[-1] if blocks else None
        if prev and prev["type"] == btype and btype == "paragraph":
            do_join, merged = _join_or_new(prev["text"], payload)
            prev["text"] = merged if do_join else prev["text"] + "\n" + payload
            continue
        if prev and prev["type"] == btype and btype == "formula":
            prev["text"] += "\n" + payload
            continue
        blocks.append({"type": btype, "text": payload})
    # 收尾：去掉暂存的软换行标记（仅用于段落合并时的连接方式判断）
    for blk in blocks:
        blk.pop("_soft_breaks", None)
        blk["text"] = blk["text"].rstrip("\n")
    return [b for b in blocks if b["text"].strip()]


def _strip_controls(text: str) -> str:
    keep = [ln for ln in text.split("\n") if not _is_control_line(ln)]
    return "\n".join(keep)


def _quality_of_page(text: str, blocks: list, margin_lines: list | None = None) -> dict:
    """质量指标：``han_ratio = 汉字数 / max(1, 非空字符数)``；``effective_chars`` 为非空字符数。

    低于 ``HAN_RATIO_MIN``（0.15）或 ``effective_chars < MIN_EFFECTIVE_CHARS``(50) 记为
    ``low_quality``。纯英文论文本来汉字为 0→必然 low_quality，此时若 ``effective_chars``
    充足且能切出 ASCII 词，附注 ``reason`` 提示"英文/公式页"，避免把正常英文页当抽取失败。

    ``margin_lines``：页首/页尾 2 行的**原始**文本（去页眉页脚之前），其中可能含印刷页码；
    它让 ``page_offset`` 在导入之后仍可推断 / 补算（见 ``infer_page_offset``）。
    """
    nonempty = [c for c in text if not c.isspace()]
    han = len(_HAN_RE.findall("".join(nonempty)))
    eff = len(nonempty)
    ascii_words = len(re.findall(r"[A-Za-z]{3,}", text))
    han_ratio = han / max(1, eff)
    reasons = []
    if han_ratio < HAN_RATIO_MIN:
        reasons.append(f"汉字覆盖率 {han_ratio:.2f} < {HAN_RATIO_MIN}")
    if eff < MIN_EFFECTIVE_CHARS:
        reasons.append(f"有效字符 {eff} < {MIN_EFFECTIVE_CHARS}")
    if reasons and eff >= MIN_EFFECTIVE_CHARS and ascii_words >= 30:
        reasons.append(f"可能为英文/公式页（{ascii_words} 个英文词），若非本意请人工核对")
    return {
        "han_ratio": round(han_ratio, 4),
        "effective_chars": eff,
        "blocks": len(blocks),
        "low_quality": bool(reasons),
        "reasons": reasons,
        "margin_lines": margin_lines or [],
    }


# ---------------------------------------------------------------------------
# 导入
# ---------------------------------------------------------------------------
def _page_margin_lines(page: dict) -> list:
    """从**已落盘**的 page 记录里还原"页首/页尾供页码推断用的行"。

    ``pages/NNN.json`` 的 blocks 已去掉页眉页脚，页码可能因此丢失；故导入时把
    含印刷页码的候选行（页首/页尾 2 行）存进 ``quality["margin_lines"]`` 供
    page_offset 推断与 --page-offset 补算使用。
    """
    if page.get("lines") is not None:
        return list(page["lines"])
    if page.get("text") is not None:
        return str(page["text"]).split("\n")
    return list((page.get("quality") or {}).get("margin_lines") or [])


def _select_page_offset(pages: list, explicit) -> dict:
    """推断 page_offset（``book_page = pdf_page - page_offset``）。

    证据 = 每页的「印刷页码」：显式 ``book=`` 声明 + 页边扫到的数字（页眉/页脚/标记前的孤立页码）。
    差值 ``pdf_page - 印刷页码`` 若在多页一致，即为 page_offset。

    ==================  ==============================================
    offset_source       条件
    ==================  ==============================================
    ``explicit``        调用方显式给定
    ``marker``          页内有页码声明（``<!-- page:N -->`` / ``book=``）且众数支持 >= 2 页
    ``inferred``        只靠页边印刷页码，>=3 页另有证据、众数支持 >= 2 页
    ``default``         证据不足（< 2 页）：offset=0，且 ``book_page`` 全部留空，**不猜页码**
    ==================  ==============================================

    并列时优先**非负**差值（书页码 <= PDF 页是常态）。
    """
    if explicit is not None:
        if isinstance(explicit, bool) or not isinstance(explicit, int):
            _err("E_BAD_ARGS", "page_offset 必须是整数", "例如 --page-offset 9")
        return {"offset": int(explicit), "source": "explicit"}

    votes = {}
    declared_pages = 0
    margin_pages = 0
    for page in pages:
        pdf_no = int(page["pdf_page"])
        # 声明页码优先；本页没有声明时才用页边印刷页码兜底
        # 注意：原始页**总有** declared_book 键（值是 None），所以不能只靠 get 的默认参数
        declared = page.get("declared_book")
        if declared is None and "declared_book" not in page:
            declared = page.get("book_page")
        if declared is not None:
            books = {int(declared)}
            declared_pages += 1
        else:
            books = set(_margin_page_numbers(_page_margin_lines(page)))
            if books:
                margin_pages += 1
        for book_no in books:
            gap = pdf_no - book_no
            votes[gap] = votes.get(gap, 0) + 1
    if not votes:
        return {"offset": 0, "source": "default"}

    best = max(votes.values())
    # 证据一致性：支持众数的页面数应当就是"能给出页码的页面数"。
    # 若多半页面的差值彼此不同（连 ``page:N`` 的 N 都对不上顺序），说明标记不是规范页码
    # （例如 page:1 开头、后面少了页），此时宁可留空，也不给一个错误的整体偏移。
    informative = max(len(pages), sum(votes.values()))
    if best != informative:
        return {"offset": 0, "source": "default"}
    tied = sorted(d for d, n in votes.items() if n == best)
    non_neg = [d for d in tied if d >= 0]
    offset = non_neg[0] if non_neg else tied[0]

    if best >= 2 and declared_pages == informative:
        return {"offset": offset, "source": "marker"}
    if best >= 2 and margin_pages >= 3:
        return {"offset": offset, "source": "inferred"}
    return {"offset": 0, "source": "default"}


def _margin_page_numbers(lines: list) -> list:
    """取出页首 / 页尾（各自 <=2 个非空行）里"独占一格"的数字（1..4 位）——典型印刷页码。

    只在页边取，避免把正文末尾的年份（"……1998"）当成页码。
    """
    nonempty = [i for i, ln in enumerate(lines) if ln.strip()]
    cand = nonempty[:2] + nonempty[-2:]
    nums = []
    for i in sorted(set(cand)):
        s = lines[i].strip()
        if re.fullmatch(r"[0-9]{1,4}", s):
            nums.append(int(s))
        elif re.fullmatch(r"[•·\-—–~]\s*[0-9]{1,4}\s*[•·\-—–~]", s):
            nums.append(int(re.search(r"[0-9]+", s).group(0)))
        elif re.fullmatch(r"第\s*[0-9]{1,4}\s*页", s):
            nums.append(int(re.search(r"[0-9]+", s).group(0)))
        elif re.fullmatch(r"(?:-|–|—)?\s*[0-9]{1,4}\s*(?:-|–|—)", s):  # "56-"
            nums.append(int(re.search(r"[0-9]+", s).group(0)))
    return nums


def _normalize_meta(meta: dict, corpus_id: str, kind: str) -> dict:
    if not isinstance(meta, dict):
        _err("E_BAD_META", "meta 必须是 dict", "至少给出 {kind, title}")
    kind = meta.get("kind", kind)
    if kind not in CORPUS_KINDS:
        _err("E_BAD_META", f"kind 非法：{kind!r}", f"可选：{', '.join(CORPUS_KINDS)}")
    title = (meta.get("title") or "").strip()
    if not title:
        _err("E_BAD_META", "meta.title 不能为空", "标题会出现在引用里（如「教材P.55」前的书名）")
    evidence = (meta.get("evidence_level") or "unknown").strip()
    if evidence not in EVIDENCE_LEVELS:
        _err("E_BAD_META", f"evidence_level 非法：{evidence!r}", f"可选：{', '.join(EVIDENCE_LEVELS)}")
    scope = (meta.get("scope") or "").strip()
    if kind == "paper" and evidence == "unknown":
        _err("E_BAD_META", "论文必须给出 evidence_level",
             f"按证据强度标注（{', '.join(x for x in EVIDENCE_LEVELS if x != 'unknown')}），"
             "unknown 会被下游降级为'不可引用证据'")
    if kind == "paper" and not scope:
        _err("E_BAD_META", "论文必须填写 scope（样本与情境）",
             "例如「N=120，高一，某市重点中学，单次干预」——缺样本信息的论文引用会误导教学决策")
    lq = meta.get("low_quality_pages") or []
    if not isinstance(lq, (list, tuple)):
        _err("E_BAD_META", "low_quality_pages 必须是整数列表")
    out = {
        "corpus_id": corpus_id,
        "kind": kind,
        "title": title,
        "publisher": (meta.get("publisher") or "").strip(),
        "edition": str(meta.get("edition") or "").strip(),
        "subject": (meta.get("subject") or "").strip(),
        "volume": (meta.get("volume") or "").strip(),
        "page_offset": 0,
        "pages_total": 0,
        "evidence_level": evidence,
        "scope": scope,
        "caveat": (meta.get("caveat") or "").strip(),
        "provenance": (meta.get("provenance") or "").strip(),
        "low_quality_pages": [int(x) for x in lq],
    }
    return out


def import_file(file_path, meta: dict, page_offset: int | None = None, dry_run: bool = False) -> dict:
    """导入教材 / 课标 / 论文 / 自制材料，生成 manifest + 每页 ``pages/NNN.json``。

    * ``.pdf``：``pdftotext -layout`` 抽取；不可用抛 ``E_NO_EXTRACTOR``（提示安装
      poppler-utils 或改用 md）。
    * ``.md`` / ``.txt``：按 ``<!-- page:N -->`` 或 ``\\f`` 切页；无页码标记时整篇 1 页、
      ``book_page=None``。
    * 其它扩展名：``E_UNSUPPORTED``。

    默认 ``dry_run=False`` 会真正落盘；``dry_run=True`` 只解析并返回报告，不写任何文件。

    返回::

        {"ok", "corpus_id", "pages_total", "low_quality_pages", "dry_run", "samples": [...],
         "page_offset", "offset_source", "warnings": [...]}

    安全：``corpus_id`` 过正则；已存在的 ``corpus_id`` 属于**另一份文件**（sha256 不同）时
    拒绝覆盖（防误删已导入语料），需先 ``remove(force=True)`` 或换 id；同一文件重复导入
    （sha256 相同）是幂等的。
    """
    path = _check_input_file(file_path)
    if not isinstance(meta, dict):
        _err("E_BAD_META", "meta 必须是 dict", "至少给出 {corpus_id, kind, title}")
    corpus_id = (meta.get("corpus_id") or "").strip()
    cdir = _corpus_dir(corpus_id)  # 同时完成正则 / 越界校验
    kind_hint = meta.get("kind") or "personal"
    meta_norm = _normalize_meta(meta, corpus_id, kind_hint)

    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        _check_pdf_signature(path)
        raw_pages = _extract_pdf_pages(path)
        source_name = "source.pdf"
    elif ext in (".md", ".txt", ".markdown"):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            _err("E_READ_FAILED", f"读取失败：{exc}")
        raw_pages = _split_marked_text(text)
        source_name = "source" + ext
        for seq, page in enumerate(raw_pages, start=1):
            # 声明了 pdf= 就用它（允许中间缺页）；只有 book= 时用顺序号，保持唯一且单调
            page["pdf_page"] = page["label"] if page.get("label") is not None else seq
    else:
        _err("E_UNSUPPORTED", f"不支持的扩展名：{ext or '(无)'}",
             "支持 .pdf / .md / .txt；扫描版 PDF 请先 OCR，再导出为带 `<!-- page:N -->` 的 .md")

    offset_info = _select_page_offset(raw_pages, page_offset)
    offset = offset_info["offset"]

    pages_out = []
    lq = []
    sorted_raw = sorted(raw_pages, key=lambda p: p.get("pdf_page") or 0)
    # 一整本一起做页眉页脚去噪：只有"多页重复出现"的短行才判为版式页眉页脚
    raw_line_sets = []
    for page in sorted_raw:
        if page.get("lines") is not None:
            raw_text = "\n".join(page["lines"])
        else:
            raw_text = page.get("text") or ""
        raw_line_sets.append(_strip_controls(raw_text).split("\n"))
    trimmed_sets = _trim_margins(raw_line_sets) if raw_line_sets else []
    for page, trimmed_lines in zip(sorted_raw, trimmed_sets):
        pdf_no = int(page.get("pdf_page") or (len(pages_out) + 1))
        text = "\n".join(trimmed_lines)
        if page.get("declared_book") is not None and offset_info["source"] != "explicit":
            # 标记里写的是教材页码 → 直接作为 book_page（不再用 pdf 顺序号覆盖）；
            # 若调用方**显式**给了 page_offset，则以显式值为准（约定：book = pdf - offset）
            book_page = int(page["declared_book"])
        elif offset_info["source"] == "default":
            book_page = None
        else:
            book_page = pdf_no - offset
        blocks = _blocks_from_text(text, trimmed=trimmed_lines)
        section = _section_of(text, blocks)
        raw_lines = raw_line_sets[len(pages_out)] if len(pages_out) < len(raw_line_sets) else []
        margin_lines = [ln for ln in raw_lines[:2] + raw_lines[-2:] if ln.strip()] if raw_lines else []
        record = {
            "pdf_page": pdf_no,
            "book_page": book_page,
            "section": section,
            "blocks": blocks,
            "quality": _quality_of_page(text, blocks, margin_lines),
            "low_quality": False,
        }
        record["low_quality"] = record["quality"]["low_quality"]
        if record["low_quality"]:
            lq.append(book_page if book_page is not None else pdf_no)
        pages_out.append(record)

    warnings = []
    if offset_info["source"] == "default" and ext not in (".md", ".txt", ".markdown"):
        warnings.append("未能推断 page_offset（PDF 无页眉页脚页码）：book_page 设为空，"
                        "引用时只给 PDF 页；若有偏移请用 page_offset 显式指定")
    if offset_info["source"] == "inferred":
        warnings.append(f"page_offset={offset} 由页边距页码推断，请用 sample 页核对后保留或修正")
    if lq:
        warnings.append(f"{len(lq)} 页抽取质量偏低（{', '.join(map(str, lq[:8]))}…），"
                        "检索命中这些页时会标记 low_quality")
    if not any(p["blocks"] for p in pages_out):
        warnings.append("未抽取到任何文本块：PDF 可能是扫描件，需先 OCR 或改用 md")

    sha = _sha256_file(path)
    existing = None
    manifest_path = os.path.join(cdir, "manifest.json")
    if os.path.isfile(manifest_path):
        try:
            existing = _read_json(manifest_path)
        except (OSError, ValueError):
            existing = {"sha256": None}
        if existing.get("sha256") and existing.get("sha256") != sha:
            _err("E_CORPUS_EXISTS",
                 f"语料 {corpus_id} 已存在且来源不同（sha256 不一致）",
                 f"如需替换请先 remove({corpus_id!r}, force=True)；或用不同 corpus_id 并存")

    occupied = {p["pdf_page"] for p in pages_out}
    extra_low = [int(x) for x in meta_norm["low_quality_pages"] if int(x) in occupied]
    all_low = sorted(set(lq) | set(extra_low))

    result = {
        "ok": True,
        "corpus_id": corpus_id,
        "pages_total": len(pages_out),
        "low_quality_pages": all_low,
        "dry_run": bool(dry_run),
        "samples": _page_summaries(pages_out, 3),
        "page_offset": offset,
        "offset_source": offset_info["source"],
        "warnings": warnings,
        "kind": meta_norm["kind"],
        "title": meta_norm["title"],
        "sha256": sha,
    }
    if dry_run:
        return result

    manifest = dict(meta_norm)
    manifest.update({
        "page_offset": offset,
        "offset_source": offset_info["source"],
        "pages_total": len(pages_out),
        "low_quality_pages": all_low,
        "sha256": sha,
        "source_file": source_name,
        "source_size": os.path.getsize(path),
        "imported_at": _now_iso(),
    })

    # ---- 落盘（先全部写 tmp，最后原子替换 manifest 作为提交点；异常则回滚） ----
    created_dir = not os.path.isdir(cdir)
    _ensure_dir(cdir)
    pages_dir = _ensure_dir(os.path.join(cdir, "pages"))
    tmp_files = []
    staged = []
    try:
        for page in pages_out:
            final = os.path.join(pages_dir, _safe_page_file(page["pdf_page"]))
            payload = json.dumps(page, ensure_ascii=False, indent=2) + "\n"
            fd, tmp = tempfile.mkstemp(dir=pages_dir, prefix=".page.", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            tmp_files.append(tmp)
            staged.append((tmp, final))
        src_final = os.path.join(cdir, source_name)
        fd, src_tmp = tempfile.mkstemp(dir=cdir, prefix=".source.", suffix=".tmp")
        with os.fdopen(fd, "wb") as out, open(path, "rb") as inp:
            shutil.copyfileobj(inp, out, 1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
        tmp_files.append(src_tmp)
        staged.append((src_tmp, src_final))
        for tmp, final in staged:
            os.replace(tmp, final)
        tmp_files = []
        # 旧页文件（页码变少时）清理：只删本次未覆盖的 NNN.json
        keep = {os.path.basename(f) for _, f in staged}
        for name in os.listdir(pages_dir):
            if name.endswith(".json") and name[:-5].isdigit() and name not in keep:
                os.unlink(os.path.join(pages_dir, name))
        _write_json(manifest_path, manifest)
    except BaseException:
        for tmp in tmp_files:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        if created_dir:
            shutil.rmtree(cdir, ignore_errors=True)
        raise

    try:
        result["indexed_pages"] = build_index(corpus_id)["indexed_pages"]
    except ShibanError as exc:  # 索引失败不影响语料可用性，但必须让调用方知道
        result["warnings"].append(f"索引失败：{exc.code} {exc.message}")
    result["manifest"] = manifest
    return result


def _section_of(text: str, blocks: list) -> str:
    headings = [b["text"].strip() for b in blocks if b["type"] == "heading"]
    return headings[0] if headings else ""


def _page_summaries(pages: list, n: int = 3) -> list:
    """取 n 页摘要：优先首页、中间页、末页；每页给前两个非空块。"""
    if not pages:
        return []
    idx = sorted({0, len(pages) // 2, len(pages) - 1})[:n]
    out = []
    for i in idx:
        page = pages[i]
        body = [b for b in page.get("blocks") or [] if b.get("text", "").strip()][:2]
        out.append({
            "pdf_page": page["pdf_page"],
            "book_page": page.get("book_page"),
            "section": page.get("section", ""),
            "low_quality": page.get("low_quality", False),
            "blocks": [{"type": b["type"], "text": b["text"][:160]} for b in body],
            "text_head": _page_plain_text(page)[:200],
        })
    return out


def infer_page_offset(corpus_id) -> dict:
    """从已落盘页面的 ``quality.margin_lines`` 推断 page_offset，并**回填** book_page + 重建索引。

    适用场景：导入时取不到页码（``offset_source == "default"``），事后发现 PDF 页脚有印刷页码。
    返回 ``{"ok","corpus_id","page_offset","offset_source","updated_pages"}``；
    无法推断时返回 ``offset_source="default"`` 且不改动任何文件。
    """
    cdir = _corpus_dir(corpus_id)
    manifest = get_corpus(corpus_id)
    if not manifest:
        _err("E_NOT_FOUND", f"语料不存在：{corpus_id}", "`corpus list` 查看已导入语料")
    pages = _load_pages(cdir)
    info = _select_page_offset(pages, None)
    if info["source"] == "default":
        return {"ok": True, "corpus_id": corpus_id, "page_offset": manifest.get("page_offset", 0),
                "offset_source": "default", "updated_pages": 0}
    offset = info["offset"]
    changed = 0
    for page in pages:
        if page.get("book_page") is None or info["source"] != "explicit":
            new_book = page["pdf_page"] - offset
            if page.get("book_page") != new_book:
                page["book_page"] = new_book
                changed += 1
            _write_json(os.path.join(cdir, "pages", _safe_page_file(page["pdf_page"])), page)
    manifest.update({"page_offset": offset, "offset_source": info["source"]})
    _write_json(os.path.join(cdir, "manifest.json"), manifest)
    build_index(corpus_id)
    return {"ok": True, "corpus_id": corpus_id, "page_offset": offset,
            "offset_source": info["source"], "updated_pages": changed}


# ---------------------------------------------------------------------------
# 索引（FTS5）
# ---------------------------------------------------------------------------
def _open_db(create: bool = True) -> sqlite3.Connection | None:
    path = _corpus_db_path()
    if not create and not os.path.isfile(path):
        return None
    if create:
        _ensure_dir(corpus_root())
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5("
            "body, corpus_id UNINDEXED, pdf_page UNINDEXED, book_page UNINDEXED)"
        )
    except sqlite3.OperationalError as exc:
        _err("E_NO_FTS5", f"当前 sqlite3 不支持 FTS5：{exc}",
             "Python 内置 sqlite3 通常已带 FTS5；或改用系统 python3（勿用精简编译版）")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS corpus_index ("
        "corpus_id TEXT PRIMARY KEY, pages INTEGER, indexed_at TEXT, sha256 TEXT)"
    )


def build_index(corpus_id) -> dict:
    """重建某语料的 FTS5 索引（先 ``DELETE FROM fts WHERE corpus_id=?``）。"""
    cdir = _corpus_dir(corpus_id)
    if not os.path.isfile(os.path.join(cdir, "manifest.json")):
        _err("E_NOT_FOUND", f"语料不存在：{corpus_id}", "`corpus list` 查看已导入语料")
    pages = _load_pages(cdir)
    if not pages:
        _err("E_NO_PAGES", f"语料 {corpus_id} 下没有 pages/*.json", "重新 import 或 `verify` 检查")
    conn = _open_db(create=True)
    try:
        _ensure_schema(conn)
        with conn:
            conn.execute("DELETE FROM fts WHERE corpus_id=?", (corpus_id,))
            rows = []
            for page in pages:
                body = _index_body(_page_plain_text(page))
                book_page = page.get("book_page")
                rows.append((body, corpus_id, int(page["pdf_page"]),
                             None if book_page is None else int(book_page)))
            conn.executemany("INSERT INTO fts(body, corpus_id, pdf_page, book_page) VALUES (?,?,?,?)", rows)
            manifest = _read_json(os.path.join(cdir, "manifest.json"))
            conn.execute(
                "INSERT OR REPLACE INTO corpus_index(corpus_id, pages, indexed_at, sha256) VALUES (?,?,?,?)",
                (corpus_id, len(rows), _now_iso(), manifest.get("sha256", "")),
            )
    finally:
        conn.close()
    return {"ok": True, "corpus_id": corpus_id, "indexed_pages": len(pages)}


def _index_ready(corpus_id) -> bool:
    """索引对该语料是否存在且与 manifest 的 sha256 一致。"""
    conn = _open_db(create=False)
    if conn is None:
        return False
    try:
        _ensure_schema(conn)
        row = conn.execute("SELECT sha256 FROM corpus_index WHERE corpus_id=?", (corpus_id,)).fetchone()
        if not row:
            return False
        manifest = get_corpus(corpus_id)
        return bool(manifest) and (row[0] or "") == (manifest.get("sha256") or "")
    except sqlite3.Error:
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------
def _target_corpora(corpus_id) -> list:
    if corpus_id is not None:
        cdir = _corpus_dir(corpus_id)
        if not os.path.isfile(os.path.join(cdir, "manifest.json")):
            _err("E_NOT_FOUND", f"语料不存在：{corpus_id}", "`corpus list` 查看已导入语料")
        return [corpus_id]
    return [m["corpus_id"] for m in list_corpora()]


def _page_haystack(page: dict) -> tuple:
    """``(原文, 归一化文本)``：归一化文本把各类空白与连字符断词一并抹掉，供子串定位。

    返回 ``(flat, compact, positions)`` 不可直接互换，故只暴露 ``compact`` 与
    ``原始字符 → compact 下标`` 的映射（见 ``_compact``）。
    """
    return _compact(_page_plain_text(page))


def _compact(text: str) -> tuple:
    """压缩文本：去掉空白；``"-"``/``"\\n"`` 造成的断词也一并粘合。

    返回 ``(compact, mapping)``，``mapping[i]`` = compact 第 i 个字符在原文中的下标，
    便于从 compact 命中位置回卷出带上下文的原始片段。
    """
    chars = []
    mapping = []
    for i, ch in enumerate(text or ""):
        if ch.isspace():
            continue
        chars.append(ch)
        mapping.append(i)
    return "".join(chars), mapping


def _locate(text: str, keyword: str):
    """在原文中定位关键词，容忍空白断开与 ASCII 大小写差异；返回 ``(start, end)`` 或 ``None``。

    策略：先直接找；再在"去空白 + 小写"的紧凑文本里找，最后用 mapping 回卷到原文下标。
    """
    if not keyword:
        return None
    idx = text.find(keyword)
    if idx >= 0:
        return idx, idx + len(keyword)
    compact, mapping = _compact(text)
    kw = "".join(ch for ch in keyword if not ch.isspace())
    if not kw or not compact:
        return None
    hay = compact.lower()
    needle = kw.lower()
    pos = hay.find(needle)
    if pos < 0 and len(needle) >= 3:
        # 连字符断词：``semiconserv-\native`` 紧凑化后仍带 ``-``，逐段匹配兜底
        needle_plain = needle.replace("-", "")
        hay_plain = hay.replace("-", "")
        p2 = hay_plain.find(needle_plain)
        if p2 < 0:
            return None
        pos = p2
    start = mapping[pos]
    end = mapping[min(len(mapping) - 1, pos + len(needle) - 1)] + 1
    return start, end


def _window(text: str, keyword: str, radius: int = SNIPPET_RADIUS) -> str:
    """从原文截取关键词前后各 ``radius`` 字（用于 snippet / quote）。

    找不到关键词时取文首 ``2*radius`` 字（末尾加省略号），保证片段始终可追溯。
    """
    flat = re.sub(r"[ \t]+", " ", (text or "").replace("\n", " ")).strip()
    if not flat:
        return ""
    loc = _locate(flat, keyword)
    if loc is None:
        return flat[: radius * 2] + ("…" if len(flat) > radius * 2 else "")
    start, end = loc
    s0 = max(0, start - radius)
    e0 = min(len(flat), end + radius)
    return ("…" if s0 > 0 else "") + flat[s0:e0] + ("…" if e0 < len(flat) else "")


def _like_scan(keyword: str, targets: list, limit: int) -> list:
    hits = []
    for cid in targets:
        for page in _load_pages(_corpus_dir(cid)):
            text = _page_plain_text(page)
            flat = re.sub(r"\s+", "", text)
            kw_flat = re.sub(r"\s+", "", keyword)
            if not kw_flat or kw_flat not in flat:
                continue
            occ = flat.count(kw_flat)
            hits.append({
                "corpus_id": cid,
                "pdf_page": page["pdf_page"],
                "book_page": page.get("book_page"),
                "score": round(-float(occ), 6),
                "snippet": _window(text, keyword),
                "low_quality": bool(page.get("low_quality")),
                "mode": "like",
            })
    hits.sort(key=lambda h: (-h["score"], h["corpus_id"], h["pdf_page"]))
    return hits[:limit]


def _registry(targets: list) -> dict:
    out = {}
    for cid in targets:
        man = get_corpus(cid)
        if man:
            out[cid] = man
    return out


def _fts_search(keyword: str, targets: list, limit: int) -> list:
    expr = _match_expr(keyword)
    if not expr or not targets:
        return []
    conn = _open_db(create=False)
    if conn is None:
        return []
    try:
        _ensure_schema(conn)
        rows = []
        for i in range(0, len(targets), MAX_PARAM - 1):
            chunk = targets[i:i + MAX_PARAM - 1]
            placeholders = ",".join("?" for _ in chunk)
            sql = (
                "SELECT corpus_id, pdf_page, book_page, bm25(fts, 1.0, 0.0, 0.0, 0.0) AS score, "
                "snippet(fts, 0, '[[', ']]', '…', 24) AS snip "
                f"FROM fts WHERE fts MATCH ? AND corpus_id IN ({placeholders}) "
                "ORDER BY score LIMIT ?"
            )
            try:
                rows.extend(conn.execute(sql, (expr, *chunk, limit)).fetchall())
            except sqlite3.OperationalError as exc:
                _err("E_BAD_QUERY", f"检索语法错误：{exc}", f"keyword={keyword!r} → {expr!r}")
    finally:
        conn.close()
    # FTS 的 snippet 是 token 流（已切碎），只用于排序定位；最终片段从原文重截
    order = {}
    for cid, pdf_page, book_page, score, snip in rows:
        key = (cid, pdf_page)
        order[key] = (score, snip)
    reg = _registry(targets)
    page_cache = {}
    for (cid, pdf_page) in order:
        page_cache[(cid, pdf_page)] = {
            p["pdf_page"]: p for p in _load_pages(_corpus_dir(cid))
        }.get(pdf_page)
    hits = []
    for (cid, pdf_page), (score, snip) in order.items():
        page = page_cache.get((cid, pdf_page))
        if page is None:
            continue
        text = _page_plain_text(page)
        snippet = _window(text, keyword)
        if snippet and not re.sub(r"\s", "", keyword) in re.sub(r"\s", "", snippet):
            snippet = _window(text, keyword, radius=80)
        hits.append({
            "corpus_id": cid,
            "pdf_page": pdf_page,
            "book_page": page.get("book_page"),
            "score": round(float(score), 6),
            "snippet": snippet,
            "low_quality": bool(page.get("low_quality")),
            "title": reg.get(cid, {}).get("title", ""),
            "kind": reg.get(cid, {}).get("kind", ""),
            "mode": "fts",
        })
    hits.sort(key=lambda h: (h["score"], h["corpus_id"], h["pdf_page"]))
    return hits[:limit]


def search(keyword: str, corpus_id: str | None = None, limit: int = 10) -> list:
    """全文检索，返回按 ``score`` 升序（FTS5 bm25，越小越相关）的命中列表。

    * ``len(keyword.strip()) <= 1``：bigram 索引对单字无效 → ``LIKE '%kw%'`` 扫 pages，
      ``score = -命中次数``（仍为负数、仍升序）。
    * 否则：``tokenize_cn`` 后每个 token 用双引号包裹、以 ``AND`` 连接做 MATCH。
    * 每条：``{"corpus_id","pdf_page","book_page","score","snippet", ...}``；
      ``snippet`` 从**原文**截取关键词前后各 40 字（FTS5 snippet() 输出的是切碎 token 流，
      复核价值低，故只借它排序）。
    * 索引缺失或与 manifest 的 sha256 不一致（例如导入后手工改过 pages）时自动
      ``build_index`` 自愈；重建失败则报错（不静默返回空结果，避免"查不到"被误读为"语料没有"）。
    """
    if not isinstance(keyword, str) or not keyword.strip():
        _err("E_BAD_ARGS", "keyword 不能为空")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        _err("E_BAD_ARGS", "limit 必须是正整数")
    kw = keyword.strip()
    targets = _target_corpora(corpus_id)
    if len(kw) <= 1:
        return _like_scan(kw, targets, limit)
    stale = [t for t in targets if not _index_ready(t)]
    for cid in stale:
        try:
            build_index(cid)  # 索引缺失/过期（sha 不符）时自愈重建
        except ShibanError as exc:
            if not corpus_id:
                continue
            _err(exc.code, f"索引不可用且无法重建：{exc.message}", exc.hint)
    hits = _fts_search(kw, targets, limit)
    if hits:
        return hits
    return _like_scan(kw, targets, limit)


def cite(hit: dict) -> str:
    """把一条检索命中渲染成可复核的引用串：``【书名·教材P.55 / PDF页64】原文…``。

    ``book_page`` 为空时**不编页码**，只给 PDF 页，并标注"教材页未知"。
    """
    man = get_corpus(hit.get("corpus_id")) or {}
    title = man.get("title") or hit.get("corpus_id", "")
    book = hit.get("book_page")
    pdf = hit.get("pdf_page")
    where = f"教材P.{book} / PDF页{pdf}" if book is not None else f"教材页未知(base=PDF) / PDF页{pdf}"
    flag = " ⚠低质量页" if hit.get("low_quality") else ""
    return f"【{title}·{where}{flag}】{(hit.get('snippet') or '').strip()}"


# ---------------------------------------------------------------------------
# 读页 / 校验 / 删除
# ---------------------------------------------------------------------------
def read_page(corpus_id, book_page: int | None = None, pdf_page: int | None = None, around: int = 0) -> dict:
    """按 ``book_page`` 或 ``pdf_page`` 读原文；``around>0`` 时附前后各 N 页摘要。"""
    cdir = _corpus_dir(corpus_id)
    manifest = get_corpus(corpus_id)
    if not manifest:
        _err("E_NOT_FOUND", f"语料不存在：{corpus_id}", "`corpus list` 查看已导入语料")
    if book_page is None and pdf_page is None:
        _err("E_BAD_ARGS", "必须给出 book_page 或 pdf_page", "例如 read_page('bx2', book_page=55)")
    if isinstance(around, bool) or not isinstance(around, int) or around < 0:
        _err("E_BAD_ARGS", "around 必须是 >=0 的整数")
    for name, val in (("book_page", book_page), ("pdf_page", pdf_page)):
        if val is not None and (isinstance(val, bool) or not isinstance(val, int)):
            _err("E_BAD_ARGS", f"{name} 必须是整数")
    pages = _load_pages(cdir)
    if not pages:
        _err("E_NO_PAGES", f"语料 {corpus_id} 无分页文件", "`verify` 或重新 import")
    by_pdf = {p["pdf_page"]: p for p in pages}
    by_book = {p["book_page"]: p for p in pages if p.get("book_page") is not None}
    target = None
    if book_page is not None:
        target = by_book.get(book_page)
        if target is None and pdf_page is None:
            hint = "该语料未记录教材页（book_page 为空或 page_offset 未知），改用 pdf_page"
            if by_book:
                near = min(by_book, key=lambda b: abs(b - book_page))
                hint += f"；最近的教材页为 {near}"
            _err("E_PAGE_NOT_FOUND", f"{corpus_id} 没有教材 P.{book_page}", hint)
    if target is None and pdf_page is not None:
        target = by_pdf.get(pdf_page)
        if target is None:
            _err("E_PAGE_NOT_FOUND", f"{corpus_id} 没有 PDF 第 {pdf_page} 页",
                 f"PDF 页范围 1..{max(by_pdf)}")
    result = {
        "ok": True,
        "corpus_id": corpus_id,
        "title": manifest.get("title", ""),
        "kind": manifest.get("kind", ""),
        "book_page": target.get("book_page"),
        "pdf_page": target["pdf_page"],
        "section": target.get("section", ""),
        "blocks": target.get("blocks") or [],
        "low_quality": bool(target.get("low_quality")),
        "quality": target.get("quality", {}),
    }
    if around > 0:
        anchor = target["pdf_page"]
        ctx = []
        for p in pages:
            if p["pdf_page"] != anchor and abs(p["pdf_page"] - anchor) <= around:
                ctx.append({
                    "pdf_page": p["pdf_page"],
                    "book_page": p.get("book_page"),
                    "section": p.get("section", ""),
                    "summary": _page_plain_text(p)[:120],
                })
        result["context"] = sorted(ctx, key=lambda x: x["pdf_page"])
        if pdf_page is None:
            result["raw_page_marker"] = f"<!-- page:pdf={target['pdf_page']} book={target.get('book_page')} -->"
    return result


def _dup_lines(pages: list, min_pages: int = 3, min_len: int = 8, ratio: float = 0.6) -> list:
    """跨页重复行检测（双向装订 / 双栏错行 / 插图说明页的典型症状）。"""
    seen = {}
    for page in pages:
        for line in set(_page_plain_text(page).split("\n")):
            s = line.strip()
            if len(s) < min_len:
                continue
            seen.setdefault(s, set()).add(page["pdf_page"])
    suspects = [(s, sorted(ps)) for s, ps in seen.items() if len(ps) >= min_pages]
    out = []
    for s, ps in suspects:
        if len(ps) / max(1, len(pages)) < ratio:
            out.append({"line": s[:60], "pdf_pages": ps[:10]})
    return out[:10]


def verify(corpus_id=None) -> dict:
    """校验：pages 文件数 == manifest.pages_total；source 存在则重算 sha256；索引是否过期。

    ``corpus_id=None`` 时校验全部语料（返回 ``{"ok", "corpora":[...]}``）。
    """
    if corpus_id is None:
        reports = [verify(m["corpus_id"]) for m in list_corpora()]
        return {"ok": all(r["ok"] for r in reports) and bool(reports), "corpora": reports}
    cdir = _corpus_dir(corpus_id)
    problems = []
    warnings = []
    manifest_path = os.path.join(cdir, "manifest.json")
    if not os.path.isfile(manifest_path):
        _err("E_NOT_FOUND", f"语料不存在：{corpus_id}")
    try:
        manifest = _read_json(manifest_path)
    except (OSError, ValueError) as exc:
        _err("E_BAD_MANIFEST", f"manifest.json 无法解析：{exc}", "重新 import 覆盖")
    files = _page_files(cdir)
    pages = _load_pages(cdir)
    total = manifest.get("pages_total")
    if not isinstance(total, int):
        problems.append("manifest.pages_total 缺失或非整数")
    elif len(files) != total:
        problems.append(f"page 文件数 {len(files)} != manifest.pages_total {total}")
    if len(pages) != len(files):
        problems.append(f"{len(files) - len(pages)} 个 page 文件解析失败")
    pdf_seen = [p.get("pdf_page") for p in pages]
    if len(set(pdf_seen)) != len(pdf_seen):
        problems.append("存在重复 pdf_page，可能多导或覆盖冲突")
    source_file = manifest.get("source_file") or ""
    src_path = os.path.join(cdir, source_file) if source_file else ""
    actual_sha = ""
    if src_path and os.path.isfile(src_path):
        actual_sha = _sha256_file(src_path)
        if manifest.get("sha256") and actual_sha != manifest.get("sha256"):
            problems.append(f"source 的 sha256 与 manifest 不一致（原件被改动）：{actual_sha[:12]}…")
    elif source_file:
        warnings.append(f"source 文件缺失（{source_file}），无法重算 sha256")
    if pages:
        first = min(pages, key=lambda p: p.get("pdf_page") or 0)
        last = max(pages, key=lambda p: p.get("pdf_page") or 0)
        if first.get("pdf_page") != 1:
            warnings.append(f"首页 pdf_page 为 {first.get('pdf_page')}（非 1），可能缺页")
    empty_pages = [p["pdf_page"] for p in pages if not _page_plain_text(p).strip()]
    if empty_pages:
        warnings.append(f"{len(empty_pages)} 页无文本：{empty_pages[:8]}")
    lq_manifest = set(manifest.get("low_quality_pages") or [])
    lq_actual = {p.get("book_page") if p.get("book_page") is not None else p.get("pdf_page")
                 for p in pages if p.get("low_quality")}
    if lq_manifest != lq_actual:
        warnings.append(f"low_quality_pages 与页面实际质量不一致（manifest={len(lq_manifest)}，"
                        f"实际={len(lq_actual)}），建议重新 import")
    if manifest.get("page_offset") and manifest.get("offset_source") in ("explicit", "inferred"):
        bad = [p["pdf_page"] for p in pages
               if p.get("book_page") is not None and p["book_page"] != p["pdf_page"] - manifest["page_offset"]]
        if bad:
            problems.append(f"{len(bad)} 页 book_page != pdf_page - page_offset，锚点错位")
    dups = _dup_lines(pages)
    if dups:
        warnings.append(f"检测到 {len(dups)} 条跨多页重复行（双栏错行 / 跨页页眉？）")
    if not _index_ready(corpus_id):
        warnings.append("FTS 索引缺失或与当前 manifest 不一致，请 build_index")
    return {
        "ok": not problems,
        "corpus_id": corpus_id,
        "problems": problems,
        "warnings": warnings,
        "pages_files": len(files),
        "pages_total": total,
        "sha256": actual_sha or manifest.get("sha256", ""),
        "dup_lines": dups,
    }


def remove(corpus_id, force: bool = False) -> dict:
    """删除语料目录与索引条目。``force=False`` 直接抛 ``E_CONFIRM_REQUIRED``。"""
    cdir = _corpus_dir(corpus_id)
    if not force:
        _err("E_CONFIRM_REQUIRED", f"删除语料 {corpus_id} 需要二次确认",
             f"再次调用 remove({corpus_id!r}, force=True)")
    existed = os.path.isdir(cdir)
    removed_index = 0
    conn = _open_db(create=False)
    if conn is not None:
        try:
            _ensure_schema(conn)
            with conn:
                cur = conn.execute("DELETE FROM fts WHERE corpus_id=?", (corpus_id,))
                removed_index = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                conn.execute("DELETE FROM corpus_index WHERE corpus_id=?", (corpus_id,))
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    if existed:
        if os.path.dirname(cdir) != os.path.realpath(corpus_root()):
            _err("E_BAD_ID", f"拒绝删除越界路径：{cdir}")
        shutil.rmtree(cdir)
    return {"ok": True, "corpus_id": corpus_id, "removed_dir": existed, "removed_index_rows": removed_index}


# ---------------------------------------------------------------------------
# 列表 / 查询
# ---------------------------------------------------------------------------
def list_corpora() -> list:
    """返回 corpus_root 下所有 manifest（按导入时间倒序；manifest 损坏的跳过并计数到 stderr）。"""
    root = corpus_root()
    if not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not os.path.isdir(path) or name.startswith("."):
            continue
        mpath = os.path.join(path, "manifest.json")
        if not os.path.isfile(mpath):
            continue
        try:
            man = _read_json(mpath)
        except (OSError, ValueError) as exc:
            print(f"[shiban_corpus] 跳过损坏的 manifest：{mpath}（{exc}）", file=sys.stderr)
            continue
        if isinstance(man, dict):
            man.setdefault("corpus_id", name)
            out.append(man)
    out.sort(key=lambda m: (m.get("imported_at") or "", m.get("corpus_id") or ""), reverse=True)
    return out


def get_corpus(corpus_id) -> dict | None:
    """读取单个 manifest；不存在返回 ``None``（corpus_id 非法则抛错）。"""
    cdir = _corpus_dir(corpus_id)
    path = os.path.join(cdir, "manifest.json")
    if not os.path.isfile(path):
        return None
    try:
        man = _read_json(path)
    except (OSError, ValueError) as exc:
        _err("E_BAD_MANIFEST", f"manifest.json 无法解析：{exc}", f"路径：{path}")
    if not isinstance(man, dict):
        _err("E_BAD_MANIFEST", f"manifest.json 不是对象：{path}")
    man.setdefault("corpus_id", corpus_id)
    return man


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------
_SELFTEST_MD = """<!-- page:1 -->
# 第3章 基因的本质

第1节 DNA是主要的遗传物质 【问题探讨】

细胞学说的建立过程说明：科学发现往往依赖技术进步。
沃森和克里克借助X射线衍射数据推断DNA是双螺旋结构。

| 实验 | 结论 |
| --- | --- |
| 格里菲斯 | 存在转化因子 |
| 艾弗里 | DNA是转化因子 |

图3-1 肺炎链球菌的转化实验 （示意图略）
<!-- page:2 -->
第2节 DNA的结构

DNA由两条脱氧核苷酸链构成，绝大多数原核生物的DNA是环状的。
半保留复制：复制时双链解开，各自作为模板。半保留复制保证了遗传信息的准确传递。

图3-2 DNA半保留复制过程
c = a ＝ b × 0.5 mol
DNA复制需要 template、primase 与 pH 7 的缓冲环境。
<!-- page:3 -->
第3节 DNA的复制

构想：1 DNA 2 PCR
"""


_PAGE_OFFSET = 1  # book_page = pdf_page - 1（正文 P.1 对应 PDF 第 2 页）


def _check(step: str, cond, fmt: str, actual) -> None:
    """断言 + 诊断：失败时打印**哪一步**、期望什么、实际值是什么。"""
    if not cond:
        raise AssertionError(f"步骤 {step} 失败：期望 {fmt}，实际 = {actual!r}")


def _selftest() -> int:
    step = "init"
    root = _shiban_root()
    print(f"[selftest] SHIBAN_ROOT={root}")
    tmp = tempfile.mkdtemp(prefix="shiban-corpus-selftest-")
    try:
        # 0) 切词规则（题目给定样例，逐字比对）
        step = "0/tokenize_cn"
        got = tokenize_cn("DNA半保留复制")
        _check(step, got == "dna 半保 保留 留复 复制", '"dna 半保 保留 留复 复制"', got)

        # 1) dry_run + import
        step = "1/dry_run"
        md_path = os.path.join(tmp, "bx2-test.md")
        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write(_SELFTEST_MD)
        meta = {
            "corpus_id": "bx2", "kind": "textbook",
            "title": "普通高中教科书·生物学必修2 遗传与进化",
            "publisher": "人民教育出版社", "edition": "2019", "subject": "生物", "volume": "必修2",
            "provenance": "selftest 合成数据（非真实教材）",
        }
        dry = import_file(md_path, meta, dry_run=True)
        _check(step, dry["dry_run"] and dry["pages_total"] == 3 and not os.path.isdir(_corpus_dir("bx2")),
               "dry_run=True 且不落盘、pages_total=3",
               {"dry_run": dry["dry_run"], "pages_total": dry["pages_total"],
                "dir_exists": os.path.isdir(_corpus_dir("bx2"))})

        step = "1/import"
        rep = import_file(md_path, meta, page_offset=_PAGE_OFFSET)
        print(f"[selftest] import: pages_total={rep['pages_total']} "
              f"low_quality={rep['low_quality_pages']} offset={rep['page_offset']}({rep['offset_source']})")
        _check(step, rep["pages_total"] == 3, "pages_total == 3", rep["pages_total"])
        _check("1/import/offset", rep["page_offset"] == _PAGE_OFFSET,
               f"page_offset == {_PAGE_OFFSET}", rep["page_offset"])
        _check("1/import/indexed", rep["indexed_pages"] == 3, "indexed_pages == 3", rep["indexed_pages"])
        _check("1/import/samples", len(rep["samples"]) == 3, "3 条 samples", rep["samples"])

        step = "1/idempotent"
        again = import_file(md_path, meta, page_offset=_PAGE_OFFSET)
        _check(step, again["pages_total"] == 3, "重复导入 pages_total == 3", again["pages_total"])

        step = "1/overwrite-guard"
        other = os.path.join(tmp, "other.md")
        with open(other, "w", encoding="utf-8") as fh:
            fh.write("<!-- page:1 -->\n别的内容\n")
        try:
            import_file(other, dict(meta))
            raise AssertionError("步骤 1/overwrite-guard 失败：同 id 不同文件应抛 E_CORPUS_EXISTS，实际未报错")
        except ShibanError as exc:
            _check(step, exc.code == "E_CORPUS_EXISTS", "E_CORPUS_EXISTS", exc.code)

        step = "1/path-traversal"
        for bad in ("../etc", "a/b", "..", ".hidden", "x\u0000y", ""):
            try:
                import_file(md_path, {"corpus_id": bad, "kind": "textbook", "title": "t"})
                raise AssertionError(f"步骤 {step} 失败：corpus_id={bad!r} 应被拒绝，实际通过")
            except ShibanError as exc:
                _check(f"{step}({bad!r})", exc.code == "E_BAD_ID", "E_BAD_ID", exc.code)

        step = "1/unsupported"
        bad_ext = os.path.join(tmp, "x.docx")
        with open(bad_ext, "w", encoding="utf-8") as fh:
            fh.write("x")
        try:
            import_file(bad_ext, {"corpus_id": "doc1", "kind": "textbook", "title": "t"})
            raise AssertionError("步骤 1/unsupported 失败：.docx 应抛 E_UNSUPPORTED，实际通过")
        except ShibanError as exc:
            _check(step, exc.code == "E_UNSUPPORTED", "E_UNSUPPORTED", exc.code)

        # 2) 分块启发式
        step = "2/read_page(pdf1)"
        p1 = read_page("bx2", pdf_page=1)
        types1 = [b["type"] for b in p1["blocks"]]
        print(f"[selftest] page1(pdf1/book{p1['book_page']}) types={types1}")
        _check(step + "/book_page", p1["book_page"] == 1 - _PAGE_OFFSET,
               f"book_page == 1 - {_PAGE_OFFSET}", p1["book_page"])
        _check(step + "/blocks", bool(types1) and types1[0] == "heading", "首个块是 heading", types1)
        _check(step + "/table", "table" in types1, "含 table", types1)
        _check(step + "/caption", bool(types1) and types1[-1] == "figure_caption", "末个块是 figure_caption", types1)

        step = "2/read_page(pdf2)"
        p2 = read_page("bx2", pdf_page=2)
        types2 = [b["type"] for b in p2["blocks"]]
        print(f"[selftest] page2(pdf2/book{p2['book_page']}) types={types2}")
        _check(step + "/book_page", p2["book_page"] == 2 - _PAGE_OFFSET,
               f"book_page == 2 - {_PAGE_OFFSET}", p2["book_page"])
        _check(step + "/caption+formula", "figure_caption" in types2 and "formula" in types2,
               "含 figure_caption 与 formula", types2)
        _check(step + "/section", p2["section"].startswith("第2节"), "section 以「第2节」开头", p2["section"])

        step = "2/read_page(pdf3, around=1)"
        p3 = read_page("bx2", pdf_page=3, around=1)
        _check(step, len(p3.get("context") or []) == 1, "context 有 1 页", p3.get("context"))

        # 3) 构建索引 + 检索
        step = "3/build_index"
        idx = build_index("bx2")
        _check(step, idx["indexed_pages"] == 3, "indexed_pages == 3", idx["indexed_pages"])

        step = "3/search(半保留)"
        hits = search("半保留")
        print(f"[selftest] search('半保留') -> {len(hits)} hit(s)")
        for h in hits:
            print("   ", h["score"], "pdf", h["pdf_page"], "book", h["book_page"], h["snippet"][:50])
        _check(step + "/hit", bool(hits) and hits[0]["pdf_page"] == 2, "首条命中 PDF 第 2 页",
               [(h["pdf_page"], h["book_page"]) for h in hits])
        _check(step + "/book_page", hits[0]["book_page"] == 2 - _PAGE_OFFSET,
               f"book_page == 2 - {_PAGE_OFFSET}", hits[0]["book_page"])
        _check(step + "/snippet", "半保留" in hits[0]["snippet"], "snippet 含关键词", hits[0]["snippet"])

        step = "3/search(limit)"
        limited = search("半保留", corpus_id="bx2", limit=1)
        _check(step, len(limited) == 1, "limit=1 → 1 条", len(limited))

        step = "3/search(单字 LIKE)"
        one = search("图")
        _check(step, bool(one) and one[0]["mode"] == "like", "单字走 LIKE", [(h["mode"], h["pdf_page"]) for h in one])

        step = "3/search(未命中)"
        miss = search("不存在的词xyz")
        _check(step, miss == [], "空列表", miss)

        step = "3/cite"
        quoted = cite(hits[0])
        print(f"[selftest] cite -> {quoted[:80]}…")
        _check(step, quoted.startswith("【") and f"教材P.{2 - _PAGE_OFFSET}" in quoted,
               f"以【开头且含 教材P.{2 - _PAGE_OFFSET}", quoted)

        # 4) verify
        step = "4/verify"
        v = verify("bx2")
        print(f"[selftest] verify ok={v['ok']} problems={v['problems']} warnings={len(v['warnings'])}")
        _check(step, v["ok"] and not v["problems"], "ok=True 且无 problems", v["problems"])

        # 5) 无页码标记的 md → 整篇 1 页，book_page=None（不编页码）
        step = "5/无页码标记"
        plain = os.path.join(tmp, "plain.md")
        with open(plain, "w", encoding="utf-8") as fh:
            fh.write("没有页码标记的一段文字，包含 细胞学说 二字，用于确认 book_page 为空。\n" * 3)
        rep2 = import_file(plain, {"corpus_id": "note-1", "kind": "personal", "title": "随手笔记"})
        _check(step + "/pages", rep2["pages_total"] == 1, "整篇 1 页", rep2["pages_total"])
        plain_page = read_page("note-1", pdf_page=1)
        _check(step + "/book_page", plain_page["book_page"] is None, "book_page is None", plain_page["book_page"])
        note_hits = search("细胞学说", corpus_id="note-1")
        _check(step + "/search", bool(note_hits) and note_hits[0]["book_page"] is None,
               "检索结果的 book_page 也为 None", note_hits[:1])

        # 6) 页眉页脚：跨页重复的才去，"第2节"这类一次性节标题保留
        step = "6/页眉页脚"
        hdr = os.path.join(tmp, "hdr.md")
        with open(hdr, "w", encoding="utf-8") as fh:
            fh.write(
                "普通高中教科书·生物学必修2\n"
                "# 第3章 基因的本质\n"
                "# 第1节 DNA是主要的遗传物质\n"
                "细胞学说的建立过程说明科学的发现依赖技术手段，这是本节最重要的内容。\n"
                "56\n"
                "<!-- page:57 -->\n"
                "普通高中教科书·生物学必修2\n"
                "# 第3章 基因的本质\n"
                "# 第2节 DNA的结构\n"
                "半保留复制是DNA复制的核心机制，它保证了遗传信息的准确传递。\n"
                "57\n"
                "<!-- page:58 -->\n"
                "普通高中教科书·生物学必修2\n"
                "# 第3章 基因的本质\n"
                "# 第3节 DNA的复制\n"
                "DNA复制需要模板、原料、能量和酶的参与，这是一个多步骤的酶促反应。\n"
                "58\n"
            )
        rh = import_file(hdr, {"corpus_id": "hdr-1", "kind": "textbook", "title": "页眉样张"})
        # 只用 `page:N` 标记时 pdf_page 取标记值（56→57→58），故按实际页号读取
        hdr_pages = _load_pages(_corpus_dir("hdr-1"))
        texts = [b["text"] for p in hdr_pages for b in p["blocks"]]
        joined = "\n".join(texts)
        _check(step + "/strip", "普通高中教科书·生物学必修2" not in joined, "页眉已去除", joined[:80])
        _check(step + "/keep", "第2节 DNA的结构" in joined, "一次性节标题保留", joined[:120])
        _check(step + "/offset", rh["page_offset"] == 0, "由页码推断 offset == 0", rh["page_offset"])

        # 7) 论文 meta 必填校验
        step = "7/论文必填"
        try:
            import_file(plain, {"corpus_id": "paper-1", "kind": "paper", "title": "某研究"})
            raise AssertionError("步骤 7 失败：论文缺 evidence_level/scope 应抛 E_BAD_META，实际通过")
        except ShibanError as exc:
            _check(step, exc.code == "E_BAD_META", "E_BAD_META", exc.code)

        # 8) remove 需二次确认
        step = "8/remove 未确认"
        try:
            remove("note-1")
            raise AssertionError("步骤 8 失败：未 force 应抛 E_CONFIRM_REQUIRED，实际通过")
        except ShibanError as exc:
            _check(step, exc.code == "E_CONFIRM_REQUIRED", "E_CONFIRM_REQUIRED", exc.code)
        step = "8/remove force"
        rm = remove("note-1", force=True)
        _check(step, rm["removed_dir"] and get_corpus("note-1") is None, "目录已删除且 get_corpus 返回 None",
               {"removed_dir": rm["removed_dir"], "get": get_corpus("note-1")})
        left = [h["corpus_id"] for h in search("细胞学说")]
        _check(step + "/index", "note-1" not in left, "索引中不再有 note-1", left)

        print("OK")
        return 0
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except ShibanError as exc:
        print(f"FAIL: 步骤 {step} 抛出 {exc.code}：{exc.message}（hint: {exc.hint}）", file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - 自检要把意外异常定位到步骤
        print(f"FAIL: 步骤 {step} 出现意外异常", file=sys.stderr)
        traceback.print_exc()
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(_selftest())
