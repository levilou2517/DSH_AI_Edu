# 师伴 Shiban v0.5.0

面向师范生与新手教师的**循证教学辅助 Agent**——装完是一个**空壳**：人格、六项原子技能、数据层就位；
教材、素材与课堂证据由教师自行导入或在使用中逐步积累。

## 它不是什么

- 不是"一键生成教案"的工具。教案是**问出来**的：师伴以问题引导，你决定，它记录理由。
- 不附带任何教材、论文或教案。**版权归你，内容归你**，插件只带方法和工具。
- 不替你裁决。每次评价并列"模型看到的"与"你说的"，分歧保留。

## 一分钟上手

```bash
shiban-store init      # 建数据根（默认 ~/.shiban）
shiban-store doctor    # 环境自检：python / sqlite / FTS5 / 转档工具
shiban-store version
```

在 DSH 里以 `师伴` 预设开新会话，直接说"帮我备一节《DNA的复制》"即可。

## 装成插件

```bash
dsh plugin --profile web add /path/to/V0.5.0
# 或在 Web 的插件页安装本地包
```

装好后：
- 预设 `师伴`（id `shiban`）出现在预设列表；
- 六项技能随包加载（`skill-filesystem.bundledSkillDir` 指向包内 `skills/`）；
- 数据全部写 `$SHIBAN_ROOT`，与工作区无关，换目录不丢。

## 四层数据

| 层 | 内容 | 位置 | 随包 | 可外传 |
|---|---|---|---|---|
| 骨架 | 人格、技能、模板、标准、代码 | 本包 | ✅ | ✅ |
| 语料 | 教材 / 课标 / 论文 / 教师笔记 | `$SHIBAN_ROOT/corpus/` | ❌ 导入 | ❌ 版权 |
| 素材 | 生成的教具、外来 HTML | `$SHIBAN_ROOT/data/assets/` | ❌ 产生 | ✅ 自愿 |
| 证据 | 课堂记录、微格转写、偏好 | `$SHIBAN_ROOT/data/evidence/` | ❌ | ❌ 永不出机 |

一句话：**教材是燃料，标准是尺子，模板是图纸，教案和素材是成品，证据是隐私。**

## 核心用法

```bash
# 教案：先出骨架，再填充，再校验渲染
shiban-store lesson template --out lesson.json
shiban-store lesson validate --file lesson.json
shiban-store lesson render   --file lesson.json --style competition --out-dir out/

# 语料：导入自己的教材
shiban-store corpus import --file 生物学必修2.pdf \
    --meta '{"corpus_id":"bx2","kind":"textbook","title":"生物学必修2","page_offset":9}'
shiban-store corpus search --kw 半保留

# 素材：外来 HTML 先体检再入库
shiban-store asset triage --path ./网页素材/
shiban-store asset import --file demo.html --title 细胞周期动画 \
    --category demo --stage 导入 --kp 细胞周期

# 产物：读写都经 CLI
shiban-store artifact list --kind les
shiban-store artifact get  --id les-... --view digest
shiban-store ctx pack --for lesson-plan --kw 半保留 --scope c1
```

## 进一步阅读

- [架构](architecture.md) — 数据流与写作规则
- [教案定制](lesson-guide.md) — 十一章节体例与两种风格
- [语料导入](import-guide.md) — PDF / Markdown / 论文
- [能力边界](capability.md) — 已实现 / 未实现 / **未验证**
