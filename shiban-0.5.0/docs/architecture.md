# 架构：一条写入通路，四个读视图

## 原则

1. **Agent 产生意图与内容，CLI 产生身份、位置、状态与引用。**
2. **只有一个写入口**：`shiban-store artifact put`。Agent 不直接写 `$SHIBAN_ROOT` 下的文件。
3. **读的是"包"，不是"文件"**：`ctx pack` 返回恰好够用的输入，字段名就是契约字段名。
4. **状态由程序推进**：`in_progress → confirmed → archived`，Agent 不能自封完成。
5. **降级必须显式**：每份产物带 `degrade[]`，说清缺什么、影响哪一部分。

## 数据流

```
教师 ──► 指挥 Agent ──ask_user_question──► 教师
              │  ①任务书（含输入 id）
              ▼
        ②ctx pack ──读 corpus / profile / carry_over──► 上下文包（≤8 KB）
              │
              ▼
        ③子 Agent 生成 payload
              │  ④artifact put（校验 / 生成 id / 原子写 / 图事务）
              ▼
        $SHIBAN_ROOT/data/artifacts/<kind>/<id>.json  +  graph.db
              │  ⑤结构化回执
              ▼
        ⑥指挥只读 index 视图（<2 KB）──► 呈现给教师
```

## 目录

```
$SHIBAN_ROOT/
  data/
    artifacts/<kind>/<id>.json   产物真源（人可读、可 diff）
    graph.db                     引用图 + 状态 + 历史
    evidence/                    原始证据（只追加）
    indexes/<kind>.jsonl         程序生成的轻量索引
    assets/<asset_id>/           素材（main.html + meta.json）
  corpus/<corpus_id>/            语料（manifest + pages/ + source）
  recipes/                       可选的配方覆盖
```

## 产物信封

所有产物共享一个包头（见 `contracts/artifact.schema.json`）：
`id / kind / rev / status / subject_line / refs / citations / degrade / controversy / payload`。
`payload` 是各原子自己的正文；其余字段语义跨原子一致。

## 两级视图

`artifact get --view`：

| 视图 | 体积 | 用途 |
|---|---|---|
| `index` | <2 KB | 列表、指挥决策 |
| `digest` | <2 KB | 看结构与标量摘要 |
| `section` | 按需 | 单章节（`--name S8` 或 `S8[2]`） |
| `full` | 20–60 KB | 只在需要通读时 |

## 提问为什么在指挥层

DSH 规定：**存活的子 Agent 不能调用 `ask_user_question`**（返回 `DELEGATED_CALLER`）。
所以子 Agent 把问题交回（回执的 `needs_teacher[]`），由指挥统一发出。
这也让提问能够被汇总、去重、按轮次控制——见 `framework/ctx-recipes/*.json` 的 `question_budget`。
