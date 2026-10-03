---
name: html-material
description: 教学素材原子/页面编排技能。管理可复用、可组合的 HTML 教学素材（碱基结构、细胞周期、交互练习件等）。原子是带契约数据接口的组件片段，页面是若干原子的编排组合，层级自由（同一素材可被更上层复用）。产物自包含单文件 HTML、优先零外部依赖；确需外库时经 assets/vendor 内化。先查后建：能复用不新建；编排前必询问教师预期交互。
---

## 素材归属：外部成长素材（不随师伴本体迁移）

> 原子素材（HTML/vendor）是**运行时外部成长数据**，不是师伴本体的一部分：
> - 存于 `SHIBAN_ROOT/data/assets/`（外部素材区，运行时数据根），**不随 DSH_AI_Edu/预设 部署迁移**
> - 随教学使用**不断扩增**（新原子、新 vendor 库按需加入），跨会话/跨工作区继承
> - 不得写进师伴本体仓（`材料/模版/`、`DSH_AI_Edu` 源码）——那些随本体迁移的应是"教案模板/文档"，不是运行时原子
> - vendor 依赖库（如 smiles-drawer）内化在 `data/assets/vendor/<lib>@<v>/`，相对引用、不 runtime 外链

## 数据层入口

一律走 CLI 或素材服务 Tool，不直接编辑文件：
```
bin/shiban-store asset list [--kind html] [--kp <知识点>]   # 查库存(先查后建)
bin/shiban-store asset get  --id <aid>                        # 拿 file_path/assembly/interface
bin/shiban-store asset add  --id <aid> --kind html --title <t> --file <html> \
    --kp <点> [--parent <宿主页>] [--assembly '<json>'] [--params '<界面schema json>']
bin/shiban-store asset reuse --id <aid>
bin/shiban-store asset suggest [--kp <点>] [--kind html]   # 编排第一步：只读查库存+契约+建议
bin/shiban-store asset compose --spec '<json>'             # 装配编排页（契约校验+内联装配+入库）
bin/shiban-store asset compose --spec-schema               # 查 compose 输入契约（单一真源）
```
宿主数据服务 Tool（若已挂载）等价且更原生，直接调用即可（与 CLI 共用同一 store）：
```
shiban_asset_list   按知识点/类型/学科查素材（先查后建第一步）
shiban_asset_get    取素材详情（file_path / interface / assembly / reuse_count）
shiban_asset_add    登记素材（自动查重；interface_schema 声明输入契约）
shiban_asset_reuse  复用记账（reuse_count +1）
shiban_asset_scan   扫现存产物统一索引（dry_run 预览）
shiban_asset_suggest  编排第一步：按知识点查库存（html 原子附 interface 契约）+ 建议编排方式
shiban_asset_compose  编排装配：校验喂数→内联装配→落盘入库（编排即复用：原子 reuse+1、parent 指回）
shiban_raw_list / shiban_raw_read / shiban_raw_save   原始证据（L0，只追加）
```
（`asset add` 会把源 HTML 拷入 `data/assets/<aid>/` 并登记；vendor 依赖放 `data/assets/vendor/`。）

## 素材层次（一表多用，无固定层级）

- **路径契约**：素材主文件固定 `data/assets/<id>/main.html`（`add`/`compose` 落盘均用固定主文件名，不随源文件名漂移）。
- **原子组件**：`data/assets/<atom>/main.html`，自包含、声明输入 schema。
- **编排页面**：`data/assets/<page>/main.html`，由 `asset compose` 引用若干原子装配；也可复用原子（先查后建）而非重写。
- **自由层级**：同一素材当页面或当组件均可——被更上层 `parent_asset` 引用即降为组件。

## 原子组件数据接口（契约 schema）

每个原子在入库时用 `params.interface` 声明它接受的输入字段（JSON Schema 片段）。
页面/`window.__MATERIAL_DATA` 按该 schema 喂数。缺省值原子内部兜底。
示例（碱基结构式）：`{"interface":{"base":{"enum":["A","C","G","T","U"]},"label":{},"showCaption":{}}}`

## 编排工作流（suggest → 询问 → compose）

1. **先查后建**：请求某知识点素材 → `asset suggest`（或 `asset list`）→ 命中（含同用途）复用并 `reuse`，未命中才新建原子。
2. **编排前询问（必经）**：把 `suggest` 返回的原子清单 + 建议编排方式转述教师，用 ask_user 确认预期交互/效果（布局 stack/grid、每节喂什么数据）——**未经确认不得 compose**。
3. **装配**：`asset compose --spec`（spec 契约用 `--spec-schema` 查）。装配器自动完成：
   - 按各原子 `interface` 校验喂数（enum/type/required；违规即报错不产出）；
   - 作用域隔离（样式加 `#shiban-sec-N` 前缀、脚本 IIFE 化、DOM id 实例改名——同一原子可多处复用互不污染）；
   - 数据注入（各节脚本前置 `window.__MATERIAL_DATA`，与原子读取约定一致）；
   - 落盘 `data/assets/<page_id>/main.html`（自包含单文件、零外链零 iframe）+ 查重 + 0 字节校验。
4. **编排簿记（自动）**：各引用原子 `reuse_count+1`（编排即复用）、`parent_asset` 指回本页（已有父层不覆盖——层级自由而非单亲）；页面 `assembly` 记引用清单与每处喂数。
5. **vendor 边界**：compose 产物零外链；外库内化发生在**原子侧**（生成原子时把库内容内联进自身 main.html），不在装配期拼 `<script src>`。

spec 最小示例：
```json
{"page_id":"dna-base-demo","title":"碱基结构对比","knowledge_point":"核酸-碱基",
 "layout":{"mode":"grid","gap":24},
 "sections":[{"asset":"base-structure","label":"腺嘌呤 A","data":{"base":"A"}},
             {"asset":"base-structure","label":"胸腺嘧啶 T","data":{"base":"T"}}]}
```

## 产物约束

- 单文件自包含 HTML，内联 CSS/JS，零外链。
- 特殊符号（化学式/环状结构）优先原生 SVG；确需外库才经 assets/vendor 内化（不 runtime 外链）。
- 5 碱基数据类原子：单 HTML 靠 `window.__MATERIAL_DATA` 数据驱动多态，不每碱基一份文件。

## 与其它技能的组合

- `lesson-plan`/`quiz` 需教具时 → 调本技能取/建 HTML 素材。
- 素材复用 `reuse_count` 回流 → 供 `class-profile` 统计哪些素材有效。