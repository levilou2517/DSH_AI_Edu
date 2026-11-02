# 师伴 ShiBan v0.5.0

面向**师范生与新手教师**的循证教学辅助 Agent，作为 DSH 插件分发。

装完是一个**空壳**：人格、六项原子技能、数据层就位——教材、素材与课堂证据由你自行导入或在使用中逐步积累。

```bash
dsh plugin --profile web add @levilou/dsh-shiban
```

或从本地包安装：

```bash
dsh plugin --profile web add ./shiban-0.5.0.tgz
```

---

## 它不是什么

| | |
|---|---|
| ❌ 一键生成教案的工具 | ✅ **问**出来的教案：师伴以问题引导，你决定，它记录理由 |
| ❌ 自带教材与教案 | ✅ **空包**：教材、论文、教具都由你自己导入，版权归你 |
| ❌ 替你做判断 | ✅ 每次评价并列"模型看到的"与"你说的"，分歧保留 |
| ❌ 黑箱建议 | ✅ 每条理论依据带文献编号与页码，可自行核对 |

**核心理念**：师伴的目标不是帮你完成工作，而是**引导你把工作想清楚**。
判断标准是——产物里"你做的决定"和"它替你做的判断"必须分得开。

---

## 安装

### 前置

| 项 | 要求 |
|---|---|
| DSH | ≥ 0.2.0-rc.2 |
| Node | ≥ 20 |
| Python | ≥ 3.9（依赖已随包携带，无需 pip install） |

可选：`pdftotext`（导入 PDF 教材）、Chrome/Chromium（导出 PDF 教案）。
缺了会降级，不会失败。

### 安装

```bash
dsh plugin --profile web add @levilou/dsh-shiban
```

装好后：预设「**师伴 v0.5.0**」自动出现、数据根自动建好、六项技能随包加载。

### 验证

```bash
shiban-store info      # 确认版本、安装位置、数据根
shiban-store doctor    # 环境自检
```

详见 [docs/DEPLOY.md](docs/DEPLOY.md)。

---

## 六个原子技能

| 技能 | 做什么 | 可以单独用吗 |
|---|---|---|
| `lesson-plan` | 教案设计、说课视角 | ✅ 无画像无语料也能起步（但会提问补足） |
| `quiz` | 归因型随堂测、批阅模板 | ✅ 可直接从知识点出题 |
| `class-eval` | 课后评价（真实课堂 / 微格内省） | ✅ 无学生证据时走内省模式 |
| `class-profile` | 学情画像查询与落库 | ✅ 无数据时如实说"没建立" |
| `teacher-growth` | 跨次成长回顾 | ✅ 可从零散记录起步 |
| `html-material` | 教具素材的查询、生成、编排 | ✅ 可只查库或复用 |

---

## 引导式提问

师伴不会一次性问十个问题，也不会自己闷头做完。它有三档推进：

| 档 | 触发 | 行为 |
|---|---|---|
| **A 立即问** | 关键决策（核心问题、学情卡点、支架判据） | 停下来问，强制等待 |
| **B 暂存推进** | 重要但不阻塞 | 记下问题，**继续做不依赖它的部分** |
| **C 阈值暂停** | 待答问题累计到 **5** 个 | 一次发出全部问题，必须回答才继续 |

每一次暂存、暂停、回答都留有记录：

```bash
shiban-store ask stats    # 暂停次数、暂停时平均待答数、回答率
shiban-store ask list     # 最近的问题流水
```

---

## 数据分四层

| 层 | 内容 | 位置 | 随包 | 可外传 |
|---|---|---|---|---|
| 骨架 | 人格、技能、模板、标准、代码 | 插件内 | ✅ | ✅ |
| 语料 | 教材、课标、论文 | `corpus/` | ❌ 导入 | ❌ 版权 |
| 素材 | 教具、外来 HTML | `data/assets/` | ❌ 产生 | ✅ 自愿 |
| 证据 | 课堂记录、偏好 | `data/evidence/` | ❌ | ❌ 永不出机 |

**教材是燃料，标准是尺子，模板是图纸，教案和素材是成品，证据是隐私。**

---

## 理论依据可追溯

内置 **38 项**文献/标准登记（552 页），提炼成三份可操作框架：

| 框架 | 依据 | 内容 |
|---|---|---|
| `pck-zpd.md` | 5 篇 · 123 处引用 | PCK 三轴、5 条"联系"判据、ZPD 与支架三条硬要求、18 个提问模板、22 条判定清单 |
| `evidence-levels.md` | 4 篇 · 26 处引用 | 数据→证据四层、A–D 证据级、够不够四问、微格铁律 |
| `standards-map.md` | 21 行映射 | 国家/考试标准 → 可检查项 → 判定门槛 |

```bash
shiban-store theory list
shiban-store theory search --kw 最近发展区
shiban-store theory cite --id T-BUILTIN-029 --page 7 --quote "…"
shiban-store theory audit      # 页码越界、引证超长、不可核验条目
```

> 内置的是**提炼框架与引证编号，不是论文全文**（全文有版权）。
> 你自己的文献用 `theory add` 加入 `derived/` 区，升级永不覆盖。

---

## 常用命令

```bash
# 教案
shiban-store lesson template --out lesson.json
shiban-store lesson validate --file lesson.json --check-theory
shiban-store lesson render   --file lesson.json --style competition --out-dir out/

# 语料
shiban-store corpus import --file 生物学必修2.pdf \
    --meta '{"corpus_id":"bx2","kind":"textbook","title":"生物学必修2"}' --page-offset 9
shiban-store corpus search --kw 半保留 --cite

# 素材
shiban-store asset triage --path ./网页素材/
shiban-store asset import --file demo.html --title 细胞周期动画 --category demo --stage 导入

# 产物
shiban-store artifact list --kind les
shiban-store ctx pack --for lesson-plan --kw 半保留
```

---

## 版本与数据

| 项 | 格式 |
|---|---|
| 包名 | `@levilou/dsh-shiban`（版本见 `version` 字段） |
| 预设 | `ShiBan_V0_5_0` · 显示「师伴 v0.5.0」 |
| 数据根 | `~/.shiban/versions/v0_5_0/` |

数据根按版本隔离 → 升级不破坏旧版；素材用 `shiban-store migrate` 显式继承（**只继承 v0.5.0 及以后**）。

---

## 文档

| 文件 | 内容 |
|---|---|
| [docs/DEPLOY.md](docs/DEPLOY.md) | 部署、升级、迁移、故障排查 |
| [docs/README.md](docs/README.md) | 一分钟上手与命令索引 |
| [docs/architecture.md](docs/architecture.md) | 数据流与写作规则 |
| [docs/lesson-guide.md](docs/lesson-guide.md) | 十一章节教案体例 |
| [docs/import-guide.md](docs/import-guide.md) | 导入自己的教材与论文 |
| [docs/capability.md](docs/capability.md) | **已实现 / 未实现 / 未验证**（未验证 ≠ 通过） |
| [framework/ask-protocol.md](framework/ask-protocol.md) | 提问三档协议 |

---

## 已知限制

见 [docs/capability.md](docs/capability.md)。简要说：

- Windows 启动器未在 Windows 实机验证
- Chrome 导出 PDF 的分支未触发（开发机走 Prince）
- 未在真实 `~/.dsh` 上安装验证（沙箱限制），已用副本等价验证

---

## 许可

代码 MIT。内置理论框架为原创提炼，可自由使用；
内置文献**只登记元数据，不含全文**——原文版权归原作者，请自行获取。
