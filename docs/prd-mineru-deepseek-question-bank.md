# 数学试卷 PDF 题库结构化系统 PRD

## 1. 背景

项目目标是将几千份数学试卷 PDF 批量转换为可运营的结构化题库数据。原始 PDF 可能包含电子文本、扫描图片、数学公式、几何图、函数图、表格、选择题、填空题、解答题、答案与解析等内容。

系统不以“把 PDF 转成 Markdown”为最终目标，而是以接近成熟教培题库的生产质量为目标：题目可检索、可组卷、可渲染、可追溯、可质检、可人工修订，并支持后续知识点标注、难度标注、去重归并和持续纠错。

## 2. 目标

### 2.1 产品目标

- 批量导入数学试卷 PDF，并自动拆分为独立题目。
- 将题干、选项、答案、解析转换为结构化 LaTeX/Markdown 数据。
- 正确保留并归属题目中的图片、几何图、函数图、表格等资源。
- 使用 DeepSeek 完成题目结构化、字段规范化、异常检查、知识点初标和难度初标。
- 建立自动质检与人工审核闭环，使关键字段达到题库可用标准。
- 支持后续检索、组卷、题目复用、相似题去重和题库运营。

### 2.2 质量目标

- 题目切分准确率：MVP 阶段 >= 95%，生产阶段目标 >= 99%。
- 题干与选项结构化准确率：MVP 阶段 >= 90%，生产阶段目标 >= 98%。
- 数学公式 LaTeX 可渲染率：MVP 阶段 >= 92%，生产阶段目标 >= 98%。
- 图片归属准确率：MVP 阶段 >= 90%，生产阶段目标 >= 98%。
- 答案命中率：选择题答案必须命中选项，生产阶段目标 >= 99%。
- 低置信题进入人工审核队列，不允许直接进入正式题库。

## 3. 非目标

- 不追求第一阶段完全无人干预。
- 不将复杂图形强行转成 LaTeX 或 SVG，图片类资源优先以裁剪图方式存储。
- 不在 MVP 阶段实现完整自适应学习、学生画像、推荐系统。
- 不在 MVP 阶段覆盖所有学科，优先聚焦数学试卷。
- 不在 MVP 阶段构建完整教研内容生产平台，先完成题库结构化生产线。

## 4. 用户与场景

### 4.1 主要用户

- 内容运营人员：批量导入试卷、查看处理状态、处理异常题。
- 教研人员：审核题目质量、修正题干/答案/解析、标注知识点和难度。
- 系统管理员：管理任务队列、模型配置、质检规则和数据版本。
- 后续业务系统：搜索题目、组卷、推荐相似题、展示题目详情。

### 4.2 核心场景

1. 用户上传一批数学试卷 PDF。
2. 系统自动解析 PDF，并拆分为题目。
3. 系统将每道题结构化为题干、选项、答案、解析、图片、页码、坐标等字段。
4. 系统运行自动质检，将高置信题入库，将低置信题送入审核台。
5. 审核人员在原 PDF 截图和结构化结果之间对照修订。
6. 审核通过后，题目进入正式题库。
7. 系统对新题进行去重、知识点标注、难度标注和版本追踪。

## 5. 总体方案

系统采用“MinerU 主解析 + DeepSeek 结构化 + 自动质检 + 人工审核 + 数据追溯”的架构。

```text
PDF 文件
 -> 文件入库与任务创建
 -> PDF 类型判断：电子 PDF / 扫描 PDF / 混合 PDF
 -> MinerU 解析：Markdown、JSON、公式、图片、版面坐标
 -> 题目切分：题号规则 + 版面坐标 + DeepSeek 辅助
 -> 题目结构化：DeepSeek 输出标准 JSON
 -> 资源归属：图片/表格/图形绑定到题目
 -> 自动质检：规则校验 + DeepSeek 语义校验 + LaTeX 渲染校验
 -> 低置信题人工审核
 -> 正式题库入库
 -> 去重、知识点、难度、版本追踪
```

## 6. 功能需求

### 6.1 PDF 导入

- 支持单文件上传和批量上传。
- 支持 PDF 文件元信息录入：学段、年级、教材版本、地区、考试类型、年份、来源。
- 支持任务状态查看：待处理、解析中、结构化中、质检中、待审核、已入库、失败。
- 支持失败任务重试。
- 支持保留原始 PDF，不覆盖、不丢弃。

### 6.2 PDF 类型识别

系统需要自动判断 PDF 类型：

- 电子 PDF：优先走原生文本抽取和 MinerU 版面解析。
- 扫描 PDF：启用 OCR 与公式识别。
- 混合 PDF：按页判断处理策略。

输出字段：

- `pdf_type`: `digital` / `scanned` / `mixed`
- `page_type`: 每页类型
- `text_extractable`: 是否可直接抽取文本
- `ocr_required`: 是否需要 OCR

### 6.3 MinerU 解析

MinerU 作为主解析引擎，负责：

- PDF 页面解析。
- 版面区域检测。
- 文本、公式、表格、图片提取。
- 公式转 LaTeX。
- 输出 Markdown、JSON、图片文件、bbox 坐标。

配置要求：

- 支持按任务配置 OCR 开关。
- 支持公式识别开关。
- 支持不同解析模式配置，例如文本优先、OCR 优先、混合模式。
- 保存 MinerU 原始输出，便于回溯与重跑。

### 6.4 题目切分

系统需要将整份试卷拆分为题目级别的结构。

切分依据：

- 题号模式：`1.`、`1、`、`（1）`、`第1题`、`一、选择题` 等。
- 大题标题：选择题、填空题、解答题、证明题、应用题。
- 页面和栏位坐标。
- 答案区、解析区、正文区分离。
- 跨页连续题识别。

题目切分输出：

```json
{
  "question_block_id": "qb_001",
  "paper_id": "paper_001",
  "question_number": "5",
  "section_title": "选择题",
  "pages": [2],
  "bbox": [52, 108, 540, 356],
  "raw_markdown": "...",
  "assets": [],
  "split_confidence": 0.97,
  "needs_review": false
}
```

### 6.5 DeepSeek 结构化

DeepSeek 用于将题目块转换为标准题库 JSON。系统需要封装 DeepSeek 调用层，避免业务代码直接依赖某个具体模型名称。

DeepSeek 主要职责：

- 识别题型。
- 规范化题干、选项、答案、解析。
- 清理 OCR 噪声。
- 将数学表达式整理为 LaTeX。
- 判断图片是否属于该题。
- 初步标注知识点。
- 初步标注难度。
- 输出结构化 JSON。
- 对异常题给出原因和修复建议。

DeepSeek 不负责：

- 直接读取原始 PDF。
- 替代 MinerU 完成大规模 OCR。
- 对所有题目做最终人工级审核。
- 凭空补全原卷中不存在的题干、答案或解析。

结构化输出示例：

```json
{
  "question_type": "single_choice",
  "stem_latex": "已知函数 $y=2x+1$，当 $x=3$ 时，$y$ 的值为（ ）",
  "choices": [
    {"label": "A", "content_latex": "$5$"},
    {"label": "B", "content_latex": "$6$"},
    {"label": "C", "content_latex": "$7$"},
    {"label": "D", "content_latex": "$8$"}
  ],
  "answer_latex": "C",
  "analysis_latex": "将 $x=3$ 代入 $y=2x+1$，得 $y=2\\times3+1=7$。",
  "knowledge_points": ["一次函数", "代入求值"],
  "difficulty": 1,
  "confidence": {
    "structure": 0.98,
    "latex": 0.96,
    "answer": 0.99,
    "knowledge": 0.82
  },
  "warnings": []
}
```

### 6.6 图片与资源管理

题目中的图片、图形、表格等资源需要单独保存，并在题目中引用。

资源类型：

- `image`: 普通图片。
- `geometry`: 几何图。
- `chart`: 函数图、统计图。
- `table`: 表格截图或结构化表格。
- `formula_image`: 公式图片，必要时保留原图用于回溯。

资源字段：

```json
{
  "asset_id": "asset_001",
  "question_id": "q_001",
  "type": "geometry",
  "storage_url": "s3://question-bank-assets/paper_001/q_001_fig_1.png",
  "page": 2,
  "bbox": [100, 230, 420, 520],
  "caption": "",
  "confidence": 0.94
}
```

### 6.7 自动质检

自动质检由规则校验、渲染校验和 DeepSeek 语义校验组成。

规则校验：

- 选择题必须存在选项。
- 选择题答案必须命中选项。
- 填空题答案不能为空。
- 解答题解析不能为空，除非原卷无解析。
- 题干不能为空。
- 题号不能重复或异常跳跃。
- 出现“如图”“下图”“图中”时，题目必须有关联图片。
- 有图片但未归属任何题目时，需要进入审核队列。
- LaTeX 括号、美元符号、环境标记需要基本闭合。

渲染校验：

- 使用 KaTeX 或 MathJax 对题干、选项、答案、解析进行渲染检查。
- 渲染失败的字段需要记录错误并进入审核队列。

DeepSeek 语义校验：

- 判断题干、选项、答案、解析是否疑似混杂。
- 判断答案是否和解析推导一致。
- 判断题型是否合理。
- 判断知识点标注是否明显偏离。
- 给出异常原因。

### 6.8 人工审核台

人工审核台是题库级质量的关键模块。

页面布局：

- 左侧：原 PDF 页面截图或题目裁剪图。
- 右侧：结构化字段编辑区。
- 底部：质检错误、模型警告、版本记录。

核心能力：

- 编辑题干 LaTeX。
- 编辑选项。
- 编辑答案。
- 编辑解析。
- 编辑知识点和难度。
- 查看并调整图片归属。
- 合并被错误拆开的题。
- 拆分被错误合并的题。
- 标记废题、重复题、缺答案题。
- 一键通过、一键退回。

审核状态：

- `pending_review`: 待审核。
- `approved`: 审核通过。
- `rejected`: 审核驳回。
- `needs_reparse`: 需要重新解析。
- `discarded`: 废弃。

### 6.9 知识点标注

系统需要维护数学知识点树。

第一阶段支持：

- 手动导入知识点树。
- DeepSeek 初步标注 1-3 个知识点。
- 人工审核修正。

后续阶段支持：

- 基于相似题召回辅助标注。
- 基于教材章节自动推荐。
- 统计每个知识点下题目数量和质量。

### 6.10 难度标注

难度采用 1-5 档：

- 1：基础概念或直接计算。
- 2：常规题，单一知识点。
- 3：中等题，需要 2-3 步推理。
- 4：较难题，综合多个知识点。
- 5：压轴题或竞赛风格题。

DeepSeek 负责初标，人工可以修正。后续可接入学生作答正确率进行校准。

### 6.11 去重与相似题

系统需要识别重复题和高度相似题。

MVP 阶段：

- 基于题干规范化文本 hash。
- 基于题干 embedding 召回相似题。
- 人工确认重复关系。

生产阶段：

- 支持题目母题、变式题、同源题关系。
- 支持重复题合并。
- 支持保留多个来源记录。

## 7. 数据模型

### 7.1 papers

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | string | 试卷 ID |
| title | string | 试卷标题 |
| subject | string | 学科 |
| grade | string | 年级 |
| source | string | 来源 |
| pdf_url | string | 原始 PDF 地址 |
| pdf_type | string | PDF 类型 |
| status | string | 处理状态 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

### 7.2 parse_runs

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | string | 解析任务 ID |
| paper_id | string | 试卷 ID |
| engine | string | 解析引擎，例如 MinerU |
| engine_version | string | 引擎版本 |
| config_json | json | 解析配置 |
| raw_output_url | string | 原始输出地址 |
| status | string | 状态 |
| error_message | text | 错误信息 |
| created_at | datetime | 创建时间 |

### 7.3 question_blocks

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | string | 题块 ID |
| paper_id | string | 试卷 ID |
| parse_run_id | string | 解析任务 ID |
| question_number | string | 原始题号 |
| section_title | string | 大题标题 |
| raw_markdown | text | 原始题块 Markdown |
| pages | json | 页码列表 |
| bbox_json | json | 坐标 |
| split_confidence | float | 切分置信度 |
| needs_review | boolean | 是否需要审核 |

### 7.4 questions

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | string | 题目 ID |
| question_block_id | string | 题块 ID |
| subject | string | 学科 |
| grade | string | 年级 |
| question_type | string | 题型 |
| stem_latex | text | 题干 |
| answer_latex | text | 答案 |
| analysis_latex | text | 解析 |
| difficulty | int | 难度 1-5 |
| quality_status | string | 质量状态 |
| review_status | string | 审核状态 |
| source_location_json | json | 来源位置 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

### 7.5 choices

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | string | 选项 ID |
| question_id | string | 题目 ID |
| label | string | A/B/C/D |
| content_latex | text | 选项内容 |
| sort_order | int | 排序 |

### 7.6 question_assets

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | string | 资源 ID |
| question_id | string | 题目 ID |
| type | string | 资源类型 |
| storage_url | string | 存储地址 |
| page | int | 来源页 |
| bbox_json | json | 坐标 |
| confidence | float | 归属置信度 |

### 7.7 quality_reports

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | string | 质检报告 ID |
| question_id | string | 题目 ID |
| rule_errors | json | 规则错误 |
| render_errors | json | 渲染错误 |
| model_warnings | json | 模型警告 |
| overall_score | float | 综合质量分 |
| needs_review | boolean | 是否需要审核 |

## 8. DeepSeek 调用设计

### 8.1 模型适配层

系统需要建立统一 LLM Adapter：

```text
DeepSeekClient
 -> structure_question()
 -> validate_question()
 -> tag_knowledge_points()
 -> estimate_difficulty()
 -> repair_latex()
```

模型名称、温度、最大 token、超时时间、重试次数需要配置化。

### 8.2 Prompt 原则

- 输入必须包含原始题块 Markdown、图片占位符、页码、bbox、题号上下文。
- 输出必须是 JSON。
- 不允许模型编造原文不存在的信息。
- 无法判断时必须返回 `needs_review=true`。
- 对每个低置信字段返回原因。
- 知识点和难度只作为初标，不作为最终审核结果。

### 8.3 调用策略

- 高质量规则题：只调用一次结构化。
- 复杂图文题：结构化 + 语义质检。
- 低置信公式题：调用 LaTeX 修复或转人工审核。
- 大批量任务：异步队列限流，记录调用成本和耗时。
- DeepSeek 失败时：自动重试，仍失败则进入人工队列。

## 9. 系统架构

推荐技术架构：

```text
Frontend Admin
 -> API Server
 -> Task Queue
 -> PDF Storage
 -> MinerU Worker
 -> DeepSeek Worker
 -> Quality Worker
 -> PostgreSQL
 -> Object Storage
 -> Vector Store
```

建议组件：

- 后端：Python FastAPI。
- 任务队列：Celery/RQ + Redis。
- 数据库：PostgreSQL。
- 对象存储：MinIO/S3。
- 向量库：pgvector 或 Milvus。
- 前端审核台：React/Vue。
- 数学渲染：KaTeX 或 MathJax。
- PDF 展示：PDF.js。
- 解析引擎：MinerU。
- LLM：DeepSeek。

## 10. 权限与操作日志

- 支持管理员、运营、教研审核员三类角色。
- 所有人工修改必须记录操作人、修改前、修改后、时间。
- 题目支持版本号。
- 支持回滚到历史版本。
- 支持查看某道题的原始 PDF、MinerU 输出、DeepSeek 输出和人工修改记录。

## 11. 指标与看板

系统需要提供以下指标：

- PDF 总数。
- 总页数。
- 总题数。
- 平均每份试卷处理耗时。
- MinerU 解析成功率。
- DeepSeek 结构化成功率。
- 自动通过率。
- 人工审核率。
- 质检失败原因分布。
- 公式渲染失败率。
- 图片未归属数量。
- 重复题数量。
- 每千题 DeepSeek 调用成本。

## 12. MVP 范围

MVP 聚焦“可批量生产、可审核、可入库”的最小闭环。

必须包含：

- PDF 批量导入。
- MinerU 解析。
- 题目切分。
- DeepSeek 结构化。
- 图片资源保存与归属。
- PostgreSQL 入库。
- 自动质检。
- 简单人工审核台。
- LaTeX 渲染检查。
- 基础知识点和难度初标。
- 处理日志与失败重试。

暂不包含：

- 学生端应用。
- 自动组卷系统。
- 复杂推荐系统。
- 完整教研工作流。
- 多学科扩展。
- 基于作答数据的难度校准。

## 13. 里程碑

### 阶段 1：样本验证

周期：1-2 周。

目标：

- 选取 100 份数学试卷作为样本。
- 跑通 MinerU 解析。
- 初步完成题目切分。
- 手工评估切题、公式、图片归属、答案解析分离质量。

交付：

- 样本评估报告。
- 解析质量指标。
- 主要错误类型清单。
- DeepSeek prompt 初版。

### 阶段 2：MVP 生产线

周期：3-5 周。

目标：

- 完成批处理队列。
- 完成结构化入库。
- 完成自动质检。
- 完成简单审核台。

交付：

- 可运行的批量处理系统。
- 数据库表结构。
- 审核后台。
- 质量看板初版。

### 阶段 3：质量增强

周期：3-6 周。

目标：

- 优化跨页题、多栏题、复杂图文题。
- 建立知识点体系。
- 引入相似题去重。
- 提升自动通过率。

交付：

- 知识点标注能力。
- 相似题检测能力。
- 更完整的人工审核流程。
- 质量评估报告。

### 阶段 4：题库运营

周期：持续迭代。

目标：

- 支持正式题库管理。
- 支持题目版本、来源、重复关系。
- 支持对外检索和组卷接口。

交付：

- 题库管理后台。
- 题目检索 API。
- 组卷 API 基础能力。

## 14. 验收标准

MVP 验收标准：

- 能成功导入不少于 100 份数学试卷 PDF。
- 能自动产出题目级结构化 JSON。
- 能保存题目相关图片并正确引用。
- 能将题目、选项、答案、解析、图片、来源位置写入数据库。
- 能展示待审核题并支持人工修订。
- 能对 LaTeX 渲染失败、答案异常、图片缺失等问题进行标记。
- 能输出批量处理质量报告。

生产级验收标准：

- 题目切分准确率 >= 99%。
- 选择题选项和答案结构化准确率 >= 99%。
- 图片归属准确率 >= 98%。
- LaTeX 可渲染率 >= 98%。
- 每道正式题都可追溯到原始 PDF、页码、bbox、解析版本和审核记录。
- 低置信题不会直接进入正式题库。

## 15. 风险与应对

### 15.1 MinerU 对复杂版面识别不稳定

应对：

- 建立版面异常检测。
- 对跨页题、多栏题进入人工审核。
- 关键样本建立 benchmark，持续比较解析配置。

### 15.2 DeepSeek 可能输出不稳定 JSON

应对：

- 使用严格 JSON schema。
- 增加输出解析和重试。
- 失败任务进入人工审核。
- 对 prompt 和模型参数做版本管理。

### 15.3 模型可能编造答案或解析

应对：

- Prompt 中明确禁止补全原文不存在内容。
- 对缺答案题标记 `answer_missing`。
- 保留原始题块供审核对照。
- 语义校验只作为辅助，不自动覆盖原始内容。

### 15.4 人工审核成本过高

应对：

- 优先审核低置信题。
- 建立错误类型统计，针对性优化规则。
- 提供快捷键和对照视图。
- 对高频版式建立模板化规则。

### 15.5 版权与来源风险

应对：

- 保存来源信息。
- 标记授权状态。
- 支持按来源删除或下架题目。
- 对外使用前进行版权合规审查。

## 16. 后续扩展

- 支持物理、化学等理科试卷。
- 支持自动生成题目标签。
- 支持母题和变式题体系。
- 支持基于学生作答数据的难度校准。
- 支持自动组卷。
- 支持题目讲解生成。
- 支持拍照搜题和相似题推荐。

