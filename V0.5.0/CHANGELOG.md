# 更新日志

## v0.5.0 — 空壳版

### 发布准备

- **包名定为 `@levilou/dsh-shiban`**，发布到 npm（`private: false`、`publishConfig.access: public`、`license: MIT`）。
  此前本地开发用的是 `@local/dsh-shiban-v0-5-0`；改为稳定的 npm 包名 + semver 版本，
  多版本并存的真正隔离点放在**预设 id（`ShiBan_V*`）与数据根（`versions/*`）**。
- `package.json` 增加 `files` 白名单，打包排除 `__pycache__`、`logs/`、`scripts/`、`tools/`。
  实测：270 文件 / 897 KB（压缩）/ 4.0 MB（解压）。

---

## v0.5.0 — 重构内容

一次彻底重构。目标不是加功能，而是把 v0.4.x "文档、PPT、代码三张皮"的问题从根上解决。

### 新增

- **契约层** `contracts/`：产物信封、回执、上下文配方三份 schema + 统一常量。
  代码与技能都从它派生，不再各自定义字段。
- **统一写入通路** `artifact put`：原子写 + 引用图 + 乐观锁 + 环检测，失败全回滚。
  解决了 v0.4.x 中"Agent 直接写文件、状态靠口头声明"的问题。
- **引用图** `graph.db`：强边（目标已存在）与弱边（悬空候选）分开，上游变更沿强边传播 `stale`。
- **读视图分级** `index / digest / section / full`：指挥默认只读索引（<2 KB），治信息过载。
- **上下文包** `ctx pack --for <原子>`：六份配方，返回"恰好够用"的输入，字段名即契约字段名。
- **教案模板与渲染**：十一章节体例，`template` / `competition` 两种风格，
  Markdown / 自包含 HTML / PDF（Prince 或 Chrome，缺失时明确报告而非报错）。
- **语料层** `corpus import/search/read/verify`：带页码锚点，中文 bigram 检索。
- **素材层** `asset triage/import/compose/suggest`：外来 HTML 先体检后入库，
  `iframe sandbox="allow-scripts" srcdoc` 隔离编排。
- **提问协议** `framework/ask-protocol.md`：三档推进（立即问 / 暂存推进 / 阈值暂停），
  默认阈值 5；每次暂存、暂停、回答写 `ask log`，可用 `ask stats` 复盘。
- **能力边界** `docs/capability.md`：已实现 / 未实现 / **未验证** 三态，未验证不算通过。
- **冒烟记录** `scripts/smoke.py`：每模块最小路径，结果写 JSONL 可追溯。

### 变更

- **命名带版本**：包名 `@local/dsh-shiban-v0-5-0`，预设 id `ShiBan_V0_5_0`，显示「师伴 v0.5.0」。
  多版本可并存，升级不必先卸载；旧版若同名 id 冲突也不会互相覆盖。
- **数据根按版本隔离**：`$SHIBAN_ROOT/versions/v<X_Y_Z>/`。升级不破坏旧版数据。
- **素材迁移**：新增 `shiban-store migrate`（sources / run），只迁积累物，
  默认干跑、不覆盖、写 `MIGRATION.json`。**开发阶段不自动迁移。**
- **安装位置动态化**：所有路径由 `import.meta.url` / `__file__` 推导，
  新增 `shiban-store info` 查看实际位置。

- 数据根统一到 `$SHIBAN_ROOT`，工作区不再持有运行数据。
- 技能随包（`bundledSkillDir`），不再依赖会话工作区的 `.dsh/skills`。
- 教案从"候选方案"变为"一份可交付文档"，章节可单独重做。

### 移除

- 序言式自检与大量一次性验证脚本（改为 `scripts/smoke.py` 一条通路 + 日志）。
- 工作区 `data/shiban/*.json` 作为共享内存的做法。

### 已知限制

见 `docs/capability.md` 的「未验证」表。当前最需要验证的是：
Windows 启动器、Chrome 打印分支、真实 `~/.dsh` 安装、大 PDF 导入耗时。
