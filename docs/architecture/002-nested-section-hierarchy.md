# ADR 002: Nested Section Hierarchy

## Status

Proposed — blocking issue identified in v1 empirical evaluation (2026-05-17).

## Problem

ADR 001 uses a flat section model:

```python
section_title: str  # e.g. "一、选择题"
dedup_key = (section_title, question_number)
```

This fails for papers with nested sections, where the same question numbers
repeat under different top-level sections:

```text
向量小题A
  一、选择题
    1. ...
    2. ...
向量小题B
  一、选择题
    1. ...
    2. ...
```

In v1, `section_title` is overwritten: "向量小题A" → "一、选择题". All
questions collapse into "一、选择题", producing 69 false duplicates in the
平面向量A小题 evaluation.

**Empirical impact** (from v1 evaluation):

| Metric | Value |
|--------|-------|
| False duplicate_question_number | 69 of 92 questions |
| question_count over-count | 92 vs ~30 ground truth |
| section_hierarchy_suspected | correctly detected |

## Decision

Replace the flat `section_title: str` with a hierarchical `section_path`:

```python
section_path: tuple[str, ...]  # e.g. ("向量小题A", "一、选择题")
dedup_key = (section_path, question_number)
```

### Section Path Construction

Sections are detected in reading order. When a section element is encountered:

1. **Standard section** (matches `SECTION_PATTERN`: `一、选择题` etc.):
   - If a nonstandard section is active, push onto it: `("向量小题A", "一、选择题")`
   - Otherwise, start a new top-level section: `("一、选择题",)`

2. **Nonstandard section** (matches `ALT_SECTION_PATTERN`: `向量小题A` etc.):
   - Always starts a new top-level section, replacing any active nonstandard:
     `("向量小题A",)`
   - The next standard section will nest under this.

3. **Answer section**: Resets the path to `("参考答案",)`.

4. **No active section**: Default path = `("",)`.

### Section Nesting Rules

- Maximum depth: 3 levels (top_section, subsection, subsubsection).
- Nonstandard sections are always top-level (reset depth to 1).
- Standard sections at reading-order position after a nonstandard section become level 2.
- Another standard section after a standard section replaces level 2 (not level 3).
- A nonstandard section after a standard section resets the path.

### Dedup Key Change

```python
# Before (ADR 001):
duplicate_key = (section_title, question_number)
seen_numbers: dict[tuple[str, str], int]

# After (ADR 002):
duplicate_key = (section_path, question_number)
seen_numbers: dict[tuple[tuple[str, ...], str], int]
```

A question number is only a duplicate if it appears with the EXACT same
`section_path`. Same number under different paths is expected behavior.

### New Warning: `section_hierarchy_suspected`

Already implemented in v1 as a heuristic detector. ADR 002 makes this a
first-class check:

```python
def _detect_section_hierarchy_issues(blocks, elements) -> list[str]:
    """Trigger when:
    1. Paper has nonstandard section markers (ALT_SECTION_PATTERN match)
    2. Same question_number appears >= 3 times
    3. Section_title changes between occurrences
    """
```

This warning fires independently of the nested model. It serves as a
cross-check: if the nested model resolves all duplicates, the warning
should NOT fire. If it still fires, the nesting model needs tuning.

### Output Contract Change

```json
{
  "question_block_id": "paper_001_qb_0001",
  "question_number": "1",
  "section_path": ["向量小题A", "一、选择题"],
  "section_title": "一、选择题",
  "pages": [1],
  ...
}
```

`section_title` is kept for backward compatibility (last component of path).
`section_path` is the new authoritative field.

## Nonstandard Subsection Patterns

```python
NONSTANDARD_SUBSECTION_PATTERN = re.compile(
    r"(?:小题|专题|模块|题组|类型|考点|向量小题|"
    r"第[一二三四五六七八九十]+组|"
    r"[A-H][组类])"
)
```

These patterns signal that section titles may nest. Papers matching these
patterns are candidates for nested hierarchy processing.

## Beta Shadow Acceptance Criteria

From the 100-paper beta shadow batch:

| Metric | Threshold |
|--------|-----------|
| single_column q_count mismatch median | ≤ 5% |
| two_column q_count mismatch median | ≤ 15% |
| critical串题 | = 0 |
| 答案区污染 | = 0 |
| missing_anchor_suspected rate | ≤ 3% |
| unassigned_visual_asset explainable | ≥ 90% |
| section_hierarchy_suspected papers | ≤ 20% |

If `section_hierarchy_suspected papers > 20%`: pause batch expansion,
implement ADR 002, re-evaluate.

## Scope

- **In scope**: Section path construction, dedup key change, output contract update.
- **In scope**: `section_hierarchy_suspected` warning (already in v1).
- **Out of scope**: DeepSeek section detection, DB schema changes, UI changes.
- **Out of scope**: Replacing the old splitter with layout_ownership.

## Implementation File

```text
docs/tasks/nested-section-hierarchy-v1.md
```
