# 师伴 v0.5.0 构建计划（在 `DSH_AI_Edu/V0.5.0/` 内独立成库）

> 状态：待确认 · 日期：2026-10-29（**rev.2：并入「书院杯」教案模板与成品交付链**） · 基于 v0.4.3 实读（`6c871d2`）与本机 DSH `0.2.0-rc.2` 实测。
> 原则：**原始材料只读**——`材料/`、`md/`、`.dsh/skills/`、`services/`、`bin/`、`data/`、`~/Documents/WorkSpace/2026-10书院杯/` 全程不改；v0.5.0 是它们的「精炼副本 + 改造」。所有运行数据只写 `~/.shiban/`（或 `SHIBAN_ROOT`）。
>
> **rev.2 变更摘要**：新增 §1.1 教案生产链（F6–F9 实测）；新增 **P1.5 教案模板与交付链**（★ 本次重点）；P4 扩为「教案写什么 + 成品长什么样」两端；N 系列新增 N1–N5；专项决定集中在 §12。

---

## 0. 决定方案的实测事实（F1–F5 基础架构；F6–F10 见 §1.1）

| # | 事实 | 证据 | 影响 |
|---|---|---|---|
| F1 | 本沙箱**写不了 `~/.dsh/`**，`dsh --dump-config` 因写 `cordis.yml` 报 `EACCES` | 复现命令见 §10 | 安装在**临时 DSH_HOME 副本**里验证，不碰你正在用的 web profile |
| F2 | `skill-filesystem` 有一条 `!!js` 配置，其 **`baseUrl` 指向 agent-preset 包目录**，用来挂载随包技能 | `/tmp/profcheck-*/dump.yml` 第 1246–1252 行 | 插件包自带技能**可行、有官方先例**，不必写到用户 `~/.dsh/skills` |
| F3 | `plugin_manager.installBundle` 支持**本地绝对路径**安装 | `dsh-plugin-manager/README.zh.md` §inspect | 分发单元 = 一个包目录（或 `.tgz`），可直接 `dsh plugin add` |
| F4 | `pdftotext -layout` 约 **1.2 s/册**，**`\f` 分页正确** | 必修1 第 11 页 = `第1节 细胞是生命活动的基本单位`（教材 P.2 = PDF 11），折射出 `page_offset = 9` | 教材可随时重转；**PDF 永不进 git**；不需要 PyMuPDF 作为硬依赖 |
| F5 | 技能契约与 store 实现**路径矛盾**：技能写工作区 `data/shiban/*.json`、`class_profile.db`；store 只用用户级 `~/.shiban/data/` | `.dsh/skills/*.md` vs `services/shiban_store.py:30-35` | 「跨工作区继承」在契约层是**假的**。v0.5.0 必须统一到 `SHIBAN_ROOT` |

补充（构建期已知）：SQLite **FTS5 可用**，但 `unicode61` 对中文是割裂的（「细胞学说」匹配不到「细胞学说的建立过程」），必须用 `trigram` 或退回 `LIKE`。

### 1.1 教案生产链的实测事实（来自 `~/Documents/WorkSpace/2026-10书院杯/`）

| # | 事实 | 证据 | 影响 |
|---|---|---|---|
| F6 | 新模板是**十一章节的有序结构**：〇基本信息 / 一 课标及教材分析 / 二 学情（三稿）/ 三 重难点（1、2）/ 四 教学目标 / 五 教学方法 / 六 教学准备 / 七 设计思路 / 八 教学过程（四列表）/ 九 教学评价（形成性 + 终结性）/ 十 板书 / 十一 创新点 | `模板/高中生物理论课教学设计模板.md`（266 行），来源标注为第十二届田家炳杯参赛作品 | 这是「**一份教案 = 一个文档**」的结构，与 v0.4.3 的 `candidates[].scaffolds[]` **是两套数据模型**，必须做**单一映射** |
| F7 | 成品**相对模板有作者自发增量**：三 → 新增「难点成因分析 / 突破策略」两个 H3；九 → 形成性评价里新增「课堂即时检测（随堂 3 题）」表（题号/题目/参考答案/学生易错预估与应对）；十 → 板书用 Mermaid 假说树 + 预期—结果对照表 | `DNA半保留复制教学设计.md`（283 行 = `_V16`）与模板的 H2/H3 逐条比对 | 增量不是「新章节」而是**既有章节内的可选项**；模板必须显式给这两处「槽位」，否则 Agent 每次都重新发明 |
| F8 | 交付链已跑通，且是**软依赖**：`md2html_prince.py`（纯标准库）+ Prince（`/usr/bin/prince`）+ `prince-print.css`（A4/页眉/页脚/跨页表头/列宽类）→ 15 页 PDF；Mermaid 走 `mmdc`，**缺失时降级为红色占位**而不中断 | `README.md`、`package.json`、`md2html_prince.py:98-103` | 可直接内化成 store 的 `lesson render`，HTML→PDF 不引入新 npm 依赖 |
| F9 | 成品前还有**封皮**：`教案封皮.pdf`（姓名/授课科目/授课题目，1 页），合并后总计 16 页；`prince-print.css` 的页眉**硬编码**了书名 | `pdftotext 楼恩琦生科DNA的复制.pdf`、`prince-print.css:12` | 封皮字段与页眉字段都要参数化；合并步骤 `pdfunite` 可脚本化 |
| F10 | 版本演进 6 订（`_V01→_V06→_V16`）：V01–V05 严格按模板十一节；**V06 起改为比赛体例**（去掉〇基本信息，开篇改为标题块 + 三列表）；V06→V16 增补了「难点成因分析/突破策略」与「即时检测」 | 两版 H2 比对 | 「模板版」与「比赛版」是**同一内容的两种呈现**——正好支持 `--style template|competition` 双输出 |

---

## 1. 目标与验收标准

**目标**：交付一个可 `dsh plugin add` 的**师伴 v0.5.0 空壳**——装完即有人格 + 6 原子技能 + 数据层；语料 / 素材 / 证据全空，靠导入与使用逐步丰满。

| # | 验收项 | 判据 |
|---|---|---|
| A1 | 空工作区可加载技能 | 在无 `.git`、无 `.dsh/` 的 `/tmp/ws` 里，`skill` 能加载全部 6 个原子 |
| A2 | CLI 零工作区依赖 | 同一空工作区里 `shiban-store init / asset list / raw list` 正常 |
| A3 | 空库诚实 | 首装后 `corpus list = []`、`asset list = []`、`raw list = []` |
| A4 | 语料导入 | `corpus import` 一本 PDF 后 `corpus list` 有 manifest；`corpus read --p 2` 命中「细胞学说」 |
| A5 | 引用可核查 | `corpus search` 结果必带 `corpus_id` + `教材P` + `PDF页` |
| A6 | 无语料降级 | 未导入时 lesson-plan / quiz 契约要求 `meta.notes` 声明「无语料依据」，不得编页码 |
| A7 | 插件可装 | 临时 DSH_HOME 副本里 `dsh plugin add <本地路径>` 成功，`--dump-config` 含 `preset-shiban` |
| A8 | 零个人数据 | 安装包内 grep 不到 `teacher_profile` / `raw/` / 真实师生内容 |
| A9 | 版本可追溯 | `package.json.version ==` git tag `shiban-v0.5.0`；`shiban-store version` 同值且由 `verify.sh` 断言 |

### 1.2 教案生产链验收（N 系列，rev.2 新增）

| # | 验收项 | 判据 |
|---|---|---|
| **N1** | 模板可复现 | 用同一 `lesson.json` 分别渲染 `--style template` 与 `--style competition`，`template` 版 H2 序列与 §1.1 F6 逐条一致（脚本断言） |
| **N2** | 成品可交付 | `lesson render` 产出 `.md` + `.html` + `.pdf`（有 Prince 时）；PDF 页数 > 0、含页眉与页码；无 Prince 时**显式报告**「未生成 PDF」而非静默跳过 |
| **N3** | 合同完整 | `lesson validate` 对缺章节 / 教学目标不足 3 条 / 环节时长和 ≠ 课时 / 评价未对应目标 四类问题给出**可定位的行号**或字段名 |
| **N4** | 争议点显式 | `lesson.json` 中所有 `⚠` 争议条目在渲染产物里带可见标记（如角标 `※`），且 `lesson validate --strict` 时计入 warning 数 |
| **N5** | 引用可回指 | 教案内任一 `citation` 能被 `corpus read --corpus <id> --p <book_page>` 复现原文（抽样 3 处） |

---

## 1.3 教案产物格式：主稿选型（★ 决策项）

**背景**：现有成品是 Markdown。新机器上「装完即用」的判据是：**不装任何额外东西也能重建可交付 PDF**。实测本机 `prince` / `google-chrome` / `chromium` 都在，但它们**不是 DSH 自带**。

三种可选：

| 方案 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| **① HTML 主稿（推荐）** | `lesson.json` → 单文件 HTML（内联 `print.css`，`@media print` 定义 A4/页眉/页码）→ `lesson render --pdf` 用 Chrome/Chromium `--headless --print-to-pdf`；无浏览器则只出 HTML | **零依赖**；浏览器里直接打开即所见即所得；打印/PDF 走系统自带能力 | 页眉页码依赖浏览器打印引擎，和 Prince 版式有细微差异（需校准一次） |
| ② HTML→Prince | 沿用现有 `prince-print.css` | 版式与现有成品一致 | Prince 是商业软件，**不可作为默认依赖**；只能作为「有则用」的增强 |
| ③ Markdown 主稿 | 沿用 `.md` | 可读、可 diff、与现有产物一致 | 中文字体、跨页表头、Mermaid 都要额外工具；**Markdown 本身不是交付格式** |

**推荐**：**① 为主，② 为增强，③ 保留导出**。即：

```
lesson.json  ──(store)──►  lesson.html (自包含，浏览器可开)
                              ├─ --pdf + 有 chrome/chromium → lesson.pdf
                              ├─ --pdf + 有 prince           → lesson.pdf（版式增强）
                              └─ 二者皆无                    → 明确报「仅生成 HTML」
lesson.json  ──(store)──►  lesson.md   （可 diff / 可继续人工编辑的中间稿）
```

这样：**装完即用的下限是 HTML**（任何机器都有浏览器），**上限是 PDF**（有打印引擎就用）。Mermaid 一律**不在运行时渲染**——设计思路/板书改用 store 内置的纯 CSS/ASCII 框图（`framework/` 提供 3–4 个版式），既零依赖，又避免 `mmdc` 需要 Chrome 的二次依赖。

---

## 1.4 中学到 v0.5.0 的落点

| 现有资产 | 去向 | 说明 |
|---|---|---|
| `模板/高中生物理论课教学设计模板.md` | `framework/lesson-template/` **随包**（A 类） | 是「怎么写」而非「写什么」，进插件；**文件名带版本** `template-v1.md` |
| `../2026-10书院杯/教学设计/DNA半保留复制/DNA半保留复制教学设计.md` | `framework/fixtures/dna-replication/lesson.json` **示例固件**（A 类，脱敏可用） | 作为**参考实现与回归基准**；不含任何学生/教师个人数据，可作为公开示例 |
| `md2html_prince.py` + `prince-print.css` | 重写为 `vendor/services/shiban_lesson.py` + `framework/print/lesson.css` | 去掉硬编码书名与 `《DNA的复制》`；保留已验证的排版规则（`table-layout: fixed`、`thead` 跨页、中文字族分流） |
| `素材/教材/*.md` | 留给教师的**导入样例**（B 类），**不进包** | 体量 47 MB+，版权敏感 |
| `素材/标准/*.md`（师范生职业能力标准、教资大纲等） | `framework/standards/` **随包**（A 类） | 是**评价准则**（「什么样的教案算合格」），与教材无关；去掉 `.doc` 自动转换的噪音头 |
| `素材/范例/教学设计范例.pdf` | `framework/fixtures/` 的**参考示例**（可先不打包，只在文档中引用其来源） | 第三人作品，打包需确认授权 |

---

## 2. 目录结构（`V0.5.0/` 是**独立 git 仓库**）

```
V0.5.0/
├── BUILD_PLAN.md             # 本文件
├── VERSIONING.md             # 五条铁律（§4）
├── CHANGELOG.md
├── package.json              # @local/dsh-shiban  v0.5.0，dsh.bundle.patch
├── cordis.patch.yml          # 人格 + 子 Agent 人格 + skill-filesystem(bundledSkillDir) + 工具行
├── .gitignore
├── skills/                   # 6 原子 md（从 .dsh/skills 移植并改造）
│   ├── README.md
│   ├── lesson-plan.md  quiz.md  class-eval.md
│   └── class-profile.md  teacher-growth.md  html-material.md
├── framework/                # ★ 理论骨架（随包 = A 类）：方法论而非教材原文
│   ├── core.md               # 支架 / ZPD / 坡度 / 可撤除 原则
│   ├── templates/            # 由 材料/模版/（18 个 md）精简
│   └── courses/              # 课型插件（概念模型 / 科学史 / 验证实验 / 探究实验 / 复习）
├── vendor/
│   ├── bin/shiban-store      # 跨平台启动器（吸收 v0.4.3-Win：python 探测 + UTF-8）
│   ├── services/*.py         # store + cli + corpus + report
│   └── requirements.txt      # 空依赖；PyMuPDF 仅作可选增强
├── scripts/                  # build-corpus / build-package / install / verify / lint-skills
├── tests/                    # 纯标准库 unittest，SHIBAN_ROOT 隔离
└── docs/                     # 用户手册 / 导入指南 / 架构 / 迁移
```

### 四层职责（写入 `docs/architecture.md`，作为后续开发的宪法）

| 层 | 类别 | 位置 | 是否随包 | 是否可外传 |
|---|---|---|---|---|
| 骨架 | A | 本包 `skills/ framework/ vendor/` | ✅ | ✅ |
| 理论框架语料 | B | `$SHIBAN_ROOT/corpus/<id>/` + `corpus.db` | ❌ 导入 | ❌ 版权 |
| 素材 | C | `$SHIBAN_ROOT/data/assets/<id>/` | ❌ 产生 | ✅ 教师自愿 |
| 证据 | D | `$SHIBAN_ROOT/data/shiban/raw/`、`teacher_profile.json` | ❌ | ❌ 永不出机 |

**`材料/模版/` 的归属判定 = A（随包）**：它讲「怎么教」（主模板 / 课型插件 / 原子卡 / ZPD 原则），不涉及具体教材原文；空壳师伴若没有它就会「空而无骨」。

---

## 3. 分阶段任务（每阶段有独立验证门，不通过不进下一阶段）

### P0 · 版本控制与仓库初始化（半天）

1. `V0.5.0/` 建**独立 git 仓库**（子目录独立 `.git`，父仓不追踪它）。
2. `git init` → 首次提交 → 打 tag `shiban-v0.1.0-draft`（构建期基线）。
3. 写 `VERSIONING.md`（§4），明确「本包 git 仓库 = 唯一分发单位」。
4. **不改动父仓库**：tag 脱节、131 MB PDF 历史只在 §9 记为「父仓运维待办」，不阻塞 v0.5.0。

> **验证门**：`cd V0.5.0 && git log --oneline` 有 1 个提交；全树（不含语料）< 2 MB。

### P1 · 骨架移植与路径统一（3–4 天）

1. **复制并改造 6 个技能 md**：
   - 产出路径 `data/shiban/*.json` → `$SHIBAN_ROOT/data/shiban/*.json`（L1 统一位置，跨工作区继承才成立）；
   - 所有 `bin/shiban-store` → `"${SHIBAN_STORE:-shiban-store}"`（**唯一入口变量**）；
   - `data/shiban/raw/` → `$SHIBAN_ROOT/data/shiban/raw/`；
   - `class_profile.db` 去留：统一到 `meta.db` 的 `lessons` 表（store 已有），删除独立文件，避免双写。
2. **`framework/` 生成**：把 `材料/模版/` 按「主模板 / 课型插件 / 原子卡 / 设计原则」重整，去掉与具体教材绑定的大段示例，保留可迁移的方法论。
3. **写 `skills/README.md`（技能地图）与 `docs/architecture.md`（四层、数据流、降级语法）**。
4. **语言一致化**：技能正文中文；frontmatter `name` 保持 kebab-case（DSH 硬约束）。

> **验证门**：`grep -rn "bin/shiban-store\|data/shiban/" skills/ | wc -l == 0`（无裸路径残留）；`scripts/lint-skills.sh` 通过。

### P2 · 插件装配（2–3 天）

1. `package.json`：
   ```json
   { "name": "@local/dsh-shiban", "version": "0.5.0", "type": "module",
     "dsh": { "bundle": { "patch": "./cordis.patch.yml" } } }
   ```
2. `cordis.patch.yml`：
   - `preset-shiban` 人格：移植旧 bundle（约 500 行），把「工作区 `data/shiban/`」旧说法改为「`$SHIBAN_ROOT` 是唯一数据根」；
   - `skill-filesystem` 加 `bundledSkillDir: !!js path.join(...)`（照抄 dump 的 `!!js` 写法），**同时保留 `includeDefaultRoots: true`** 供教师放自有技能；
   - `tool-bash / tool-pwsh / tool-fs / 子 Agent` 行保持现状。
3. `vendor/bin/shiban-store`：吸收 `df653f9` 的跨平台逻辑（python 探测 + `PYTHONUTF8`），并新增：
   - `$SHIBAN_STORE` 已设则直接 `exec`；
   - `--version` 子命令；
   - 首会话无库时自动 `init`。

> **验证门**：`bash vendor/bin/shiban-store version` 输出 `0.5.0`；`init` 在 `/tmp/root` 返回 `ok`。

### P1.5 · 教案模板与交付链（★ rev.2 重点，6–8 天）

**目标**：把「书院杯」那套已验证的产物链内化为 store 能力——`lesson template → validate → render`，并且**首次使用时就能生成，而不是从零设计**。

#### P1.5-a · `framework/lesson-template/`（模板随包，A 类）

1. 置入 `template-v1.md`（来自 `2026-10书院杯/模板/高中生物理论课教学设计模板.md`），并补上 F7 实测的两处槽位：
   - **三、教学重难点** 增加可选 `3. 难点成因分析`、`4. 突破策略`（成品有此两节，模板原本没有）；
   - **九、教学评价** 增加可选 `课堂即时检测（随堂 N 题）` 表（列：题号 / 题目 / 参考答案 / 学生易错预估与应对）。
2. **槽位规范化**：给每个章节加**稳定槽位 ID**（`S0.meta`, `S1.curriculum`, `S1.textbook`, `S2.general`, … `S11.innovation`），并在模板里注明「必填 / 可选 / 条件必填」，供 `validate` 使用（见 P4）。
3. **两种呈现**（F10）：
   - `template` 版：完整十一节 + 〇基本信息（备课/校内评比用）；
   - `competition` 版：无〇节，开篇为「教材 + 章节」标题块 + 三列（主题/年级/教材/时间）信息表（书院杯/师范生技能竞赛用）。
4. `framework/standards/`：师范生职业能力标准、教资 **面试**评分维度（职业认知/心理素质/仪表仪态/言语表达/教学设计/教学实施/教学评价）、教资 **学科知识** 教学设计要求——作为 `validate` 的「合规依据」，并在模板「附录：检查清单」中与它们**显式对应**（每条检查项 → 哪个标准条目）。

> **验证门**：`bash scripts/lint-skills.sh --template` 校验槽位 ID 唯一且无遗漏；`framework/lesson-template/template-v1.md` 的 H2 序列与 §1.1 F6 完全一致。

#### P1.5-b · `lesson.json` 中间格式（单一事实源）

```jsonc
{
  "schema": "shiban.lesson/1",
  "style": "template",                       // template | competition（渲染时可选覆盖）
  "meta": { "title":"DNA的复制", "subtitle":"基于假说—演绎与建模的探究式教学",
            "grade":"高一", "textbook":"人教版高中生物学必修2《遗传与进化》",
            "chapter":"第3章第3节", "course_type":"新授课", "duration_min":40,
            "class":"普通高中高一平行班，4—5人一组" },
  "core_question": "一份写在DNA里的信息，凭什么在经历无数次复制后仍能被精确读出？",
  "sections": {
    "S1.curriculum": { "module":"必修课程模块2", "big_idea":"概念3 …", "important_idea":"3.1 …",
                       "subconcept":"3.1.3 概述DNA分子通过半保留方式进行复制",
                       "achievement_req":"…（生命观念、科学思维）",
                       "citation":[{"corpus_id":"std-bio-2017-2025","book_page":12,"quote":"…"}] },
    "S1.textbook": { "position":"第3章第3节，教材P.53—56", "overview":"…",
                     "internal_role":"…", "cross_links":["…"], "overall":"承上启下" },
    "S2.general":  { "cognitive_stage":"…", "prior_knowledge":"…", "thinking":"…", "response":"…" },
    "S2.style":    { "cognitive_mode":"…", "cooperation":"…", "preference":"…", "response":"…",
                     "classroom_mgmt":"…" },
    "S2.starting": { "known":"…", "preconceptions":[{"name":"…","evidence":"…","plan":"…"}], "ladder":"A→B→C" },
    "S3.points":   { "key_points":["…"], "difficulties":["…"],
                     "difficulty_causes":[{"difficulty":"…","cause":"…"}],
                     "breakthrough":[{"difficulty":"…","strategy":"…"}] },
    "S4.objectives":[{"dimension":"生命观念","on":"通过…","can":"…","develop":"…",
                      "assessable_sign":"…"}],
    "S5.methods":  [{"name":"引导发现法","basis":"…","how":"…","effect":"…"}],
    "S6.prep":     { "environment":["…"], "student":["…"], "teacher_materials":["…"] },
    "S7.flow":     { "stages":["导入","环节二…"], "lines":{"situation":"…","knowledge":"…","literacy":"…"},
                     "core_idea":"结构决定功能" },
    "S8.process":  [{"no":"一","name":"情境导入：…","minutes":3,
                     "teacher_activity":["【情境创设】…"], "student_activity":["【观察】…"],
                     "intent":"…", "scaffolds":["S1 …"]}],
    "S9.formative":{ "participation":{"weight":20,"rubric":{"A":"…","B":"…","C":"…","D":"…"}},
                     "objective_attainment":{"weight":30,
                       "rows":[{"objective_id":"O1","dimension":"生命观念","target":"…"}]},
                     "quick_check":[{"no":1,"stem":"…","answer":"…","pitfalls":"…"}] },
    "S9.summative":{ "weight":50, "task":"…", "requirements":["…"],
                     "mapping":["O1","O2","O3","O4"] },
    "S10.board":   { "main":"…", "side":"…", "generative":"…",
                     "structure":{"type":"tree|frame|table","nodes":["…"]} },
    "S11.innovation":[{"title":"…","what":"…","how":"…","effect":"…"}]
  },
  "citations": [ { "corpus_id":"bx2","book_page":55,"quote":"…","section":"S8.process[4]" } ],
  "controversy": [ { "section":"S4.objectives[2]", "issue":"…", "my_view":"…" } ]
}
```

**三条硬规则**：
1. **一个目标 = 一行**：`S4.objectives[]` 的条数即目标数（3–4），`S9.formative.objective_attainment.rows[]` 与之一一对应（`objective_id`），`S9.summative.mapping` 也必须引用它们——**评价与目标一一对应**（模板 §九 的填写提示）。
2. **过程表即数据**：`S8.process[]` 的 `minutes` 之和必须等于 `meta.duration_min`（`validate` 检查）。
3. **引用只认 corpus**：任何 `citation` 必须能在 `corpus` 中找到（`corpus read` 可复现），否则降级为 `quote` 无页码并在 `validate` 报警。

> **验证门**：用 `DNA半保留复制` 成品反向生成 `lesson.json`（**往返测试**），再渲染回 Markdown，H2/H3 结构一致。

#### P1.5-c · `lesson template / validate / render` 三个命令

```text
shiban-store lesson template [--style template|competition] [--out lesson.json]
    # 从 framework/lesson-template/ 生成骨架（含所有槽位与填写提示），不覆盖已存在文件
shiban-store lesson validate --file lesson.json [--strict]
    # 结构（章节齐备）+ 一致性（目标↔评价、时长和）+ 合规（标准条目映射）
    # 输出 {ok, errors:[{code,section,message}], warnings:[...]}，退出码 0/2
shiban-store lesson render --file lesson.json [--style ...] [--out-dir DIR]
                           [--formats md,html,pdf] [--pdf-engine auto|chrome|prince|none]
    # 产出 <title>.md / .html / .pdf；pdf 引擎按 auto 探测：chrome → prince → 不生成
shiban-store lesson cover --file lesson.json --out cover.pdf   # 封皮（F9）
```

**排版约束**（从 `prince-print.css` 已有经验固化，写进 `framework/print/lesson.css`，**用 `@media print` 而非 Prince 专有语法**）：

| 规则 | 来源 |
|---|---|
| `table-layout: fixed` + 显式列宽类（`.process-table` / `.achieve-table` / `.grade-table` / `.quiz-table` / `.meta-table`） | `md2html_prince.py:44-58` |
| `thead { display: table-header-group }`（跨页表头） | README「已解决的排版问题」 |
| 中文字族：`"Times New Roman", "SimSun", "Noto Serif CJK SC", serif`；上标/下标与特殊符号分流 | `prince-print.css:40-60` |
| A4、页眉（**参数化标题**）、页脚 `counter(page)"/"counter(pages)` | `prince-print.css:8-30`（标题不再硬编码） |
| 设计思路/板书：**纯 CSS/ASCII 框图**，不依赖 Mermaid | 见 §1.3 |

> **验证门（N2/N3）**：`lesson render --formats md,html,pdf` 在**无 Prince 有 Chrome**的机器上产出 PDF；把 `PATH` 里的浏览器也去掉后，命令返回 `ok` 但 `pdf: "skipped(no-engine)"`，**不得抛异常**。

#### P1.5-d · 示例固件与回归

- `framework/fixtures/dna-replication/lesson.json` + `expected-template.h2.txt` + `expected-competition.h2.txt`；
- `tests/test_lesson_render.py`：对示例渲染两版，断言 H2 序列、教学目标↔评价映射、时长和、引用可解析。

> **验证门**：`python3 -m unittest tests.test_lesson_render` 全绿；N1 通过。

### P3 · 语料层 corpus（5–7 天，最大工作量）

1. **数据模型**（`$SHIBAN_ROOT/corpus.db`）：
   ```sql
   CREATE TABLE corpus ( corpus_id TEXT PRIMARY KEY, title, publisher, edition,
                         subject, volume, kind /* textbook|standard|reference|personal */,
                         page_offset INTEGER, provenance TEXT, sha256, imported_at );
   CREATE TABLE corpus_page ( corpus_id, pdf_page, book_page, text );
   CREATE VIRTUAL TABLE corpus_fts USING fts5(text, corpus_id UNINDEXED, pdf_page UNINDEXED,
                                              book_page UNINDEXED, tokenize='trigram');
   ```
2. **命令（全部零第三方依赖）**：
   ```
   shiban-store corpus import --file <pdf|md> --meta '{...}' [--page-offset N]
   shiban-store corpus list
   shiban-store corpus search --kw <词> [--corpus <id>] [--limit N]
   shiban-store corpus read --corpus <id> --p <教材P> [--around N]
   shiban-store corpus pages --corpus <id>            # 分页 / 章节目录
   shiban-store corpus remove --corpus <id>           # 二次确认
   shiban-store corpus verify                          # 校验 sha256 与页数
   ```
3. **转档后端**：首选 `pdftotext -layout`（`\f` 分页）→ 备选 PyMuPDF → 都没有则读已转 md（`--file x.md`，页号不可知时显式 `book_page: null`）。
4. **页码锚点**：每页一行 `<!-- page:pdf=<n> book=<n> -->`，`corpus read` 原样带出。
5. **中文检索**：FTS5 `trigram`；`--kw` 短于 3 字时退回 `LIKE` 子串。
6. **章节索引**：`pages` 从页文本识别 `第N章 / 第N节` 行，生成轻量目录（不依赖外部大纲文档）。

> **验证门**：导入必修1 → `corpus search --kw 细胞学说` 至少命中 2 页且 `book_page` 正确；`corpus read --corpus bx1 --p 2` 正文含「细胞学说的建立过程」。

### P4 · 技能契约接入语料与教案产物（3 天，rev.2 扩写）

1. `lesson-plan`（**最大改动**）：
   - **产出契约改为两层**：先写 `$SHIBAN_ROOT/data/shiban/lesson.json`（`schema: shiban.lesson/1`，见 P1.5-b），再由 `shiban-store lesson render` 派生 `.md/.html/.pdf`；
   - **保留 v0.4.3 的「2–3 个候选」**：`candidates` 仍产生 2–3 个方案，但每个候选就是一个**完整的 `lesson.json` 骨架**（而不是只有支架片段），这样「选定 → 定案 → 渲染成品」是一条线；
   - 新增可选输入 `corpus`（先 `corpus list`，命中则 `corpus search` 取依据写进 `S1.*.citation` 与 `citations[]`）；缺失时 `meta.notes` 声明「无语料依据」，**不得编页码**；
   - 新增输出 `controversy[]`：把「有争议/有取舍」的地方显式记录（例如成品里「弥散复制是思维工具、不作考试要求」「古DNA只证明亲缘关系不证明社会形态」「比赛版删去〇基本信息」），渲染时带 `※` 标记；
   - 新增输入 `style`：`template`（备课用，含〇节）或 `competition`（竞赛用，无〇节），默认取教师偏好档案。
2. `quiz`：同项 + `quick_check` 槽位与 `S9.formative.objective_attainment` 的「易错预估」互链（题 → 目标 → 支架）。
3. `class-eval / class-profile / teacher-growth`：不改内容，只统一路径到 `$SHIBAN_ROOT`；`class-eval` 读教案时改为读 `lesson.json` 的 `S8.process[]`（支架环节），比 v0.4.3 的 `current_lesson.json` 更结构化。
4. `html-material`：保持「外部素材库」语义，只修路径；新增「教案产物可引用素材」的弱链接（`S6.prep` 中可挂 `asset_id`）。

> **验证门**：用测试语料跑一遍 lesson-plan 契约样例 → `lesson validate` 通过 → `lesson render` 产出三格式；`citations.book_page` 可由 `corpus read` 复现；N5 通过。

### P5 · 导出 / 备份 / 迁移（1–2 天）

1. `shiban-store export --out <x.shiban-pkg>`：zip + `manifest.json`（版本、asset 列表、corpus **元数据不含正文**）。
2. `shiban-store import-pkg <x.shiban-pkg>`：只恢复 C 类素材；B 类语料**不进包**（版权）。
3. `shiban-store doctor`：检查 root 权限、FTS5、python 版本、旧版 `data/shiban/` 迁移提示。
4. `v0.4.3 → v0.5.0` 迁移脚本：旧 `~/.shiban/data/meta.db` 原样保留（新库新增表，不改旧表），旧工作区 JSON 列出清单由教师决定是否导入。

> **验证门**：`export` → 删除 `assets/` → `import-pkg` → `asset list` 恢复；`manifest.json` **不含**任何教材正文。

### P6 · 测试与安装验证（2–3 天）

1. `tests/` 扩展：
   - `test_corpus_store.py`（导入 / 检索 / 页码 / 幂等 / 失败回滚）
   - `test_corpus_cli.py`
   - `test_lesson_render.py`（★ 示例往返、双版 H2、N1–N5）
   - `test_store_paths.py`（`SHIBAN_ROOT` 隔离；无工作区可用）
   - `test_packaging.py`（包内文件齐备、version 一致、无个人数据）
   - 原有 9 个测试移植并保持全绿。
2. `scripts/verify.sh`：一键跑 **A1–A9** 与 **N1–N5**。
3. **插件装验证**：复制 web profile 到临时目录，在该副本里 `dsh plugin add /.../V0.5.0`，再 `--dump-config` 检查 `preset-shiban` 与 `bundledSkillDir`。

> **验证门**：`bash scripts/verify.sh` 全绿；A7 / N1–N5 通过。

### P7 · 文档与发版（1–2 天）

1. `docs/`：`README`（5 分钟上手）、`import-guide`（导入自己的教材）、`lesson-guide`（★ 教案模板怎么用：`template` 与 `competition` 两版、即时检测/难点成因两个可选槽位、质检清单）、`architecture`、`migrate-v0.4.3`、`copyright`。
2. `scripts/build-package.sh` → `dist/shiban-0.5.0.tgz` + `.sha256`。
3. `git tag shiban-v0.5.0`（annotated）；tag 与 `package.json.version` 的断言写进 `verify.sh`。

> **验证门**：`tar tzf dist/shiban-0.5.0.tgz` 文件数在预期范围；`grep -r teacher_profile` 为空。

---

## 4. 版本控制方案（五条铁律，写入 `VERSIONING.md`）

1. **一个分发单位 = 本包 git 仓库**。`package.json.version` 是唯一真源；tag 名固定 `shiban-v<version>`。
2. **语料永不入库**：`材料/教材/`、`corpus/`、`*.shiban-pkg` 全部在 `.gitignore`。
3. **个人数据永不入库**：`raw/`、`teacher_profile.json`、`meta.db`、样例 `*.json` 全部忽略。
4. **父仓库不动**：v0.5.0 独立成库；父仓的 tag 脱节 / 131 MB PDF 历史记为待办（§9），新库稳定后再处理。
5. **幂等升级**：迁移脚本必须可重复执行（`IF NOT EXISTS` / `--dry-run`）。

**tag 策略**：`shiban-v0.5.0-rc.N` → 验收通过 → `shiban-v0.5.0`。`rc` 不推远端，正式版才推。

**模板与示例的版本（rev.2 新增，铁律 6）**：
6. **模板与示例固件同库同版本**：`framework/lesson-template/template-v1.md` 与 `framework/fixtures/dna-replication/` 随包发版；模板结构改动（增删槽位）**必须**升 `template-vN` 并在 `CHANGELOG` 注明「旧 `lesson.json` 是否兼容」；`lesson.json` 的 `schema` 字段用 `<name>/<major>`，**major 变化即视为不兼容**，需提供迁移脚本。

---

## 5. 排期（rev.2：约 4.5–5 周，串行；P1.5 可与 P3 并行）

```text
P0   ██            (0.5d)   版本地基
P1   ████          (3.5d)   骨架移植
P1.5 ████████      (7d)     教案模板与交付链 ★rev.2 重点
P2   ███           (2.5d)   插件装配
P3   ███████       (6d)     语料层 ★核心
P4   ███           (3d)     契约接入（含教案）
P5   ██            (1.5d)   导出 / 迁移
P6   ████          (3d)     测试验收（含 N1–N5）
P7   ██            (1.5d)   文档发版
```

并行建议：**P1.5 与 P3 可以两人/两线并行**——P1.5 只依赖 `framework/`，P3 只依赖 `corpus.db`，两者唯一的交叉点是 `S1.*.citation`（先定字段名即可）。

---

## 6. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| **沙箱写不了 `~/.dsh`** | 无法在你正在用的 GUI 上真装 | 用临时 `DSH_HOME` 副本验证（A7）；真装写手册由你执行 |
| **`!!js` 在 preset 子行的 `baseUrl` 语义未证实** | `bundledSkillDir` 可能解析失败 | P2 先做最小试验：`bundledSkillDir` 用 `!!js` 相对包路径 + `includeDefaultRoots: true` 双保险；失败则退回 copy 到 `~/.dsh/skills` |
| **`pdftotext` 双栏错行** | 教学质量下降 | 本机样张实测可读；`corpus verify` 加「连页重复行」检测；不达标退回 PyMuPDF |
| **版权** | 不能分发 | 包内**零语料**；导入时提示「仅限本人合法持有」；语料包禁止外传 |
| **`class_profile.db` 迁移** | 旧数据丢失 | 只读合并进 `meta.db.lessons`，保留源文件副本，不删 |
| **与现有 GUI 并行** | 改动 `~/.dsh` 影响正在用的会话 | 全程独立 profile / 独立 `SHIBAN_ROOT` |
| **打印引擎不可移植（rev.2）** | 换机后 PDF 出不来，或版式与书院杯成品不一致 | 主产物定为 **HTML**（零依赖），PDF 为增强；Chrome/Prince 二者取其一，且**校准一次两引擎的页眉页脚差异** |
| **Mermaid 二次依赖（rev.2）** | `mmdc` 需要 Chrome，长链路 | 运行时**不渲染** Mermaid；设计思路/板书用内置 CSS/ASCII 框图；若教师手上有 `.mermaid` 源码，作为「可选增强」走 `mmdc` 且失败不阻断 |
| **模板漂移（rev.2）** | 模板改了，旧 `lesson.json` 渲染错乱 | 铁律 6：模板 `vN` 与 `schema` major 绑定；`lesson validate` 先校验 `schema` 版本 |
| **竞赛体例 vs 学校体例（rev.2）** | 同一份教案要在两种场合提交 | `--style template|competition` 双渲染，**内容只有一份** `lesson.json` |

---

## 7. 修改清单（精确到文件）

| 动作 | 文件 |
|---|---|
| 新建 | `V0.5.0/{package.json, cordis.patch.yml, CHANGELOG.md, VERSIONING.md, .gitignore}` |
| 移植+改造 | `V0.5.0/skills/*.md`（6 个 + README） |
| 新建 | `V0.5.0/framework/{core.md, templates/*, courses/*}` |
| **新建（rev.2）** | `V0.5.0/framework/lesson-template/template-v1.md`（来自 `2026-10书院杯/模板/`，补两处可选槽位 + 槽位 ID） |
| **新建（rev.2）** | `V0.5.0/framework/standards/{师范生职业能力标准, 教资面试评分维度, 教资学科教学设计要求}.md`（从 `2026-10书院杯/素材/标准/` 去噪整理） |
| **新建（rev.2）** | `V0.5.0/framework/print/lesson.css`、`V0.5.0/framework/fixtures/dna-replication/{lesson.json, expected-*.h2.txt}` |
| 移植+改造 | `V0.5.0/vendor/bin/shiban-store`、`vendor/services/{shiban_store.py, shiban_cli.py, shiban_corpus.py, **shiban_lesson.py**, shiban_report.py}` |
| **新建（rev.2）** | `vendor/services/shiban_lesson.py`（由 `md2html_prince.py` 重写：模板/校验/渲染/封皮，纯标准库） |
| 新建 | `V0.5.0/scripts/{build-corpus.sh, build-package.sh, install.sh, verify.sh, lint-skills.sh}` |
| 新建 | `V0.5.0/tests/*`（新增 5 个 + 移植 2 个） |
| 新建 | `V0.5.0/docs/*`（含 `lesson-guide.md`） |
| **只读** | 父仓 `材料/`、`md/`、`.dsh/skills/`、`services/`、`bin/`、`data/`；`~/Documents/WorkSpace/2026-10书院杯/**` |

---

## 8. 需要你拍板的事项（不确认则按推荐默认值开工）

| # | 事项 | 推荐 | 理由 |
|---|---|---|---|
| 1 | 父仓库处理：tag 脱节 + 131 MB PDF 历史 | **本次不动**，只记录待办 | 新库独立，不阻塞 |
| 2 | `材料/模版/` 是否随包 | **随包（A 类）** | 讲「怎么教」，是骨架 |
| 3 | `class_profile.db` 是否合并进 `meta.db.lessons` | **合并** | 消除双写 |
| **4** | **教案主稿格式**：HTML 主稿 / Markdown 主稿 / Prince 优先 | **HTML 主稿 + Markdown 导出**（§1.3） | 装完即用的下限只需浏览器 |
| **5** | **`lesson.json` 做中间格式**（两版渲染只维护一份内容） | **要做** | 避免「模板版/比赛版」两套人工维护 |
| **6** | **Instant check 与难点成因是否进模板** | **进模板作可选槽位** | 书院杯成品已自发使用 |
| **7** | **`素材/范例/教学设计范例.pdf`（第三人作品）是否打包** | **不打包**，只在文档里写来源 | 授权不明 |
| **8** | **`素材/标准/*.md` 是否随包** | **随包**（去噪），作为 `validate` 合规依据 | 与教材无关、体量小 |

---

## 9. 父仓库运维待办（不在 v0.5.0 范围）

| # | 问题 | 建议 |
|---|---|---|
| T1 | `v0.4.3` tag（f964db2）与 HEAD（6c871d2）脱节，合并提交落在 tag 下游 | 新打 annotated tag `v0.4.3.1` 指向 `6c871d2`；不强制移动旧 tag |
| T2 | `v0.4.3-Win`（df653f9）未合回主干 | `git cherry-pick` 回主干，或由 v0.5.0 的 `vendor/bin/shiban-store` 吸收（**已完成吸收，见 P2**） |
| T3 | `材料/教材/*.pdf` 131 MB 在 git 历史（`fde54c7` 引入） | 三选一：保持现状 / `git filter-repo` 重写历史 / 拆独立数据仓。建议新库稳定后再定 |
| T4 | `构建/shiban-bundle/`、`构建/upgrade/` 未入 git | v0.5.0 稳定后，把 `构建/` 目录整体迁入 v0.5.0 的 `docs/legacy/` 并从父仓删除 |
| **T5（rev.2）** | `2026-10书院杯/` 是**独立工作区**（不属本仓库），其中的 `教学设计/DNA半保留复制/` 有 6 版历史与 node_modules | 不进本仓；**只把成品 md 与模板做「只读移植」**；如需留档，建议它单独 `git init` |

---

## 10. 附录：关键实测命令与输出

```bash
# F1：dump-config 在真实 profile 上被沙箱拒绝
cd ~/.dsh/profiles/web && dsh --profile web --dump-config
# → Error: EACCES: permission denied, open '/home/levi/.dsh/profiles/web/cordis.yml'

# F1 绕行：复制 profile + 独立 DSH_HOME
cp -a ~/.dsh/profiles/web /tmp/profcheck && cd /tmp/profcheck
DSH_HOME=/tmp/profcheck/home dsh --dump-config --profile web > dump.yml   # 1259 行

# F4：pdftotext 分页与偏移
pdftotext -layout "材料/教材/普通高中教科书·生物学必修1 分子与细胞.pdf" /tmp/pt-bx1.txt
python3 -c "print(len(open('/tmp/pt-bx1.txt').read().split(chr(12))))"   # 142 页
# 第 11 页首行 = 第1节 / 细胞是生命活动的基本单位 → 教材 P.2，page_offset = 9

# F5：路径矛盾
grep -rn "data/shiban/" .dsh/skills/*.md | wc -l     # 技能写工作区
grep -n "DATA_DIR\|META_DB" services/shiban_store.py # store 写 ~/.shiban

# F6/F7：模板与成品的章节结构比对（rev.2）
python3 - <<'EOF'
import re
for p in ['模板/高中生物理论课教学设计模板.md',
          '教学设计/DNA半保留复制/DNA半保留复制教学设计.md']:
    t = open(os.path.expanduser('~/Documents/WorkSpace/2026-10书院杯/'+p), encoding='utf-8').read()
    print(p); [print('  ', m.group(2)) for m in re.finditer(r'^(##)\s+(.*)$', t, re.M)]
EOF

# F8：导出链与软依赖（rev.2）
which prince google-chrome chromium-browser   # 本机三者都有；DSH 不自带
wc -l 教学设计/DNA半保留复制/md2html_prince.py prince-print.css          # 337 / ~350
pdfinfo 教学设计/DNA半保留复制/DNA半保留复制教学设计.pdf | grep Pages    # 15
pdfinfo 教学设计/DNA半保留复制/楼恩琦生科DNA的复制.pdf  | grep Pages     # 16（含封皮 1 页）

# F9：封皮靠文本层即可抽取（可脚本化生成）
pdftotext -layout 教学设计/DNA半保留复制/教案封皮.pdf -   # 姓名/授课科目/授课题目

# F10：版本演进 H2 比对
grep -n "^## " 教学设计/DNA半保留复制/DNA半保留复制教学设计_V01.md   # 18 个（含〇节）
grep -n "^## " 教学设计/DNA半保留复制/DNA半保留复制教学设计.md       # 12 个（无〇节，比赛体例）
```

---

## 11. 落地顺序（今天就能开始）

1. `V0.5.0/` 建独立 git 仓库，写入 P0 四份地基文件（`VERSIONING.md`、`.gitignore`、`CHANGELOG.md`、`package.json`）；
2. 跑 P1 第一条：复制 6 个技能 md 并做路径统一（用 `grep -c` 量化）；
3. **跑 P1.5-a 第一条**：把书院杯模板搬进 `framework/lesson-template/template-v1.md` 并补两处可选槽位（这一步不依赖任何代码，**当天可见效果**）；
4. 每完成一个阶段跑一次 `scripts/verify.sh`，红则停。

---

## 12. 教材 / 教案 / 理论与「素材」四者的边界（rev.2 收口）

| 概念 | 是什么 | 住哪 | 随包? | 可外传? |
|---|---|---|---|---|
| **教材（corpus）** | 他人著作的**原文**（课标、教科书、教参） | `$SHIBAN_ROOT/corpus/<id>/` | ❌ 教师导入 | ❌ 版权 |
| **标准（standards）** | 国家/考试**评判准则**（课标摘要、教资大纲、师范生能力标准） | `framework/standards/` | ✅ | ✅（公开文件） |
| **模板（template）** | **怎么写教案**的结构与填写提示 | `framework/lesson-template/` | ✅ | ✅ |
| **教案（lesson.json / 成品）** | 教师**自己写出来的**一份教学设计 | `$SHIBAN_ROOT/data/shiban/lessons/` | ❌ 产出 | ✅ 教师自愿 |
| **素材（asset）** | 可复用的 HTML 教具/交互件 | `$SHIBAN_ROOT/data/assets/<id>/` | ❌ 产出 | ✅ 教师自愿 |
| **证据（evidence）** | 课堂记录、微格转写、画像 | `$SHIBAN_ROOT/data/shiban/raw/` 等 | ❌ | ❌ 永不出机 |

> 一句话：**教材是燃料，标准是尺子，模板是图纸，教案和素材是成品，证据是隐私。** 前两者可替换（老师可能用别的版本、别的学科），中两者随包（换了学科也成立），后两者是教师自己的积累。
