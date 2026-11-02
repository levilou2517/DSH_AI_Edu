# 导入自己的语料

师伴不附带任何教材。你导入什么，它才能引用什么。

## 一本教材 PDF

```bash
shiban-store corpus import --file 生物学必修2.pdf \
  --meta '{"corpus_id":"bx2","kind":"textbook",
           "title":"普通高中教科书·生物学必修2 遗传与进化",
           "publisher":"人民教育出版社","edition":"2019",
           "subject":"生物","volume":"必修2"}' \
  --page-offset 9
```

`--page-offset` 是 **PDF 页码 − 教材印刷页码**。例如封面版权目录共 9 页，正文 P.1 在 PDF 第 10 页，则 offset = 9。
不确定时先 `--dry-run` 看抽出的页首，再确认真实偏移。

依赖 `pdftotext`（poppler-utils）。没有的话改用已转换的 Markdown：

```bash
shiban-store corpus import --file 必修2.md \
  --meta '{"corpus_id":"bx2","kind":"textbook","title":"必修2"}'
```

md 里用 `<!-- page:12 -->` 标记页边界，没有标记则整篇算一页、页码记 `null`。

## 课标与论文

```bash
# 课标
shiban-store corpus import --file 课程标准.pdf \
  --meta '{"corpus_id":"std-bio-2017","kind":"standard","title":"普通高中生物学课程标准（2017版）"}'

# 论文：必须写证据等级与适用范围
shiban-store corpus import --file 半保留复制教学研究.pdf \
  --meta '{"corpus_id":"paper-halfreserve-2019","kind":"paper",
           "title":"…","authors":["…"],"year":2019,"doi":"10.xxxx",
           "evidence_level":"quasi","scope":"高二3个班 N=142",
           "caveat":"样本为城市重点校"}'
```

论文的 `evidence_level` 取值：`rct` / `quasi` / `small-n` / `review` / `opinion`。
教案引用小样本论文时，渲染会带 `※` 提示——不要把一条小样本研究当成普遍结论。

## 检索

```bash
shiban-store corpus search --kw 半保留            # 全库
shiban-store corpus search --kw DNA --corpus bx2  # 限定一本
shiban-store corpus read --corpus bx2 --p 55      # 按教材页码读整页
shiban-store corpus verify --corpus bx2           # 校验完整性
```

中文检索用 **bigram 切分**（两字一组），因此"半保留""复制""骨架"这类两字词都能命中。
单字查询退回子串匹配。

## 导入后会发生什么

- `ctx pack` 会开始把命中的页片段带进教案/出题的上下文；
- 教案的 `citations` 可以写 `corpus_id + book_page + quote`，`validate` 会检查能否复现；
- **删除语料不会删除已有教案的引用记录**，只会让它们在下一次校验时提示"引用源已移除"。
