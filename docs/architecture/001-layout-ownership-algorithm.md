# ADR 001: Layout Ownership Algorithm v1

## Goal

Convert MinerU page-level layout elements into question-level ownership:

```text
MinerU elements -> question blocks -> owned text/formula/assets -> warnings
```

This module is deterministic. It must not call DeepSeek.

## Input Contract

Each element must be normalized before ownership:

```json
{
  "id": "e_001",
  "page": 1,
  "type": "text",
  "bbox": [0.08, 0.12, 0.44, 0.16],
  "text": "1. 已知 $x+1=2$，求 $x$。",
  "confidence": 0.98
}
```

Allowed `type`:

```text
text | formula | image | table | figure | line | header | footer
```

Bbox convention:

```text
[x1, y1, x2, y2]
origin = top-left
coordinates normalized to [0,1] per page
```

Invalid element:

```text
x2 <= x1
y2 <= y1
page missing
type missing
```

Invalid elements are dropped and recorded as `invalid_layout_element`.

## Output Contract

```json
{
  "question_block_id": "paper_001_qb_0001",
  "question_number": "1",
  "section_title": "一、选择题",
  "pages": [1],
  "column_index": 0,
  "text_bbox": [0.08, 0.12, 0.46, 0.29],
  "question_bbox": [0.08, 0.12, 0.55, 0.40],
  "element_ids": ["e_001", "e_002", "e_003"],
  "assets": [
    {
      "asset_id": "img_001",
      "score": 0.78,
      "reasons": ["same_page", "same_column", "visual_cue", "vertical_near"],
      "needs_review": false
    }
  ],
  "warnings": []
}
```

## Preprocessing

Drop noise before question detection:

```text
height < 0.006 and width < 0.01
y2 < 0.04
y1 > 0.96
```

Repeated header/footer candidate:

```text
same normalized text appears on >= 3 pages
and y2 < 0.08 or y1 > 0.92
```

Repeated candidates are excluded from reading order but preserved for traceability.

## Column Detection

Run per page.

Use non-asset text/formula elements:

```text
eligible = type in text/formula and width < 0.75
x_center = (x1 + x2) / 2
```

Column split heuristic:

```text
sort eligible by x_center
gaps = adjacent x_center gaps
major_gap = max(gaps)
if major_gap < 0.18 -> one column
else split at gaps >= 0.18
```

Column bbox:

```text
column.x1 = min element.x1 in cluster
column.x2 = max element.x2 in cluster
column.y1 = 0
column.y2 = 1
```

Element column assignment:

```text
column = argmax horizontal_overlap(element.bbox, column.bbox)
```

Full-width section/header:

```text
width > 0.65
and text matches section pattern
=> applies to all columns below until next section
```

Reading order:

```text
page asc
column_index asc
y1 asc
x1 asc
```

Do not sort by `page, y, x` globally. That breaks two-column papers.

## Section Detection

Section regex:

```regex
^[一二三四五六七八九十]+[、.．]\s*(选择|填空|解答|计算|证明|应用|综合|压轴).*
```

Answer section regex:

```regex
^(参考答案|答案|解析|答案与解析|试卷答案|详解)\s*$
```

Section state:

```text
current_section = latest section before question anchor
answer_section stops body ownership
```

## Question Anchor Detection

Question number regex:

```regex
^\s*(?:第\s*)?([0-9]{1,3})(?:\s*题)?[\.．、)]\s*
```

Chinese number regex:

```regex
^\s*[（(]?([一二三四五六七八九十]{1,4})[）)、.．]\s*
```

Option label exclusion:

```regex
^\s*[A-H][\.．、:：]\s+
```

Anchor acceptance:

```text
regex_match
and not option_label
and element.type in text/formula
and element.x1 <= column.x1 + 0.12
and (
  text_after_marker not empty
  or next element vertical_gap <= 0.035
)
```

Reject if:

```text
inside answer section
header/footer candidate
same text repeated across pages
```

## Block Boundary

For each question anchor:

```text
start = anchor_i
end = nearest of:
  next question anchor in same page+column
  next section anchor
  answer section anchor
  page end
```

Cross-page continuation:

```text
if no next anchor before page end:
  continue to next page same column
  until next question/section/answer anchor
```

Hard stop:

```text
max_pages_per_question = 3
if exceeded -> question_spans_too_many_pages
```

## Text Ownership

Text/formula ownership:

```text
reading_order(anchor_i) <= reading_order(element) < reading_order(anchor_{i+1})
```

Only include:

```text
type in text/formula
not section
not header/footer
not answer section
```

## Asset Ownership

Asset candidates:

```text
type in image/table/figure
```

Visual cue regex:

```regex
(如图|下图|图中|图示|函数图像|坐标系|表格|统计图|几何图)
```

Score per candidate question:

```text
same_page_score = 1 if asset.page in question.pages else 0
vertical_score = y_overlap(asset.bbox, question.text_bbox expanded by 0.04)
column_score = horizontal_overlap(asset.bbox, question.column_bbox)
distance_score = exp(-vertical_gap(asset.bbox, question.text_bbox) / 0.08)
cue_score = 1 if question text has visual cue else 0

score =
  0.35 * same_page_score +
  0.25 * vertical_score +
  0.20 * column_score +
  0.15 * distance_score +
  0.05 * cue_score
```

Assignment:

```text
score >= 0.62 -> assign
0.45 <= score < 0.62 -> assign + needs_review
score < 0.45 -> unassigned
```

Conflict:

```text
top2_score_gap < 0.12 -> asset_assignment_conflict
```

Cross-column asset exception:

```text
asset.width > 0.55
and y_overlap(asset, question.text_bbox expanded by 0.06) > 0
=> allow cross-column assignment
```

## Bbox Calculation

Use two bbox layers:

```text
text_bbox = union(text/formula/choice elements)
asset_bbox = union(confident assigned assets)
question_bbox = union(text_bbox, asset_bbox)
```

Asset scoring must use `text_bbox`, not `question_bbox`, to avoid self-contamination.

## Warning Codes

```text
invalid_layout_element
duplicate_question_number
question_without_text
cross_column_question
question_spans_too_many_pages
answer_section_mixed_into_body
missing_referenced_image
unassigned_visual_asset
asset_assignment_conflict
low_confidence_asset_assignment
orphan_formula
```

## Required Fixtures

Create fixtures under `docs/test-fixtures/`:

```text
layout-case-two-columns.json
layout-case-image-nearby.json
layout-case-cross-page.json
layout-case-answer-section.json
layout-case-cross-column-image.json
```

Each fixture must include:

```json
{
  "name": "two column choice questions",
  "elements": [],
  "expected": {
    "question_count": 4,
    "asset_assignments": {},
    "warnings": []
  }
}
```

## Known Blind Spots

1. Handwritten annotations can look like figures and must be low confidence.
2. Geometry diagrams between two questions may score close for both; require review.
3. Full-width images in two-column layout are ambiguous without visual cue.
4. OCR may merge `1.` and previous line; anchor detection must expose `missing_anchor_suspected`.
5. Some answer sections start without title; repeated short lines like `1.A 2.B 3.C` need separate answer parser.

## Engineering Boundary

Implement only deterministic ownership v1:

```text
input: normalized MinerU layout elements
output: question ownership blocks + warnings
no DeepSeek calls
no database writes
no UI
```

