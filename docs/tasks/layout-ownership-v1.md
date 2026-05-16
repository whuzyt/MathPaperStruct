# Task: Layout Ownership v1

## Objective

Implement ADR 001 exactly.

## Scope

In scope:

```text
column detection
reading order
section detection
question anchor detection
question block boundary
text/formula ownership
asset scoring and assignment
warning generation
fixture-based tests
```

Out of scope:

```text
DeepSeek
database persistence
manual review UI
image OCR
formula repair
```

## Acceptance Criteria

```text
1. Two-column fixture does not mix left/right column questions.
2. Image-nearby fixture assigns image to question with visual cue.
3. Cross-page fixture merges continuation into one question.
4. Answer-section fixture stops body ownership before answers.
5. Cross-column image fixture allows full-width figure assignment.
6. All ambiguous asset assignments emit warning codes.
```

## Test Command

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

