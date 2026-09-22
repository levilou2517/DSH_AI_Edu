#!/usr/bin/env python3
"""把生物学教材/课标 PDF 转成 AI 友好的 Markdown。

用法: python3 pdf2md.py <material_dir> <output_dir>

策略:
- PyMuPDF 文本块按 (阅读顺序) 重排: 先按 y 排序并做栏检测(左右双栏), 页眉/页脚剔除
- 章节标题 (第X章/第X节/一、二、...) 提升为 Markdown 标题, 正文合并为段落
- 特色栏目 (探究·实践/生物科技进展/...) 以引用块标注
- 图片/表格位置插入 [图] 占位符 (保留文字层信息, 图内标注丢失)
"""
import os
import re
import sys
import fitz

# ---------- 常量 ----------
FRONT_END_RE = re.compile(r'^(目\s*录|前\s*言|绪\s*论|后\s*记)$')

# 正文起始信号: 第1章/第1 章/第1节 等
BODY_START_RE = re.compile(r'^第\s*1\s*[章节]')

CH_RE = re.compile(r'^第\s*([0-9一二三四五六七八九十]+)\s*章\s*(.*)$')
SEC_RE = re.compile(r'^第\s*([0-9一二三四五六七八九十]+)\s*节\s*(.*)$')
# 课标式大节: "一、课程性质与基本理念" (仅当无第X章结构时使用)
TOPSEC_RE = re.compile(r'^([一二三四五六七八九十]{1,3})\s*、\s*(.{2,28})$')
SUBSEC_RE = re.compile(r'^（([一二三四五六七八九十]{1,3})）\s*(.{2,28})$')
APPENDIX_RE = re.compile(r'^附录\s*(\d+)?\s*(.*)$')
SUB2_RE = re.compile(r'^[1-9]\.\s+(.{2,24})$')

LABELS = [
    '探究·实践', '探究・实践', '生物科技进展', '生物科学史话',
    '科学·技术·社会', '科学・技术·社会', '与生物学有关的职业',
    '科学家的故事', '科学家访谈', '拓展视野', '科技探索之路',
]
LABEL_RE = re.compile(r'^(%s)\s*(?:[·・]\s*(.+))?$' % '|'.join(LABELS))

# 图注: "图3-9 半保留复制（左）和全保留复制（右）示意图" / "图A 富兰克林..." / "表3-1 ..."
CAPTION_RE = re.compile(r'^(图|表|图版|照片)\s*[0-9A-Za-z０-９]+[A-Za-z-]*\s*.{0,40}$')

BOX_HEADER_RE = re.compile(r'^(讨论|思考与讨论|旁栏思考题|批判性思维|实践|制作|实验|思考|练习|小结|概念检测|资料分析|资料卡片|本节聚焦|思考·\s*讨论|问题探讨|练习与应用|相关信息|背景知识|科学方法|复习与提高|理解概念|思维训练)$')

CN = {'0': '0', '一': '1', '二': '2', '三': '3', '四': '4', '五': '5',
      '六': '6', '七': '7', '八': '8', '九': '9', '十': '10',
      '十一': '11', '十二': '12', '十三': '13', '十四': '14', '十五': '15'}

def norm_num(s):
    s = s.strip()
    if s.isdigit():
        return int(s)
    return int(CN.get(s, 0)) or 0

def norm_text(t):
    """压缩空白; 去掉行尾换行。"""
    t = t.replace('\u3000', ' ')
    t = re.sub(r'[ \t]+', ' ', t)
    lines = [l.strip() for l in t.split('\n')]
    out = []
    for l in lines:
        if l:
            out.append(l)
    return ' '.join(out).strip()

# ---------- 页面解析 ----------
def get_page_items(page):
    """返回页面内容项列表 [(kind, text, y, x)], kind ∈ {'text','imgcap'}
    已按阅读顺序(双栏感知)排好, 页眉页脚已剔除。
    图注(图X-X …)单独成项 imgcap, 标记原文此处有图片/插图。"""
    page_w = page.rect.width
    blocks = page.get_text('blocks')
    items = []
    for x0, y0, x1, y1, text, bno, btype in blocks:
        t = norm_text(text)
        if not t:
            continue
        # 页眉 (顶部, 短) / 页脚 (底部, 短: 页码或 页码+节名)
        if y0 < 40 and len(t) < 60:
            continue
        if y0 > 760 and len(t) < 40:
            continue
        if btype == 1:  # image 块: 不输出(图片不进 md), 位置由图注标记
            continue
        if CAPTION_RE.match(t):
            items.append(('imgcap', t, y0, x0))
        else:
            items.append(('text', t, y0, x0))

    # 双栏检测: 看 text 块的 x0 分布
    xs = [it[3] for it in items if it[0] == 'text']
    two_col = False
    if xs:
        mid = page_w / 2
        left = [x for x in xs if x < mid - 20]
        right = [x for x in xs if x > mid + 20]
        # 两栏都有显著内容
        if left and right and min(len(left), len(right)) >= max(2, len(xs) // 4):
            two_col = True

    def key(it):
        if two_col:
            col = 0 if it[3] < page_w / 2 else 1
            return (col, it[2], it[3])
        return (0, it[2], it[3])

    items.sort(key=key)
    # 去重(有些 PDF 文本块重复)
    seen = set()
    dedup = []
    for it in items:
        k = (it[0], it[1], round(it[2]), round(it[3]))
        if k in seen:
            continue
        seen.add(k)
        dedup.append(it)
    return dedup

def merge_paragraphs(items, struct='chapter'):
    """把文本项合并为段落/标题。返回 [(kind, text)], kind ∈
    {'para','h1','h2','h3','label','img'}"""
    out = []
    buf = []

    def flush():
        if buf:
            out.append(('para', ''.join(buf)))
            buf.clear()

    for it in items:
        kind, text, y, x = it
        if kind == 'imgcap':
            flush()
            out.append(('imgcap', text))
            continue
        m_ch = CH_RE.match(text)
        m_sec = SEC_RE.match(text)
        m_lab = LABEL_RE.match(text)
        if m_ch and len(text) < 30:
            flush()
            out.append(('h1', text))
        elif m_sec:
            flush()
            out.append(('h2', text))
        elif m_lab:
            flush()
            out.append(('label', text))
        elif struct == 'topsec' and TOPSEC_RE.match(text) and '...' not in text and len(text) < 32:
            flush()
            out.append(('h1', text))
        elif struct == 'topsec' and SUBSEC_RE.match(text) and len(text) < 32:
            flush()
            out.append(('h2', text))
        elif len(text) < 34 and BOX_HEADER_RE.match(text):
            flush()
            out.append(('h3', text))
        else:
            buf.append(text)
    flush()
    return out

# ---------- 文档级处理 ----------
def convert_pdf(src, dst, book_title):
    doc = fitz.open(src)
    n = len(doc)

    # 先全文扫一遍, 判断结构类型: 'chapter' (第X章) 或 'topsec' (一、二、...)
    has_chapter = False
    topsec_hits = 0
    for pno in range(n):
        for b in doc[pno].get_text('blocks'):
            t = norm_text(b[4])
            if CH_RE.match(t) and len(t) < 30:
                has_chapter = True
                break
            if TOPSEC_RE.match(t) and len(t) < 32 and b[1] > 40:
                topsec_hits += 1
        if has_chapter:
            break
    struct = 'chapter' if has_chapter else ('topsec' if topsec_hits >= 3 else 'chapter')

    # 定位正文起点
    if struct == 'chapter':
        body_start = n
        for pno in range(n):
            for it in get_page_items(doc[pno]):
                if it[0] == 'text' and BODY_START_RE.match(it[1]) and len(it[1]) < 30:
                    body_start = pno
                    break
            if body_start != n:
                break
    else:
        # topsec 结构: 从第二页起找 "一、" 大节标题。
        # 正文起点处的标志: 页面 y<120 存在页码 "1"(印刷页码, 即正文第1页)。
        body_start = n
        for pno in range(1, n):
            items = get_page_items(doc[pno])
            if not items:
                continue
            has_pageno1 = any(it[0] == 'text' and it[1] == '1' and it[2] > 600 for it in items)
            has_topsec = any(it[0] == 'text' and TOPSEC_RE.match(it[1]) and '...' not in it[1]
                             and len(it[1]) < 32 and it[2] < 220 for it in items)
            if has_pageno1 and has_topsec:
                body_start = pno
                break
        if body_start == n:
            body_start = 1

    # 正文结束: 封底(绿色印刷产品)
    end = n
    last_items = get_page_items(doc[n-1])
    if any(it[0]=='text' and '绿色印刷' in it[1] for it in last_items):
        end = n - 1

    # 逐页提取
    chapters = []   # [{'title':..., 'items': [(pno, [items])]}]
    current = None
    for pno in range(body_start, end):
        items = get_page_items(doc[pno])
        if not items:
            continue
        # 附录: 作为独立块
        for i, it in enumerate(items):
            if it[0] == 'text' and APPENDIX_RE.match(it[1]) and len(it[1]) < 40:
                title = norm_text(it[1])
                current = {'title': title, 'items': []}
                chapters.append(current)
                items = items[:i] + items[i + 1:]
                break
        if struct == 'chapter':
            for i, it in enumerate(items):
                if it[0] == 'text':
                    m = CH_RE.match(it[1])
                    # 章标题块: 短, 且位于页面上部(章首页的大标题)
                    if m and len(it[1]) < 30 and it[2] < 160:
                        title = norm_text(it[1])
                        current = {'title': title, 'items': []}
                        chapters.append(current)
                        items = items[:i] + items[i + 1:]
                        break
            if current is None:
                current = {'title': '正文（未分章部分）', 'items': []}
                chapters.append(current)
            current['items'].append((pno, items))
        else:
            if current is None:
                current = {'title': '正文', 'items': []}
                chapters.append(current)
            current['items'].append((pno, items))

    # 生成 markdown
    md = []

    def add(t=''):
        md.append(t)

    add(f'# {book_title}')
    add()
    add(f'> 来源: `{os.path.basename(src)}` · 共 {n} 页 · 正文自 PDF 第 {body_start+1} 页起')
    add('> 说明: 由 pdf2md.py 自动转换。`[图]` 表示原文此处为图片/插图(含图表), 文字层无法提取;')
    add('> 特色栏目以 `### ◈` 引用块保留, 表格内容以文字块顺序近似还原。')
    add()

    for ch in chapters:
        if struct == 'chapter':
            add(f'## {ch["title"]}')
            add()
        merged = []
        for pno, items in ch['items']:
            merged.extend(merge_paragraphs(items, struct))
        # 输出
        last = None
        for kind, text in merged:
            if kind == 'para':
                text = text.strip()
                if not text:
                    continue
                add(text)
                add()
            elif kind == 'h1':
                add(f'### {text}')
                add()
            elif kind == 'h2':
                add(f'#### {text}')
                add()
            elif kind == 'h3':
                add(f'**【{text}】**')
                add()
            elif kind == 'label':
                add(f'### ◈ {text}')
                add()
            elif kind == 'imgcap':
                add(f'> 📷 *[图: {text}]*')
                add()
                last = 'imgcap'
            else:
                add(text)
                add()
            if kind != 'img':
                last = kind
        add()

    os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
    with open(dst, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))
    doc.close()
    return dst, len(chapters)


def main():
    material = sys.argv[1]
    outdir = sys.argv[2]
    os.makedirs(outdir, exist_ok=True)

    books = []
    for fn in sorted(os.listdir(material)):
        if fn.endswith('.pdf') and not fn.startswith('.'):
            books.append((fn, os.path.join(material, fn)))
    texbooks = os.path.join(material, '教材')
    if os.path.isdir(texbooks):
        for fn in sorted(os.listdir(texbooks)):
            if fn.endswith('.pdf'):
                books.append((('教材/' + fn), os.path.join(texbooks, fn)))

    for rel, path in books:
        stem = os.path.splitext(os.path.basename(rel))[0]
        # 短名
        short = stem.replace('普通高中教科书·生物学', '').replace('普通高中', '')
        out = os.path.join(outdir, short + '.md')
        print(f'converting: {rel} -> {os.path.basename(out)}')
        dst, nch = convert_pdf(path, out, stem)
        size = os.path.getsize(dst)
        print(f'   chapters={nch} size={size/1024:.0f} KB')

if __name__ == '__main__':
    main()
