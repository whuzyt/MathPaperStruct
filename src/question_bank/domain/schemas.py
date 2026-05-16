DEEPSEEK_QUESTION_REQUIRED_FIELDS = {
    "question_type",
    "stem_latex",
    "choices",
    "answer_latex",
    "analysis_latex",
    "knowledge_points",
    "difficulty",
    "confidence",
    "warnings",
}

DEEPSEEK_QUESTION_TYPES = {
    "single_choice",
    "multiple_choice",
    "fill_blank",
    "short_answer",
    "proof",
    "unknown",
}

DEEPSEEK_CONFIDENCE_REQUIRED_FIELDS = {
    "structure",
    "latex",
    "answer",
    "knowledge",
}

DEEPSEEK_QUESTION_SCHEMA = {
    "type": "object",
    "required": sorted(DEEPSEEK_QUESTION_REQUIRED_FIELDS),
    "properties": {
        "question_type": {"type": "string", "enum": sorted(DEEPSEEK_QUESTION_TYPES)},
        "stem_latex": {"type": "string"},
        "choices": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["label", "content_latex"],
                "properties": {
                    "label": {"type": "string"},
                    "content_latex": {"type": "string"},
                },
            },
        },
        "answer_latex": {"type": "string"},
        "analysis_latex": {"type": "string"},
        "knowledge_points": {"type": "array", "items": {"type": "string"}},
        "difficulty": {"type": ["integer", "null"]},
        "confidence": {
            "type": "object",
            "required": sorted(DEEPSEEK_CONFIDENCE_REQUIRED_FIELDS),
            "properties": {
                "structure": {"type": "number"},
                "latex": {"type": "number"},
                "answer": {"type": "number"},
                "knowledge": {"type": "number"},
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
}
