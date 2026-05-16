# Task: Nested Section Hierarchy v1

Implements [ADR 002: Nested Section Hierarchy](../architecture/002-nested-section-hierarchy.md).

## Scope

- Replace flat `section_title` propagation with hierarchical `section_path`.
- Change dedup key from `(section_title, q_number)` to `(section_path, q_number)`.
- `section_hierarchy_suspected` warning already in place (v1 evaluation).
- No DeepSeek, DB, or UI changes.

## Files to Modify

- `src/question_bank/services/layout_ownership.py`

## Step 1: Add `section_path` to output types

### 1a. `LayoutOwnershipBlock.section_path`

```python
@dataclass(slots=True)
class LayoutOwnershipBlock:
    ...
    section_title: str         # kept for backward compat
    section_path: tuple[str, ...] = ()  # NEW
    ...
```

### 1b. `_Element.section_path`

```python
class _Element:
    ...
    section_title: str = ""
    section_path: tuple[str, ...] = ()  # NEW
    ...
```

## Step 2: Rewrite `detect_sections()`

Replace the flat `current_section_title: str` with `current_path: list[str]`.

Rules (from ADR 002):
1. **ALT_SECTION_PATTERN match** (e.g. "向量小题A"): Reset path to `[text]`.
2. **SECTION_PATTERN match** (e.g. "一、选择题"):
   - If path is non-empty and top-level is nonstandard: append → `["向量小题A", "一、选择题"]`
   - Otherwise: replace → `["一、选择题"]`
3. **ANSWER_SECTION_PATTERN match**: Reset path to `["参考答案"]`.
4. **No active section**: Default path = `[""]`.

```python
def detect_sections(elements: list[_Element]) -> list[str]:
    warnings: list[str] = []
    current_path: list[str] = []

    for elem in elements:
        if elem.is_noise or elem.is_header_footer:
            continue
        text = elem.text.strip()
        if not text:
            continue

        if ANSWER_SECTION_PATTERN.match(text):
            elem.is_answer_section = True
            current_path = ["参考答案"]
            continue

        if ALT_SECTION_PATTERN.match(text):
            elem.is_section = True
            elem.section_title = text
            current_path = [text]
            elem.section_path = tuple(current_path)
            continue

        if SECTION_PATTERN.match(text):
            elem.is_section = True
            elem.section_title = text
            if current_path and NONSTANDARD_SUBSECTION_PATTERN.search(current_path[-1]):
                current_path = [current_path[0], text]
            else:
                current_path = [text]
            elem.section_path = tuple(current_path)
            continue

        elem.section_title = current_path[-1] if current_path else ""
        elem.section_path = tuple(current_path)

    return warnings
```

## Step 3: Propagate `section_path` to blocks

In `build_question_blocks()`, set block `section_path` from the anchor element:

```python
block = LayoutOwnershipBlock(
    ...
    section_title=anchor.section_title,
    section_path=anchor.section_path,  # NEW
    ...
)
```

## Step 4: Change dedup key

In `build_question_blocks()`, change:

```python
# Before:
key = (current_section_title, question_number)
seen_numbers: dict[tuple[str, str], int]

# After:
key = (current_section_path, question_number)
seen_numbers: dict[tuple[tuple[str, ...], str], int]
```

## Step 5: Update `_distribute_warnings()`

The `duplicate_question_number` warning message should include the
`section_path` for clarity:

```python
f"duplicate_question_number: {q_number} appears at anchor {elem.id} "
f"in section_path {anchor.section_path}"
```

## Step 6: Update `_detect_section_hierarchy_issues()`

After ADR 002, the warning should fire LESS often (nested paths resolve
most collisions). Adjust the check:

```python
# Check if duplicates PERSIST after nesting
suspected = []
for qn, qn_blocks in by_number.items():
    if len(qn_blocks) < 3:
        continue
    paths = {b.section_path for b in qn_blocks}
    if len(paths) != len(qn_blocks):  # still have same-path duplicates
        suspected.append(qn)
```

## Tests to Add

1. **Nested section dedup**: Two questions with same number under different
   `section_path` → no duplicate warning.
2. **Same-path duplicate**: Two questions with same number under same
   `section_path` → duplicate warning.
3. **Three-level nesting**: `["专题一", "选择题", "单选题"]` path depth=3.
4. **Nonstandard reset**: "向量小题B" after "向量小题A" replaces top-level.
5. **section_path in output**: Verify `LayoutOwnershipBlock.section_path`
   is populated correctly.
6. **Backward compat**: `section_title` still contains last path component.

## Acceptance Criteria

- All existing 84+ tests pass.
- New nested-section fixture: `layout-case-nested-sections.json`.
- 平面向量A小题 evaluation: `duplicate_question_number` drops from 69 → 0,
  question_count drops from 92 → ~30.
- `section_hierarchy_suspected` no longer fires on papers with resolved nesting.
- 100-paper beta shadow: `section_hierarchy_suspected papers ≤ 20%`.

## Dependencies

- ADR 001 (layout_ownership.py) — already implemented.
- `section_hierarchy_suspected` warning — already in v1.
- PyMuPDF evaluation pipeline — already in `tools/pdf_to_mineru.py`.
