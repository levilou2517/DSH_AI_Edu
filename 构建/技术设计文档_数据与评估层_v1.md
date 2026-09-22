# 师伴系统·技术设计文档（架构定稿 / 数据与评估层）

**版本：** v1.0（设计定稿，待实现）
**基线：** A 域 `v0.2.0` · B 域 `shiban-v0.2.0`
**性质：** 这是 R1–R5 的地基性架构文档。本版专注「持久数据层 + 长期记忆继承 + 教师/班级/学生纵深 + 低负载过程性评价 + 双源整合评估」。R2–R5 的接入点在本文档末尾给出。
**评审状态：** 待用户确认后进入实现。

---

## 0. 设计目标（用户确认的架构判定）

本系统的数据层要同时满足四个约束，缺一不可：

| # | 目标 | 含义 |
|---|---|---|
| T1 | **数据独立于 Agent** | Agent（预设）本身不挂载/不内嵌数据；数据独立持久化。 |
| T2 | **跨会话/跨工作区继承** | 任意会话、任意工作区都能读到完整的班级画像 + 教师偏好；新会话不丢记忆。 |
| T3 | **增量累积 + 纵向参考** | 新课堂数据追加到既有画像；支持多班、多届纵向沉淀，过去数据对未来有参考价值。 |
| T4 | **低负载过程性评价 + 双源整合** | AI 协助教师把「未经组织的原始回忆」升级为「有序反思」；评估报告 = AI 判断 ⊕ 教师判断（显式处理冲突）。 |

**核心哲学（贯穿全系统）：** 师伴永远是「协助者/支架」，而非「替代者/审核者」。AI 卸载的是教师的**认知组织负担**，不替代教师的价值判断。这与「副驾驶模式、决策权在教师」一致，并落到认知层面。

---

## 1. 总体架构：两域 + 一个宿主数据服务

### 1.1 数据与代码的职责分离

| 层 | 归属 | 内容 | 版本控制 | 会话/工作区范围 |
|---|---|---|---|---|
| **行为代码** | B 域预设 | `agent.cordis.yml`（persona/委派/行为规则） | `dsh-shiban-presets` | 全局（预设） |
| **技能资产** | A 域工作区 | `.dsh/skills/*.md` | `DSH_AI_Edu` | 随工作区 |
| **持久数据** | **宿主数据服务** | `~/.shiban/data/`（教师/班级/学生/课节/观测点/聚合库） | 不入 git；由服务管理 | **跨会话/跨工作区** |
| **运行时中间产物** | A 域工作区 | `data/shiban/current_*.json` 等 | 语义=共享内存 | 会话内 |

> **Agent 不碰数据文件本身**，只通过宿主数据服务读写。这是 T1/T2 的关键实现。

### 1.2 为什么必须宿主侧服务（沙箱事实）

实测当前 DSH 文件沙箱边界（workspace-write 策略）：

| 路径 | Agent 写权限 |
|---|---|
| 当前工作区 `DSH_AI_Edu` | ✅ |
| `/tmp` | ✅ |
| `~`、`~/Documents/WorkSpace`（工作区外） | ❌ |

因此 **`~/.shiban/data/` 不能用 Agent 直接写**。三条备选：

| 路线 | 是否满足 T2（跨会话） | 是否满足隔离 | 成本 | 结论 |
|---|---|---|---|---|
| A. 宿主侧数据服务 | ✅ 彻底 | ✅ | 高 | **采用** |
| B. 软链纳入工作区 | ⚠️ 依赖软链每次就位 | ⚠️ | 中 | 否 |
| C. 会话同步 | ⚠️ 靠纪律 | ⚠️ | 中 | 否 |

### 1.3 宿主数据服务的形态（cordis 实现草图）

宿主侧注册一个动态 Cordis Plugin，通过 `harness` 暴露一个**模型可调用的动态 Tool**（RPC 方式），内部执行 `~/.shiban/data/` 的读写。Agent 无需文件权限，只调用服务方法。

```js
// code.host —— 宿主侧数据服务（实现要点，非最终码）
return {
  apply(ctx) {
    const harness = ctx.get('harness')
    if (harness === undefined) return
    harness.tool('shiban.store', {
      title: '师伴持久数据读写',
      schema: {
        type: 'object',
        properties: {
          op: { enum: ['read', 'write', 'query', 'append'], type: 'string' },
          collection: { type: 'string' },   // teacher/class/student/lesson/observation/reference
          key: { type: 'string' },
          payload: { type: 'object' },
          query: { type: 'object' },
        },
        required: ['op'],
      },
      async execute(args, context) {
        // 1) 校验路径（防目录穿越，仅允许 ~/.shiban/data/**)
        // 2) 分 collection 走对应 handler：
        //    - teacher: 教师档案/偏好/成长轨迹
        //    - class: 班级容器 + 班内时间轴
        //    - student: 班内学生个体
        //    - lesson: 课节记录
        //    - observation: 过程性观测点
        //    - reference: 跨班聚合借鉴库（只读）
        // 3) 返回最小 JSON（不回传内部对象）
      },
    })
  },
}
```

> 实现前需按 cordis 技能要求，用 `cordis_inspect_list` / `Builtin.listBuiltins` 核对 `harness` 的真实签名与 Tool 注册 schema，再 `cordis_define` + `cordis_run`。本文档给出设计意图。

---

## 2. 数据模型（主体 + 时间纵深）

### 2.1 主体模型

```
教师 ★核心主体·在进步
 ├── professional_timeline   # 教龄、支架执行熟练度、采纳反馈的改进
 ├── preferences             # 跨班跟随教师（去选项化/结论先行…）
 └── taught_classes          # 带过的所有班级（跨班参照基准=他自己的历史）

班级（独立容器，有自身时间轴）
 ├── timeline                # 成立 → 各课节 → …
 ├── students                # 班内学生个体纵深
 └── 跨届同类班级可做【聚合】借鉴，不借原始个体数据

学生（班内纵深）
 ├── timeline                # 多次观测点 → 发展评估证据
 └── 跨班/跨届不强制关联（个体只在本班有意义）

知识/支架（教学内容维度：知识点 × 支架类型 × 认知层次 = 聚集线索）
```

### 2.2 存储组织（目录结构，`~/.shiban/`）

```
~/.shiban/
├── schema/                      # 建表/建结构语句（入 git A 域？否——随宿主代码）
├── data/                        # 运行时 .db / .json（不入 git，由服务管理）
│   ├── teacher/
│   │   └── <teacher_id>.json    # 教师档案 + 偏好 + 专业成长时间线
│   ├── classes/
│   │   ├── <class_id>.json      # 班级元数据
│   │   ├── <class_id>/
│   │   │   ├── students.json    # 班内学生列表 / 个体档案索引
│   │   │   ├── lessons/         # 班内时间轴：每课一节
│   │   │   │   └── <date>_<topic>/
│   │   │   │       └── lesson.json   # 该课指标/支架/通过率/评价
│   │   │   └── observations/    # 过程性观测点（学生→时间→信号）
│   ├── reference.db             # 【跨班聚合借鉴】只读索引（知识点×支架×层次×效果）
│   └── meta.db                  # 资源管理（teacher/class/student id 分配、版本）
├── migrations/                  # schema 演进脚本
└── bin/                         # CLI / 服务脚本
```

> **采纳策略**：结构化指标与可查聚合用 SQLite（`meta.db` + `reference.db`）；原始对话/快照/个体开放字段用 JSON 文件。二者互补，不做极端单一化。

### 2.3 关键表结构（SQLite：`meta.db` + `reference.db`）

**meta.db（资源 + 结构）**

```sql
-- 主体注册
CREATE TABLE teachers (
  teacher_id  TEXT PRIMARY KEY,
  name        TEXT,
  profile     TEXT,            -- JSON：偏好 + 专业成长时间线
  created_at  TEXT
);
CREATE TABLE classes (
  class_id    TEXT PRIMARY KEY,
  teacher_id  TEXT REFERENCES teachers,
  level       TEXT,            -- 高一/高二/高三
  cohort      TEXT,            -- 届（2026）
  subject     TEXT,
  class_family TEXT,           -- 同类班聚合键（如"高二(3)班"）
  created_at  TEXT
);
CREATE TABLE students (
  student_id  TEXT PRIMARY KEY,
  class_id    TEXT REFERENCES classes,
  name        TEXT,
  profile     TEXT,            -- JSON：个体画像（时间纵深）
  external_ref TEXT            -- 学号，跨班不强制关联
);
CREATE TABLE lessons (
  lesson_id   TEXT PRIMARY KEY,
  class_id    TEXT REFERENCES classes,
  date        TEXT,
  topic       TEXT,
  knowledge_point TEXT,
  scaffold_type TEXT,
  cognitive_level TEXT,
  pass_rate   REAL,
  lesson_meta TEXT             -- JSON：current_*.json 产物、对话引用
);
```

**reference.db（跨班聚合借鉴，只读）**

```sql
CREATE TABLE scaffold_effectiveness_agg (
  id INTEGER PRIMARY KEY,
  class_family TEXT,           -- "高二(3)班"
  scaffold_type TEXT,          -- 类比/逻辑推导/…
  knowledge_point TEXT,        -- DNA复制
  cognitive_level TEXT,        -- 记忆/理解/应用/分析
  n INTEGER,
  avg_pass_rate REAL,
  -- 可追溯：分解到具体 lesson_id 已去标识（不暴露学生个体）
  source_distinct_lessons INTEGER
);
```

> **隔离原则**：`students` 内部纵深可读；跨班/跨届查询**只走 `reference.db` 的聚合**，不外泄个体原始数据。

---

## 3. 读写接口（宿主数据服务方法集）

| 方法(op) | 用途 | 输入要点 | 更新规则 |
|---|---|---|---|
| `read` | 任意主体/课/观测点读取 | collection + key | — |
| `write` | 落盘中间产物 / 教师偏好 / 班级画像 | collection + key + payload | 幂等覆盖 |
| `append` | 追加课节、观测点、时间线事件 | collection + (class_id, lesson_id) + payload | 只增不删 |
| `query` | 跨班聚合 / 纵向 SQL | collection=reference + query（知识点/支架/层次/届区间） | 只读 |

**跨会话验证路径（T2 验收）**
1. 会话 A 用 `append` 写入一条观测点
2. 新开会话 B，用 `read/query` 读到同一条 → 证明继承
3. 切到不同 DSH 工作区，再 `read` 仍可及 → 证明跨工作区

---

## 4. 低负载过程性评价（认知脚手架）

**目标：** 让教师把「散乱、未组织的原始回忆」变成「有序、可用的反思」，**降低而非增加认知负载**。

### 4.1 循环流程（顺带，不新增独立环节）

```
每课/随堂测后（顺带进课后对话，复用 R4 通道）
  → AI 按「班 × 时间 × 指标」给有序反思支架:
      提示本阶段有变化/存疑的学生 + 已调取的证据(次数/层次/支架)
  → 教师顺着支架,低负担补真实观察
      AI 记录为【教师侧观点】，与【AI 数据版】对质，显式标冲突/校准
  → append 为该生"过程观测点"(observation)，沿时间轴累积
  → 多次观测 → 可输出"发展评估综合报告"
```

### 4.2 低负载退出机制（用户确认方案 c）

| 教师状态 | AI 行为 |
|---|---|
| 常规 | 顺支架引导，低负担补观察 |
| 表示"不想现在反思/累了" | **立即收尾**，已采集保存 |
| AI 判断该生/该课确为关键 | 给一个"下次可补"的**轻量待办**，不强制 |

### 4.3 观测点 JSON schema（observation）

```json
{
  "observation_id": "obs_2026-09-02_x",
  "class_id": "CLS_2026_3",
  "student_id": "STU_083",
  "recorded_at": "2026-09-02T15:10:00Z",
  "dimension": {
    "knowledge_point": "DNA复制",
    "scaffold_type": "类比",
    "cognitive_level": "理解"
  },
  "evidence": {
    "ai_data": { "pass_rate": 0.71, "trend": "down", "notes": "推演层下滑" },
    "teacher_said": { "source": "teacher_said", "confidence": "0.9", "text": "后半节状态上来，最后题会做，只是前面走神" }
  },
  "alignment": "conflict",          // agreed / conflict / partial
  "conflict_detail": "AI判停滞 vs 教师判状态波动",
  "integrated": "该生概念识别达标，推演表现受课堂状态干扰，非能力缺口"
}
```

---

## 5. 双源整合评估报告（deliverable schema）

```json
{
  "report_id": "eval_2026-09-02_CLS2026_3_STU083",
  "student_id": "STU_083",
  "period": { "from": "2026-09-01", "to": "2026-12-31" },
  "timeline_evidence": [ "多观测点浓缩：识别→推演→综合 的层次迁移" ],
  "ai_view": { "assessment": "…", "confidence": "…", "data_basis": "…" },
  "teacher_view": { "assessment": "…", "basis": "课堂观察，模型记录不到" },
  "alignment": {
    "status": "conflict",
    "points": [ { "dimension": "推演能力", "ai": "停滞", "teacher": "状态波动", "resolution": "以两轮连续测数据加后续课观察定夺" } ]
  },
  "integrated": "…综合 AI 数据 + 教师观察的判断…",
  "recommendation": "下一步教学建议（支架或补强）",
  "audience_note": "本报告面向教师本人（内部洞察）；如需交付外部，须去掉冲突展示并标注责任边界"
}
```

---

## 6. 测试数据与真实数据分离（前评估确认：当前 data/shiban 全为测试/示例）

| 区 | 位置 | 性质 |
|---|---|---|
| 示例/测试区 | A 域 `data/shiban/`（保留现有 class_profile.db、current_*.json、last_eval.json、examples） | 演示/schema 参照/里程碑，**不入真实持久层** |
| 真实持久层 | `~/.shiban/data/`（宿主服务管理） | **从空开始**，首次真实课堂才写入 |

**迁移**：现有数据全部留在示例区；`scripts/init_db.py`（4 条模拟画像）与 `build_profile_db.py`（示例 6 表）作为**结构/schema 参照源码保留**，但真实持久层用新的 `meta.db`/`reference.db` 结构，互不混淆。

---

## 7. 版本控制与回退

| 对象 | 版本控制 |
|---|---|
| 设计文档（本文件） | A 域 git（`构建/`） |
| 宿主数据服务代码 | 作为 cordis 动态插件，归宿主；源码进 A 域 `scripts/` 或独立 `services/` 目录维护 + 版本管理 |
| `~/.shiban/data/` | **不入 git**；用 schema 演进脚本（`migrations/`）+ 定期备份管理（决策 R1.5） |
| 数据回退 | 代码回退=git；数据回退=迁移脚本逆向 / 备份恢复，与代码解耦 |

---

## 8. 与 R2–R5 的接入点

| 需求 | 本设计如何承载 |
|---|---|
| R1 数据独立化 | 本文档 §1–§3（宿主数据服务 + `~/.shiban/data/` + meta/reference 库） |
| R2 教材知识库 | 新开 `~/.shiban/knowledge/` + `textbook.db`(FTS5)，作为 reference 库的补充维度 |
| R3 教案组件化 | class→lesson 容器承接 plan_snapshot；`reference.db` 提供支架×知识点历史效果作为教学决策证据 |
| R4 对话式获取 | §4 过程性评价复用 R4 课后对话通道；`observation` 承接课堂记录/对话 |
| R5 HTML 素材 | `reference.db` 之外的 `templates/` 与 lessons 关联 |

---

## 9. 风险与待定

| 风险 | 说明 | 应对 |
|---|---|---|
| 宿主服务需真实注册/授权 | cordis 动态 Tool 需 `cordis_define` + `cordis_run`，可能涉及审批 | 实现前核对 harness 签名，按要求走审批 |
| `~/.shiban/data` 目录创建 | 服务首次写需建目录；宿主权限可建，Agent 不可 | 宿主服务内部 `mkdir` |
| 隔离 vs 借鉴平衡 | 学生原始数据 vs 跨班聚合 | 强制只走 `reference.db` 聚合查询，个体数据不外泄 |
| 教师判断采集负担 | 真实课堂教师不一定有话说 | 低负载退出机制(c) + 重点学生优先 |

**评审待确认项：**
1. §2.3 表结构与 §2.2 目录组织是否认同？
2. §3 接口方法与 §7 版本策略是否认同？
3. 是否需要先实现「宿主数据服务最小可跑原型」验证 T2（跨会话继承）后再铺全部，还是直接全量？