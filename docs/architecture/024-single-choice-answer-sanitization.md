# ADR 024: Single-choice Answer Sanitization

## Status

Accepted.

## Context

The 10-PDF production pilot found that most remaining quality warnings were
`answer_not_in_choices`. Inspection showed two distinct model failure modes:

- recoverable answers that embed a valid label inside explanation text, such as
  `B\n【解析】...故选：B`;
- non-answer payloads where `answer_latex` contains whole question markdown,
  image markdown, or section instructions.

Saving a polluted payload as the answer is worse than leaving the answer empty:
it creates false correctness data and keeps triggering quality gates.

## Decision

During DeepSeek hardening, single-choice answers are sanitized in this order:

1. extract a reliable label from `答案/正确答案/故选/故答案为/选 + A-H`;
2. extract a leading label like `D．...` or `B\n...`;
3. if no reliable label exists and the value looks like whole-question or
   instruction payload, clear `answer_latex` and append
   `answer_cleared_non_answer`;
4. otherwise keep the existing ADR 015 choice-content matching behavior.

The sanitizer must not convert arbitrary unmatched short text into an empty
answer. Ambiguous short answers remain unchanged for manual review.

## Consequences

- Valid polluted answers become usable labels and pass `answer_not_in_choices`.
- Obvious non-answer payloads are no longer stored as incorrect selected labels.
- The absence of an answer remains reviewable through model warnings and
  downstream validation, rather than being hidden as a false label.
