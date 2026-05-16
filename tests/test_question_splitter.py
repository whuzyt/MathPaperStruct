import unittest

from question_bank.services.question_splitter import (
    parse_answer_entries,
    parse_answer_entry,
    parse_choices,
    split_document_sections,
    split_markdown_into_blocks,
)


class QuestionSplitterTest(unittest.TestCase):
    def test_splits_numbered_questions_and_keeps_formula_text(self):
        markdown = """
一、选择题
1. 已知 $x+1=3$，求 $x$。
A. $1$
B. $2$
2. 如图，求三角形面积。
![fig](assets/p1.png)
"""

        blocks = split_markdown_into_blocks("paper_001", markdown)

        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].question_number, "1")
        self.assertEqual(blocks[0].section_title, "一、选择题")
        self.assertIn("$x+1=3$", blocks[0].raw_markdown)
        self.assertEqual(blocks[1].question_number, "2")
        self.assertIn("![fig]", blocks[1].raw_markdown)

    def test_supports_chinese_comma_numbering(self):
        markdown = """
二、填空题
3、计算 $2^3=$____。
4、若 $a>b$，比较 $a+1$ 与 $b+1$。
"""

        blocks = split_markdown_into_blocks("paper_002", markdown)

        self.assertEqual([block.question_number for block in blocks], ["3", "4"])
        self.assertTrue(all(block.paper_id == "paper_002" for block in blocks))

    def test_does_not_split_option_labels_as_questions(self):
        markdown = """
一、选择题
1. 下列计算正确的是（ ）
A. $1+1=3$
B. $2+2=4$
C. $3+3=7$
D. $4+4=8$
2. 下一题题干
"""

        blocks = split_markdown_into_blocks("paper_003", markdown)

        self.assertEqual([block.question_number for block in blocks], ["1", "2"])
        self.assertIn("A. $1+1=3$", blocks[0].raw_markdown)
        self.assertIn("D. $4+4=8$", blocks[0].raw_markdown)

    def test_stops_before_answer_section(self):
        markdown = """
一、选择题
1. 题干一
2. 题干二
参考答案
1. A
2. B
"""

        blocks = split_markdown_into_blocks("paper_004", markdown)

        self.assertEqual([block.question_number for block in blocks], ["1", "2"])
        self.assertNotIn("参考答案", blocks[-1].raw_markdown)

    def test_recognizes_section_headings_without_question_suffix(self):
        markdown = """
三、解答
5. 解方程 $x+1=2$。
"""

        blocks = split_markdown_into_blocks("paper_005", markdown)

        self.assertEqual(blocks[0].section_title, "三、解答")

    def test_supports_question_number_on_its_own_line(self):
        markdown = """
四、压轴题
第 6 题
如图，在矩形 $ABCD$ 中，求 $x$。
"""

        blocks = split_markdown_into_blocks("paper_006", markdown)

        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].question_number, "6")
        self.assertIn("如图", blocks[0].raw_markdown)

    def test_split_document_sections_returns_body_and_answer_markdown(self):
        markdown = """
一、选择题
1. 题干一
2. 题干二
参考答案
1. A
2. B
"""

        sections = split_document_sections(markdown)

        self.assertIn("1. 题干一", sections.body_markdown)
        self.assertNotIn("参考答案", sections.body_markdown)
        self.assertIn("1. A", sections.answer_markdown)

    def test_parse_answer_entries_by_question_number(self):
        answer_markdown = """
参考答案
1. A
2. 解：由 $x+1=2$ 得 $x=1$。
3、答案：$8$
"""

        entries = parse_answer_entries(answer_markdown)

        self.assertEqual(entries["1"], "A")
        self.assertIn("$x=1$", entries["2"])
        self.assertEqual(entries["3"], "答案：$8$")

    def test_parse_answer_entry_splits_answer_and_analysis_labels(self):
        entry = parse_answer_entry("答案：A 解析：代入可得。")

        self.assertEqual(entry.answer_latex, "A")
        self.assertEqual(entry.analysis_latex, "代入可得。")
        self.assertEqual(entry.raw_text, "答案：A 解析：代入可得。")

    def test_parse_answer_entry_treats_solution_as_analysis_when_no_answer_label(self):
        entry = parse_answer_entry("解：由 $x+1=2$ 得 $x=1$。")

        self.assertEqual(entry.answer_latex, "")
        self.assertEqual(entry.analysis_latex, "由 $x+1=2$ 得 $x=1$。")

    def test_parse_answer_entry_treats_plain_choice_as_answer(self):
        entry = parse_answer_entry("B")

        self.assertEqual(entry.answer_latex, "B")
        self.assertEqual(entry.analysis_latex, "")

    def test_parse_choices_from_option_lines(self):
        raw_block = """
1. 下列计算正确的是（ ）
A. $1+1=3$
B、$2+2=4$
C：$3+3=6$
D．$4+4=9$
"""

        choices = parse_choices(raw_block)

        self.assertEqual([choice.label for choice in choices], ["A", "B", "C", "D"])
        self.assertEqual(choices[1].content_latex, "$2+2=4$")

    def test_parse_choices_supports_multiline_option_content(self):
        raw_block = """
1. 阅读材料，选择正确说法。
A. 第一行
继续解释 A
B. 第二项
"""

        choices = parse_choices(raw_block)

        self.assertEqual(len(choices), 2)
        self.assertEqual(choices[0].content_latex, "第一行\n继续解释 A")

    def test_parse_choices_ignores_inline_letter_text(self):
        raw_block = """
1. 点 A 在直线 $l$ 上，求长度。
"""

        self.assertEqual(parse_choices(raw_block), [])


if __name__ == "__main__":
    unittest.main()
