---
name: html-material
description: 教学素材原子/页面编排技能。管理可复用、可组合的 HTML 教学素材（碱基结构、细胞周期、交互练习件等）。原子是带契约数据接口的组件片段，页面是若干原子的编排组合，层级自由（同一素材可被更上层复用）。产物自包含单文件 HTML、优先零外部依赖；确需外库时经 assets/vendor 内化。先查后建：能复用不新建；编排前必询问教师预期交互。
---

## 数据层入口

一律走 CLI 或素材服务 Tool，不直接编辑文件：
```
bin/shiban-store asset list [--kind html] [--kp <知识点>]   # 查库存(先查后建)
bin/shiban-store asset get  --id <aid>                        # 拿 file_path/assembly/interface
bin/shiban-store asset add  --id <aid> --kind html --title <t> --file <html> \
    --kp <点> [--parent <宿主页>] [--assembly '<json>'] [--params '<界面schema json>']
bin/shiban-store asset reuse --id <aid>
```
宿主数据服务 Tool（若已挂载）等价，能力更原生：`shiban_asset_list` 等。

## 素材层次（一表多用，无固定层级）

- **原子组件**：`assets/<atom>/*.html`，自包含、声明输入 schema。
- **编排页面**：`assets/<page>/*.html`，引用若干原子 + 喂数据；prod 也可复用原子（先查后建）而非重写。
- **自由层级**：同一素材当页面或当组件均可——被更上层 `parent_asset` 引用即降为组件。

## 原子组件数据接口（契约 schema）

每个原子在入库时用 `params.interface` 声明它接受的输入字段（JSON Schema 片段）。
页面/`window.__MATERIAL_DATA` 按该 schema 喂数。缺省值原子内部兜底。
示例（碱基结构式）：`{"interface":{"base":{"enum":["A","C","G","T","U"]},"label":{},"showCaption":{}}}`

## 组成：

- **先查后建**：请求某知识点素材 → 先 `asset list` → 命中（含同用途）复用并 `reuse`，未命中才新建原子。
- **编排前询问**：产出的编排方案（建议引用哪些原子 + 期望交互/效果）先用 `asset_suggest`/对话呈现，经教师确认后再建页面。
- **编排记录**：页面入库时 `--assembly` JSON 记引用子组件与每处喂数；`--parent` 记它是谁的子层。

## 产物约束

- 单文件自包含 HTML，内联 CSS/JS，零外链。
- 特殊符号（化学式/环状结构）优先原生 SVG；确需外库才经 assets/vendor 内化（不 runtime 外链）。
- 5 碱基数据类原子：单 HTML 靠 `window.__MATERIAL_DATA` 数据驱动多态，不每碱基一份文件。

## 与其它技能的组合

- `lesson-plan`/`quiz` 需教具时 → 调本技能取/建 HTML 素材。
- 素材复用 `reuse_count` 回流 → 供 `class-profile` 统计哪些素材有效。