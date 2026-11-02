# 能力边界：已实现 / 未实现 / 未验证

> 这份文件的规则：**未验证 ≠ 通过**。凡是没在隔离环境里真跑过一遍的，一律标 `unverified`。

生成时间：v0.5.0 首版

## ✅ 已实现（有冒烟记录）

| 能力 | 入口 | 验证方式 |
|---|---|---|
| 数据根初始化与自检 | `shiban-store init` / `doctor` | `scripts/smoke.py` |
| 产物读写（原子写 + 引用图 + 乐观锁） | `artifact put/get/list/confirm/discard/archive/stale` | 模块自检 |
| 图传播（上游变更 → 下游 stale） | `artifact stale` | 自检断言 |
| 原始证据只追加 | `evidence save/list/read` | 自检断言（重名拒绝） |
| 上下文包 | `ctx pack --for <原子>` | 六份配方 |
| 教案骨架 / 校验 / 渲染 | `lesson template/validate/render` | 端到端出 A4 PDF |
| 语料导入与检索 | `corpus import/search/read/verify` | 模块自检 |
| 素材导入体检与编排 | `asset triage/import/compose/suggest` | 模块自检 |
| 插件装载 | `dsh plugin add <本包>` | 临时 DSH_HOME 副本 `--dump-config` 命中 `preset-shiban` |
| 技能随包 | `skill-filesystem.bundledSkillDir` | `!!js` 表达式解析验证指向 `skills/` |

## ⛔ 未实现（设计已定，代码未写）

| 能力 | 现状 | 何时补 |
|---|---|---|
| `asset pack` / `.shiban-pkg` 导出导入 | 未写 | 需要跨机迁移时 |
| 素材模板机制（`templates/<kind>/`） | 目录预留，未实现填充 | R5.1 |
| 语料页内表格/图注的结构化抽取 | 目前按启发式分块 | 视导入质量再定 |
| v0.4.3 → v0.5.0 数据迁移 | 未写 | 有人要从旧版升级时 |
| 素材复用度统计 | 未写 | R5.3 |

## ⚠️ 未验证（代码在，但没在目标环境真跑过）

| 项 | 风险 | 怎么验 |
|---|---|---|
| Windows 启动器 `shiban-store.cmd` | 未在 Windows 上执行过 | 在 Windows 机器跑 `shiban-store version` |
| Chrome/Chromium `--print-to-pdf` 路径 | 本机走向了 Prince，chrome 分支未触发 | 去掉 PATH 里的 prince 再渲染 |
| 无 Prince/无浏览器时的 `skipped` 报告 | 逻辑写了，未实测 | 遮蔽 PATH 后渲染 |
| `~/.dsh` 真实安装 | 沙箱写不了 `~/.dsh`，只在副本验证 | 你在终端执行 `dsh plugin add` |
| 大文件 PDF 导入 | 自检用的是小 md | 用 20 MB 教材实测耗时与内存 |
| 中文 PDF 双栏错行 | `pdftotext -layout` 已知局限 | 用双栏论文实测 `low_quality_pages` 是否报出 |

## 明确的非目标

- 不做向量检索（坚持 FTS5，保证索引可重建）。
- 不做多租户、权限体系。
- 不做音频采集与转写（输入仍是文本）。
- 不在运行时渲染 Mermaid（板书用 CSS/ASCII 框图）。
