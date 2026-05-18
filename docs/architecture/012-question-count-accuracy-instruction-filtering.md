# ADR 012 — Question Count Accuracy & Instruction Filtering v1

## Status

Accepted (2026-05-18)

## Context

ADR 010 batch evaluation revealed that paper_0086 produced 23 question blocks
when the paper actually contains 22 real questions. The extra block came from
a numbered instruction/preamble item being misidentified as a question anchor.

Layout Ownership's `detect_question_anchors()` matches any Arabic or Chinese
number pattern in leftmost-column position. This is correct for real questions
but produces false positives for instruction/preamble numbered lists that
appear before the first formal section (e.g. "一、选择题").

Common instruction/preamble patterns that get misidentified:
- "1. 答题前，考生务必将姓名填写在答题卡上"
- "2. 本试卷满分 150 分，考试时间 120 分钟"
- "一、注意事项：本试卷分为第 I 卷和第 II 卷"

These tend to appear **before the first real section** — the section pattern
(`SECTION_PATTERN` / `ALT_SECTION_PATTERN`) serves as a natural boundary.

## Decision

Add instruction/preamble filtering to `detect_question_anchors()`:

1. After `detect_sections()` marks section elements, find the reading_order of
   the first formal section element.
2. For each question anchor candidate whose reading_order is **before** the
   first section, perform secondary classification:
   - Check if the element's text contains instruction/preamble cues
   - Check if the text contains math content features
   - If instruction cues are present **and** math features are absent →
     cancel `is_question_anchor` and emit `instruction_number_filtered`
   - If math features are present (regardless of instruction cues) →
     keep the anchor (it's a real question)

### Instruction cues (trigger filtering when math features absent)

```
答题前, 考生须知, 注意事项, 本试卷, 本卷, 考试时间, 满分,
答案写在答题卡, 用2B铅笔, 不准使用, 考试结束后, 选择题作答,
非选择题必须, 将答案写在, 答题卡上, 写在试卷上, 试卷满分,
考试用时, 考生务必将, 务必
```

### Math features (prevent filtering)

```
已知, 设, 若, 求, 证明, 计算, 函数, 数列, 集合, 方程,
不等式, 概率, 椭圆, 双曲线, 抛物线, 向量, 三角形, 圆,
$, ∠, △, ⊙, ∥, ⊥, ≤, ≥, ≠, °, ′, ″, α, β, γ, θ, π,
sin, cos, tan, log
```

### Warning code

`instruction_number_filtered` — emitted when a number-matched element before
the first section is classified as instruction/preamble and excluded from
question blocks.

### Scope

Only anchors with reading_order **before the first formal section** are
subject to filtering. Anchors after a section begins are assumed to be real
questions. Papers without any detected section do **not** apply this filter;
their first numbered elements may be real questions, so filtering without a
section boundary is too risky.

## Consequences

### Positive

- Eliminates false question blocks from instruction/preamble numbered lists
- Improves question count accuracy for papers with preamble sections
- Math features prevent over-filtering of math-heavy opening questions
- Zero false positives expected on math questions (math features dominate)

### Negative

- Instruction items without math features that happen to contain question-like
  content could be incorrectly filtered (rare edge case)
- Papers without sections can still contain numbered instruction text; this is
  accepted because filtering without a section boundary would risk dropping
  real math-first questions.

### Risk mitigation

- Filtering only applies before the first section, limiting blast radius
- Math features act as a strong positive signal that overrides instruction cues
- Warning code `instruction_number_filtered` makes filtered items traceable
- Existing tests verify no regressions on section-detected papers

## Alternatives considered

1. **Filter by page 1 only.** Rejected — preamble text can span multiple pages
   in long exam papers with detailed instructions.

2. **Use an LLM classifier for instruction vs. question.** Rejected —
   introduces latency and cost for a problem solvable with keyword matching.
   Could revisit if keyword approach proves insufficient.

3. **Mark instruction elements as a new section type.** Rejected — instruction
   text is structurally different from sections and shouldn't affect
   section_path propagation.
