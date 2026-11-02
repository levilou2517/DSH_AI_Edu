---
name: class-profile
description: 学情分析原子——回答"这个班怎么样/上次这个支架管用吗"，输出"支架类型 × 通过率"矩阵与画像摘要，或把一次课堂/测验结果落库。**可独立调用且可只查不更**：无数据时如实声明"画像库未建立"并给建库选项，绝不编造学生数据；记录不足 3 次时不给趋势结论。
whenToUse: 任何"这个班水平如何/掌握得怎么样/上次那个讲法效果如何/我要不要换支架/查查学情"的意图。备课前的学情诊断、课堂后的落库、单元的横向比较均可。
---

# 学情画像：先把"有多少证据"说清楚，再说结论

学情结论的杀伤力来自于它会被当成事实使用——所以你的第一句话永远是**数据够不够**，第二句才是**数据说了什么**。
你的核心动作是**先数样本、再谈结论**：几次记录、多少学生、覆盖哪些知识点。

## 一、工作方式

### 0. 两种模式，先认

| 模式 | 教师的话 | 你要做的 | 禁止 |
|---|---|---|---|
| **只查** | "这班怎么样""上次那个讲法效果如何" | 读 `graph` + 历史 `ev` → 出矩阵 + 摘要 | 顺手改库、编数据 |
| **更新** | "今天这节课的测验结果记一下""把这次落库" | 从一次课堂/测验抽出结构化字段 → 落库 | 无原始记录时替教师估通过率 |

可查后再更、可只更不查。教师没说要落库，就**不要落库**。

### 1. 提问规则（这是最省话的原子）

本原子**多数情况下不该问问题**——数据在库里，读就是了。只在两种情形开口，**一次最多 2 题**：

1. **分不清问的是哪个班/哪一段**：`ctx pack` 不带 `--scope` 时，"你说的'这个班'是 c1 还是 c2？"
2. **要落库但缺关键字段**：缺 `pass_rate` 或 `scaffold_type` 时，问"这次 Q3 全班对了几个人？"——**要分子分母，不要"通过率大概多少"**。

问法示例：
- ✅"这次是 42 人的班，Q3 答对 27 人，对吗？通过率按 27/42 记。"
- ✅"这节课重点用的是'方向性流程图'，归到可视化，还是归到逻辑推导？"
- ❌"你觉得学生掌握得好吗？"——这是自评，不是数据；要了也只能进 `teacher_note`。

教师不愿给数字时说"你就按感觉写吧"：**不落库**，改出对话摘要并在回执 `degrade` 写"教师仅提供主观印象，未落库"。

### 2. 只查模式的动作

```bash
shiban-store graph                                   # 全局：{nodes, edges, by_kind, by_status}
shiban-store artifact list --kind ev --scope c1      # 本班历史评价
shiban-store artifact list --kind mev --scope c1     # 微格内省（无学生，不进通过率）
shiban-store artifact get --id <ev-id> --view digest # 先看结构，再决定是否取某节
```

1. **先数证据**：`ev` 几条、`mev` 几条、跨越的日期范围。
2. **`mev` 只做语气补充**：微格内省**没有学生数据**，不许参与通过率计算，只可在摘要里注明"另有 N 次微格，不含学情数据"。
3. **取数只取需要的节**：`--view section --name <节>`，例如 `--name scaffold_attribution`。
4. 出矩阵 + 摘要（见 §二）。

### 3. 更新模式的动作

从**一次**课堂/测验抽出字段，逐条对照必填清单，缺的填 `null` 并写明原因——**不要估算**。

| 字段 | 含义 | 校验 |
|---|---|---|
| `class_id` | 班级标识 | 非空 |
| `session_date` | 课堂日期 | `YYYY-MM-DD` |
| `knowledge_point` | 知识点 | 非空 |
| `scaffold_type` | 支架类型：类比 / 逻辑推导 / 可视化 / 实验演示 / 流程图 | 枚举（超出则问教师归类） |
| `cognitive_level` | 记忆 / 理解 / 应用 / 分析 | 枚举 |
| `pass_rate` | 通过率 | `0–1` 小数；必须有分子分母 |
| `sample` | `{n, correct}` | 缺分母则 `null` + 原因 |
| `session_duration_min` | 该支架实际讲解分钟数 | 数值 |
| `teacher_note` | 课后摘要（**教师原话**） | — |

**派生化原则**：学情数据由 `ev` / `mev` 产物派生，画像由 `graph` 聚合——**本原子不直接写数据库、不创建表**。
落库 = 把结构化字段写进对应 `ev` 的 payload 或摘要字段，由 CLI 统一记账。

## 二、产出契约

数据通路唯一：**一律经 `shiban-store` CLI**，不直接读写 `$SHIBAN_ROOT` 下文件，不碰 sqlite 文件。产物 id / 版本 / 状态由 CLI 生成。

### 只查：对话摘要（默认不落盘）

先给教师一段话，再给矩阵。**顺序不能反**——先给结论会让矩阵变成装饰。

```
c1｜2026-09-10 至 2026-11-02｜共 5 次课堂评价，覆盖 4 个知识点
证据强度：5 次 ≥ 3 次门槛，可做趋势判断
可视化支架 3 次，平均通过率 0.71（52–88 人）；类比支架 2 次，0.58 → 换支架前先看这里
注意：这 5 次里只有 2 次有完整分母，其余 3 次按点名结果估算，已标注
```

### 矩阵字段（对话里给，需要留档时才 put）

```jsonc
{
  "scope": "c1",
  "period": {"from": "2026-09-10", "to": "2026-11-02"},
  "evidence_count": {"ev": 5, "mev": 2, "note": "mev 不含学生数据，未参与计算"},
  "matrix": [
    {"class_id": "c1", "scaffold_type": "可视化", "knowledge_point": "DNA复制",
     "sessions": 3, "avg_pass_rate": 0.71, "min": 0.52, "max": 0.88,
     "avg_duration_min": 9.3, "basis": "Q1/Q3 作答，分母完整"}
  ],
  "summary": {"kp_covered": ["DNA复制","转录"], "avg_pass_rate": 0.66,
              "scaffold_preference": "可视化占 60%",
              "cognitive_level_spread": {"记忆": 2, "理解": 1, "应用": 2, "分析": 0}},
  "insufficiency": ["类比支架仅 2 次，不足 3 次，不给上下结论"],
  "no_data_policy": null
}
```

### 需要留档时

```bash
shiban-store artifact put --kind pref --envelope '{
  "subject_line": {"scope":"c1","topic":"学情画像","date":"2026-11-02"},
  "producer": {"atom":"class-profile","skills_loaded":["class-profile"]},
  "refs": [{"role":"source","id":"ev-c1-…"}, {"role":"source","id":"ev-c1-…"}],
  "payload": {
    "title": "c1 班学情画像 2026-11",
    "preferences": [{"rule":"优先级推荐时以可视化为首选支架","reason":"3 次记录平均通过率 0.71，高于类比 0.58"}],
    "matrix": [ …§二矩阵字段… ],
    "evidence_basis": ["ev-c1-…","ev-c1-…"]
  }
}'
```

`--kind pref` 的 `preferences[]` 会被后续 `ctx pack` 自动带给 `lesson-plan` / `quiz`——所以每条偏好**必须挂 `evidence_basis`**，否则会变成无源头的教条。

### 三条硬规则

- **库未建立 → 如实说**：`graph` 返回 `nodes: 0` 或本班 `ev` 为空时，输出"**c1 班画像库未建立**"，然后给三条路：
  1. 从这堂课开始建（完整闭环）；
  2. 用教师手上已有的记录补录（需要纸质/Excel 数据）；
  3. 先搁置，本次按无画像处理。
  **不许给示例数字，不许填默认值。**
- **< 3 次不说趋势**：`sessions < 3` 的支架类型，照常列均值，但摘要里写"不足以下趋势判断"，并在 `insufficiency[]` 记录。均值本身也要带 `sessions` 和样本 `n`，否则教师会当成稳定结论。
- **`pass_rate` 必须有分母**：只有"感觉对了七八成"的，记 `pass_rate: null` + `sample: null` + 原因；在矩阵里显示为 `—`，不参与 `avg_pass_rate` 计算。

## 三、先查后建

```bash
shiban-store ctx pack --for class-profile --scope c1 --kw <知识点>
```

| 包内字段 | 用途 |
|---|---|
| `preferences` | 已确认偏好，输出措辞要遵守 |
| `carry_over` | 上次遗留的待办/未采纳建议，摘要里可提一句"上次留的 X 还没做" |
| `degrade` | 语料缺失时，知识点名称不得伪造教材章节号 |

`graph` 是**聚合层**，给的是 `{nodes, edges, by_kind, by_status}` 计数——它不直接给通过率。通过率要从 `ev` payload 里取，两者要交叉核对（`by_kind.ev` 的数量必须与 `artifact list --kind ev` 条数一致，不一致说明索引未重建，在 `degrade` 里声明）。

## 四、与其它原子的关系

- **上游**：`class-eval` 的 `ev` 是唯一学情事实源；`quiz` 提供分母。
- **下游**：`lesson-plan` 拿它做支架优先级推荐；`teacher-growth` 拿它做时间线上的背景，但**成长趋势以 `ev`/`mev` 本身为准，不用画像均值**（均值会掩盖单次波动）。
- **边界**：本技能**不产出**教学建议，只说"哪类支架在哪个知识点上、通过率是多少"。要不要换支架是 `lesson-plan` 与教师的事。

## 五、返回给指挥的内容

```json
{"task_id":"<原样带回>","atom":"class-profile","status":"ok",
 "skills_loaded":["class-profile"],
 "artifacts":[],
 "mode":"query",
 "asked":["'这个班'指 c1 还是 c2？"],
 "teacher_decisions":[{"question":"指哪个班","answer":"c1","at":"2026-11-02"}],
 "matrix_summary":{"evidence_count":{"ev":5,"mev":2},"rows":4,"avg_pass_rate":0.66,
                   "below_threshold":["类比(2次)"]},
 "data_status":"ok|profile_not_built|insufficient(<3)",
 "degrade":["3 次 ev 无完整分母，矩阵中显示为 —"],
 "needs_teacher":[
   {"id":"q1","question":"要不要把这次结果落库？","options":["落库","只出不落"],
    "why":"落库会改变后续 lesson-plan 的优先级推荐"}],
 "next_suggest":[{"atom":"lesson-plan","why":"已有支架×通过率，可做优先级推荐"}],
 "one_liner":"c1 共 5 次评价，可视化 0.71 > 类比 0.58；类比样本不足 3 次"}
```

`asked` 与 `teacher_decisions` 是**必填**。本原子可以**如实为空**——但为空时必须在回执里写明 `asked: []` 的原因（"数据齐全，无需提问"），而不是悄悄省掉字段。
只查模式下 `artifacts` 为空数组是**正常且推荐**的；只有教师明确要留档才 `put`。
