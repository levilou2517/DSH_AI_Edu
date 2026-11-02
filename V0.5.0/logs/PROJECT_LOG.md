# 项目日志（可追溯）

> 记录每次推进做了什么、依据是什么、遗留什么。按时间倒序。

## 2026-11-02（四）· 版本化命名、数据根隔离与素材迁移

**四项要求及其落地**

| 要求 | 落地 |
|---|---|
| 命名带版本 | 包 `@local/dsh-shiban-v0-5-0`；预设 id `ShiBan_V0_5_0`；显示「师伴 v0.5.0」 |
| 新版本继承素材 | `shiban-store migrate`：默认干跑，`--yes` 执行，不覆盖同名文件，写 `MIGRATION.json` |
| 安装位置随 DSH 变 | 所有路径从 `import.meta.url` / `__file__` 推导；`shiban-store info` 可查实际位置 |
| 预设命名 `ShiBan_VX_X_X` | 行 id 亦改为 `preset-shiban-v0-5-0` / `shiban-runtime-v0-5-0` |

**数据根改为按版本隔离**

```
$SHIBAN_ROOT/versions/v0_5_0/     ← 本版本
$SHIBAN_ROOT/versions/v0_6_0/     ← 将来
$SHIBAN_ROOT/data/…               ← 旧扁平布局，用 migrate 继承
```

理由：升级/回退互不破坏；两版本可并存对照。`SHIBAN_DATA_DIR` 可完全接管（测试用）。

**迁移只迁"积累物"**：corpus / assets / theory-derived / evidence / artifacts，
不迁代码、配置、日志、临时文件。

**开发阶段保持空包**：迁移**不自动触发**，只有显式 `migrate run --yes` 才动数据。
实测空根 init 后只有 `graph.db` 一个文件。

**实测**

| 项 | 结果 |
|---|---|
| 真实安装（带版本名） | exit 0；`dsh-shiban-v0-5-0` 与旧 `dsh-shiban-preset` **并存** |
| 配置合成 | `ShiBan_V0_5_0` 命中 1 处；技能根解析到带版本包名 |
| 从安装位置调 CLI | `package_dir=/tmp/dt2/pkg`，`data_root=/tmp/dt2/root/versions/v0_5_0` |
| 迁移干跑/执行/重跑 | 4 项复制 → 重跑 0 复制 4 跳过（幂等） |
| 六模块冒烟 | 6/6 |

**迁移范围收窄**：v0.5.0 之前的素材不迁移（用户确认）。
`discover_sources` 只认 `versions/vX_Y_Z` 且版本 ≥ 0.5.0；
更早版本列出但标 `migratable:false`，避免误以为"找不到"。
实测：v0_5_1 可迁、v0_4_3 与 legacy 均不可迁。

**踩坑**

- `plan_migration` 内误用 `it["from_"]`（该键此时尚未构造）→ 改用局部变量。
- `items_skip` 分支依赖 `from_` → 改为从源根拼路径。
- JS 侧漏 import `readFileSync`。

**打包**：`dist/shiban-0.5.0.tgz`，888 KB / 305 文件，sha256 已生成。

## 2026-11-02（三）· 理论库接入

**核心决策：文献不进包，只进"提炼框架 + 引证编号"**

- 首版曾把 38 篇全文（2.0 MB）复制进 `framework/theory/builtin/`，随即撤销——
  全文属第三方版权，且随包分发没有必要。改为：
  - `citations.json` 只登记元数据（编号/标题/页码范围/源文件哈希），**不含正文**；
  - 全文留在维护者源库 `理论库/` 或教师自己的 `$SHIBAN_ROOT/theory/derived/`。
  - 包体因此从 2.0 MB 降到 48 KB。

**两层隔离**

| | builtin | derived |
|---|---|---|
| 来源 | 随包 | 教师自补 |
| 升级 | 覆盖 | **永不覆盖** |
| 编号 | `T-BUILTIN-nnn`（不复用） | `T-DERIVED-nnn` |
| 冲突 | 以 derived 为准 | — |

**提炼出的三份框架（Agent 真正要读的）**

| 文件 | 行数 | 引用 | 内容 |
|---|---|---|---|
| `pck-zpd.md` | 239 | 123 处 / 5 篇 | PCK 三轴、5 条"联系"判据、ZPD 与支架三条硬要求、18 个提问模板、22 条判定清单 |
| `evidence-levels.md` | 170 | 26 处 / 4 篇 | 数据→证据四层、A–D 证据级、够不够四问、微格铁律 |
| `standards-map.md` | 137 | 21 行映射 | 标准原文 → 可检查项 → 环节 → 判定门槛 |

三份都遵守：论断带 `〔T-BUILTIN-nnn p.N〕`、引证 ≤40 字、推断标 `〔推断〕`。

**工具链**

- `tools/ingest-theory.py`：生成引证清单；编号稳定，源文件缺失标 `missing` 不删号。
  修正了标题提取（文件名优先于 PDF 转换残留的泛化标题）。
- `shiban_theory.py`：`list/stats/pages/read/search/cite/verify/add/audit`。
  正文按需定位——内置查源库、补充查 derived；都缺失时报 `no_fulltext` 而不是静默失败。
- `theory audit`：检查页码越界、编号不存在、引证超长；
  **无页码标记的文献（如 T-BUILTIN-032）显式报"不可页码核验"**，不装作通过。
- `ctx pack`：按配方携带对应框架的文件名与用法，体积控制在 1.8 KB。

**验证**

- `theory audit` → ok，硬问题 0；150 处页码引用全在有效范围。
- 六模块冒烟 6/6；包体 6.3 MB（vendor/python 5.1 MB）。

**遗留**

- `standards-map.md` 中 `T-BUILTIN-032` 用章节号引用（该转换稿无页码标记），
  核验需回溯原件；已在审计里显式标注。
- 两份框架由子代理起草后经人工审校；`standards-map.md` 的子代理中途退出，映射表由父代理核对补完。

## 2026-11-02（续）· 零配置安装 + 自带运行时 + 提问协议收口

**新增能力**

- **零配置安装**：`cordis.patch.yml` 增加 `shiban-runtime` 行（`lib/index.js`）。
  挂载时幂等建 `$SHIBAN_ROOT` 骨架 → 跑 `init` → 跑 `doctor`，缺失依赖写
  `$SHIBAN_ROOT/data/logs/runtime.log`，不再要求用户手工初始化。
- **预设随包注册**：`preset-shiban` 声明行使预设「师伴」在安装后自动出现在预设列表；
  `presets/` 下只放给人看的装配说明，配置唯一真源仍是 `cordis.patch.yml`。
- **自带 Python 运行时**：`tools/vendor-python.py` 追踪 CLI 的真实导入闭包（58 个模块，3.2 MB），
  复制到 `vendor/python/lib`；启动器把它放在 `PYTHONPATH` 最前。
  `python3 -S` 完全隔离系统包时，`init` / `version` / `doctor` 仍全部通过。
- **提问三档协议**：A 立即问（`timeout: -1`）/ B 暂存推进 / C 达阈值强制暂停，
  默认阈值 **5**；`ask log` / `ask stats` 记录每次暂存、暂停、回答。
- **证据引用分流**：`role=evidence` 的 ref 从 `refs` 移入 `evidence[]`，不进图；
  文件不存在时标 `missing`（此前会被当作"未落盘的弱边"，语义错误）。
- **引用可核验**：`lesson validate --check-citations` 逐条回 `corpus` 复核引文，
  复现不到即判不过——这是"引用可追溯"的硬证据。
- **画像与偏好分离**：`ctx pack` 只把 `preferences` 给所有原子，`class_profile` 类条目走 `profile` 字段。

**验证记录**

| 项 | 结果 |
|---|---|
| 六模块冒烟 | 6/6 OK |
| 干净安装演练（仅 base + web-app + 本包） | dump 中预设 1 / 运行时 1 / 技能根 1 / timed 提问 1 |
| 自带运行时隔离测试 | `-S` 下三条命令全通过 |
| 技能清单 | 6/6，行数 79–226 |
| 包体 | 6.2 MB（其中 vendor/python 5.1 MB） |

**子代理交付**

- core（1492 行）、corpus（2209 行）、lesson（2069 行 + 模板 336 行）、4 个技能（739 行）。
- 并行写入导致 core 出现两次文件冲突，已由主 Agent 收敛（21 个 API 全在，自检 OK）。

**迁移范围收窄**：v0.5.0 之前的素材不迁移（用户确认）。
`discover_sources` 只认 `versions/vX_Y_Z` 且版本 ≥ 0.5.0；
更早版本列出但标 `migratable:false`，避免误以为"找不到"。
实测：v0_5_1 可迁、v0_4_3 与 legacy 均不可迁。

**踩坑**

- `--profile web --help` 与 `dsh headless` 的参数位置不同；`--patch` 覆盖要求 name 与包声明一致。
- 设计 assets 的 `--human` 在子命令后不生效 → 改为扫描 argv 后摘除。

**遗留**

- Windows `.cmd` 启动器仍未在 Windows 实机验证。
- Chrome 打印 PDF 分支未触发（本机走 Prince）。
- 尚未在真实 `~/.dsh` 安装（沙箱限制），已用副本完成等价验证。

## 2026-11-02 · v0.5.0 骨架搭成

**做了什么**
- 建 `V0.5.0/` 独立包：`package.json` / `VERSION` / `cordis.patch.yml` / `.gitignore`
- 契约层：`artifact.schema.json`、`receipt.schema.json`、`ctx-recipe.schema.json`、`constants.json`
- 数据层：`shiban_core.py`（产物 + 图 + 证据 + 索引 + 提问日志）
- 语料层：`shiban_corpus.py`（导入 / 分页 / bigram 索引 / 检索）
- 教案层：`shiban_lesson.py`（十一章节校验 + 双风格渲染）、`template-v1.md`
- 素材层：`shiban_asset.py`（体检 / 导入 / 分类 / compose）
- 入口：`shiban_cli.py`、`vendor/bin/shiban-store`（含 `.cmd`）
- 技能：`lesson-plan.md`、`quiz.md`（另 4 个在写）
- 配方：`framework/ctx-recipes/*.json`（6 份，含 question_budget）
- 文档：README / architecture / capability / lesson-guide / import-guide
- 冒烟：`scripts/smoke.py`，6 步全绿

**关键决策与依据**
- 数据用 JSON 文件为真源、DB 只存索引与图 —— 为可 diff、可 git。
- 提问放指挥层 —— DSH 规定存活子 Agent 调用 `ask_user_question` 会被 `DELEGATED_CALLER` 拒绝。
- 阈值 5、暂停必留痕 —— 用户要求；`ask log` / `ask stats` 提供复盘依据。
- 附录「检查清单」不渲染进成品 —— 是写给作者的编写指引，非交付内容。

**踩过的坑（已修）**
- `_db()` 每次连接都 `executescript` 建表，会重置事务状态导致写入静默丢失 → 改为只在建库时执行一次。
- `edges` 表复合主键下 `WHERE src=?` 查询异常 → 改普通表 + 独立索引，唯一性由应用层保证。
- `_walk_section` 正则 `([^.\\[\\]]+)?` 允许空匹配，导致解析错位 → 去掉可选量词。
- 自检用例把 `mark_stale` 方向写反（应查引用者而非被引用者）→ 已按语义修正。

**遗留**
- 4 个技能待合并（class-eval / class-profile / teacher-growth / html-material）
- 见 `docs/capability.md`「未验证」表
