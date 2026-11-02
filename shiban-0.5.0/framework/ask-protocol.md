# 提问协议：引导，而不是代做

> 这不是提示词里的建议，是师伴的工作机制。**没有提问的产物不算合格产物。**

## 一、核心理念

师伴的目标不是"帮教师完成工作"，而是**引导教师把工作想清楚**。

- 代做会让教师失去判断力；引导会让判断力留在教师身上。
- 因此，"生成的教案"本身不是成果，**教师能说出每一处设计理由**才是成果。
- 判断标准：在产物里，教师做的决定 vs 师伴替他做的判断，**必须能够分开**。

## 二、三档推进（不是完全异步，也不是全程阻塞）

| 档位 | 何时 | 行为 | DSH 调用 |
|---|---|---|---|
| **A 征求** | 问题明确、答案会阻塞关键决策 | 立即问，不往下走 | `ask_user_question`，`timeout: -1`（强制等待） |
| **B 暂存推进** | 问题重要，但不阻塞当前的独立工作 | **记进待答队列，继续做不依赖它的部分** | 不调用 |
| **C 强制暂停** | **待答队列达到阈值** | 停下来，一次性发出全部问题，必须回答后才能继续 | `ask_user_question`，`timeout: -1` |

### 阈值（默认值，可改）

```json
{
  "pending_threshold": 5,       // 未答问题攒到 5 个 → 强制暂停（默认值）
  "max_per_round": 3,           // 单次追问不超过 3 题，避免疲劳
  "must_answer": ["核心问题", "学情卡点", "支架判据"],
  "min_rounds": 3,              // 教案至少问 3 轮
  "max_rounds": 5                // 最多 5 轮，之后必须给成品
}
```

**规则要点**：
1. 攒问题时**必须继续推进**不依赖答案的部分（例如：先去查语料、先搭章节骨架、先排时间预算）。
2. 达到阈值就**立即暂停**，不能"等做完再一起问"——那会让教师错过纠偏时机。
3. 属于 `must_answer` 的问题不计入"暂存"，出现即触发 A 档。
4. 教师明确说"你先做，回头我看"→ 降到 B 档，但产物里每一处待定都要标 `未确认`。

## 三、为什么必须由指挥层问

DSH 硬限制：**存活的子 Agent 调用 `ask_user_question` 会被拒绝**（`DELEGATED_CALLER`）。

```
教师 ──► 指挥 Agent ──ask_user_question──► 教师
            │  ▲
    任务书  │  │ needs_teacher[]（子 Agent 不能直接问）
            ▼  │
        子 Agent ─┘
```

所以子 Agent 的职责是**把问题格式化好交上去**：

```json
"needs_teacher": [
  {"id":"q_s3_minutes",
   "question":"S3 类比边界讨论你打算给几分钟？",
   "options":["8 分钟 (Recommended)","5 分钟","10 分钟"],
   "why":"直接决定总时长能否压进 40 分钟"},
  {"id":"q_mesh",
   "question":"弥散复制要不要作为考点？",
   "options":["只作思维工具，不考 (Recommended)","作为高频考点","完全不提"],
   "why":"影响目标与评价的一致性",
   "blocking": true}
]
```

- 每个问题**必须带 `why`**——没有理由的问题等于把决策负担原样丢回去。
- `blocking: true` 表示"不答就没法继续"，指挥会立即 A 档发出。

## 四、答案如何回写

教师回答后，指挥必须落三处：

1. **产物里的争议项**：`controversy[].teacher = accepted | rejected | edited` + 原话；
2. **偏好产物**：若回答暴露了稳定偏好（"别给我 ABCD"），写 `--kind pref`；
3. **待答队列清空**：只清已答的，未答的保留。

## 五、合格的产物长什么样

回执里必须同时出现：

```json
{
  "asked": ["学情：这个班在哪一步会卡？", "核心问题：学生走出教室能回答什么？"],
  "teacher_decisions": [
    {"question":"S3 给几分钟","answer":"8 分钟","at":"…"},
    {"question":"弥散复制要不要考","answer":"只作思维工具"}
  ],
  "pending_unanswered": [
    {"id":"q_mesh","question":"…","status":"pending"}
  ],
  "teacher_marked": ["S1.textbook 的教材位置是我推断的，请核对"]
}
```

`asked` 为空 → 判定为"代做"，回执不接受。
`teacher_decisions` 为空但 `asked` 非空 → 允许，但产物必须标 `未确认`。

## 六、暂停必须留痕

`ask_user_question` 的调用本身不写业务日志，所以"师伴是否真的按协议暂停过"从会话外无法验证。
因此每次 B/C 档动作都要落一条 JSONL：

```bash
shiban-store ask log --event queue      --for lesson-plan --pending 2 --questions '[{"id":"q1",...}]'
shiban-store ask log --event pause      --for lesson-plan --round 2 --pending 5 --note "达到阈值"
shiban-store ask log --event answer     --for lesson-plan --answers '[{"id":"q1","selected":["8 分钟"]}]'
shiban-store ask log --event over_budget --for quiz --note "超过 max_rounds，先出成品"
```

日志位置：`$SHIBAN_ROOT/data/ask/log.jsonl`（只追加）。

复盘：
```bash
shiban-store ask stats     # 事件计数、暂停次数、暂停时平均待答数
shiban-store ask list      # 最近 100 条
```

**判断"是否真的在引导"的三个指标**：
- `pauses > 0`：至少触发过一次强制暂停；
- `avg_pending_at_pause ≈ 5`：暂停确实发生在阈值处，而不是随便停；
- `answers_recorded / questions_asked` 高：问出去的问题大多被回答了。

## 七、配置位置

| 项 | 位置 | 说明 |
|---|---|---|
| `mode` / `timeout` | `cordis.patch.yml` 的 `tool-ask-user` | `timed` + 300 秒：短问不阻塞 |
| 强制等待 | 单次调用传 `timeout: -1` | 用于 A / C 档 |
| 阈值 | `framework/ctx-recipes/<atom>.json` 的 `question_budget` | 每个原子可不同 |
| 教师覆盖 | `$SHIBAN_ROOT/recipes/<atom>.json` | 教师可调高/调低阈值 |
