from __future__ import annotations

import json
import unittest

from question_bank.services.duplicate_review import (
    DuplicateCandidateGroup,
    DuplicateCandidateItem,
    ReviewDecision,
    SimilarityScores,
    _compute_pairwise_similarity,
    _section_jaccard,
    _trim_top_examples,
    format_groups_summary,
    generate_candidate_groups,
    groups_to_json,
)
from question_bank.services.question_identity import QuestionIdentity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_identity(
    block_id: str = "qb_001",
    paper_id: str = "paper_01",
    section_path: tuple[str, ...] = ("一、选择题",),
    question_number: str = "1",
    text_fp: str = "abc123",
    latex_fp: str = "",
    asset_sig: str = "",
) -> QuestionIdentity:
    path_str = "/".join(section_path)
    return QuestionIdentity(
        block_id=block_id,
        source_position_key=f"{paper_id}#{path_str}#{question_number}",
        text_fingerprint=text_fp,
        latex_fingerprint=latex_fp,
        asset_signature=asset_sig,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSectionJaccard(unittest.TestCase):
    def test_identical_paths(self):
        self.assertEqual(_section_jaccard("一/选择题", "一/选择题"), 1.0)

    def test_disjoint_paths(self):
        self.assertEqual(_section_jaccard("一/选择题", "二/填空题"), 0.0)

    def test_partial_overlap(self):
        self.assertEqual(_section_jaccard("向量小题A/一、选择题", "向量小题A/二、填空题"), 1.0 / 3.0)

    def test_empty_paths(self):
        self.assertEqual(_section_jaccard("", ""), 0.0)

    def test_one_empty(self):
        self.assertEqual(_section_jaccard("一/选择题", ""), 0.0)


class TestPairwiseSimilarity(unittest.TestCase):
    def _make_item(self, text_fp="abc", latex_fp="", asset_sig="", section_path="一/选择题"):
        return DuplicateCandidateItem(
            block_id="qb_001", paper_id="paper_01", section_path=section_path,
            question_number="1", source_position_key=f"paper_01#{section_path}#1",
            text_fingerprint=text_fp, latex_fingerprint=latex_fp,
            asset_signature=asset_sig,
        )

    def test_identical_items_max_composite(self):
        a = self._make_item(text_fp="abc", latex_fp="xyz", asset_sig="img1")
        b = self._make_item(text_fp="abc", latex_fp="xyz", asset_sig="img1")
        scores = _compute_pairwise_similarity([a, b])
        s = scores[(0, 1)]
        self.assertEqual(s.text_match, 1.0)
        self.assertEqual(s.latex_match, 1.0)
        self.assertEqual(s.asset_match, 1.0)
        self.assertAlmostEqual(s.composite, 1.0)

    def test_different_latex_partial_score(self):
        a = self._make_item(text_fp="abc", latex_fp="xyz", asset_sig="img1")
        b = self._make_item(text_fp="abc", latex_fp="zzz", asset_sig="img1")
        scores = _compute_pairwise_similarity([a, b])
        s = scores[(0, 1)]
        self.assertEqual(s.text_match, 1.0)
        self.assertEqual(s.latex_match, 0.0)
        self.assertEqual(s.asset_match, 1.0)
        expected = 0.25 * 1.0 + 0.35 * 0.0 + 0.25 * 1.0 + 0.15 * 1.0
        self.assertAlmostEqual(s.composite, expected)

    def test_empty_fingerprints_handled(self):
        a = self._make_item(text_fp="", latex_fp="", asset_sig="")
        b = self._make_item(text_fp="", latex_fp="", asset_sig="")
        scores = _compute_pairwise_similarity([a, b])
        s = scores[(0, 1)]
        self.assertEqual(s.text_match, 0.0)
        self.assertEqual(s.latex_match, 0.0)
        self.assertEqual(s.asset_match, 0.0)

    def test_mixed_empty_and_filled(self):
        a = self._make_item(text_fp="abc", latex_fp="xyz", asset_sig="")
        b = self._make_item(text_fp="abc", latex_fp="", asset_sig="img1")
        scores = _compute_pairwise_similarity([a, b])
        s = scores[(0, 1)]
        self.assertEqual(s.text_match, 1.0)
        self.assertEqual(s.latex_match, 0.0)
        self.assertEqual(s.asset_match, 0.0)


class TestTrimTopExamples(unittest.TestCase):
    def _make_item(self, idx: int, paper_id: str = "paper_01"):
        return DuplicateCandidateItem(
            block_id=f"qb_{idx:03d}", paper_id=paper_id,
            section_path="一/选择题", question_number=str(idx),
            source_position_key=f"{paper_id}#一/选择题#{idx}",
            text_fingerprint="abc", latex_fingerprint="", asset_signature="",
        )

    def test_trims_to_max(self):
        items = [self._make_item(i) for i in range(5)]
        similarities = _compute_pairwise_similarity(items)
        trimmed = _trim_top_examples(items, similarities, 3)
        self.assertEqual(len(trimmed), 3)

    def test_no_trim_when_under_max(self):
        items = [self._make_item(i) for i in range(3)]
        similarities = _compute_pairwise_similarity(items)
        trimmed = _trim_top_examples(items, similarities, 5)
        self.assertEqual(len(trimmed), 3)


class TestGenerateCandidateGroups(unittest.TestCase):
    def test_empty_input_returns_empty(self):
        groups = generate_candidate_groups({})
        self.assertEqual(groups, [])

    def test_single_paper_no_collisions(self):
        ids = {
            "paper_01": [
                _make_identity("qb_1", "paper_01", text_fp="aaa"),
                _make_identity("qb_2", "paper_01", text_fp="bbb"),
            ]
        }
        groups = generate_candidate_groups(ids)
        self.assertEqual(groups, [])

    def test_cross_paper_collision_produces_group(self):
        ids = {
            "paper_01": [_make_identity("qb_1", "paper_01", text_fp="dup1")],
            "paper_02": [_make_identity("qb_2", "paper_02", text_fp="dup1")],
        }
        groups = generate_candidate_groups(ids)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].fingerprint, "dup1")
        self.assertEqual(len(groups[0].items), 2)
        papers = {item.paper_id for item in groups[0].items}
        self.assertEqual(papers, {"paper_01", "paper_02"})

    def test_min_candidates_filter(self):
        ids = {
            "paper_01": [_make_identity("qb_1", "paper_01", text_fp="dup1")],
            "paper_02": [_make_identity("qb_2", "paper_02", text_fp="dup1")],
            "paper_03": [_make_identity("qb_3", "paper_03", text_fp="dup1")],
        }
        groups = generate_candidate_groups(ids, min_candidates=3)
        self.assertEqual(len(groups), 1)
        groups = generate_candidate_groups(ids, min_candidates=4)
        self.assertEqual(len(groups), 0)

    def test_empty_fingerprints_excluded(self):
        ids = {
            "paper_01": [_make_identity("qb_1", "paper_01", text_fp="")],
            "paper_02": [_make_identity("qb_2", "paper_02", text_fp="")],
        }
        groups = generate_candidate_groups(ids)
        self.assertEqual(groups, [])

    def test_multiple_fingerprints_multiple_groups(self):
        ids = {
            "paper_01": [
                _make_identity("qb_1", "paper_01", text_fp="dup1"),
                _make_identity("qb_2", "paper_01", text_fp="dup2"),
            ],
            "paper_02": [
                _make_identity("qb_3", "paper_02", text_fp="dup1"),
                _make_identity("qb_4", "paper_02", text_fp="dup2"),
            ],
        }
        groups = generate_candidate_groups(ids)
        self.assertEqual(len(groups), 2)
        fps = {g.fingerprint for g in groups}
        self.assertEqual(fps, {"dup1", "dup2"})

    def test_same_paper_same_fingerprint_not_enough(self):
        ids = {
            "paper_01": [
                _make_identity("qb_1", "paper_01", text_fp="dup1"),
                _make_identity("qb_2", "paper_01", text_fp="dup1"),
            ],
        }
        groups = generate_candidate_groups(ids, min_candidates=2)
        self.assertEqual(groups, [])

    def test_paper_id_extracted_from_identity_key(self):
        ids = {
            "paper_01": [_make_identity("qb_1", "paper_01", text_fp="dup1")],
            "paper_02": [_make_identity("qb_2", "paper_02", text_fp="dup1")],
        }
        groups = generate_candidate_groups(ids)
        self.assertEqual(groups[0].items[0].paper_id, "paper_01")
        self.assertEqual(groups[0].items[1].paper_id, "paper_02")

    def test_nested_section_path_extracted(self):
        ids = {
            "paper_01": [_make_identity(
                "qb_1", "paper_01",
                section_path=("向量小题A", "一、选择题"),
                question_number="3", text_fp="dup1",
            )],
            "paper_02": [_make_identity(
                "qb_2", "paper_02",
                section_path=("二、填空题",),
                question_number="5", text_fp="dup1",
            )],
        }
        groups = generate_candidate_groups(ids)
        self.assertEqual(len(groups), 1)
        paths = {item.section_path for item in groups[0].items}
        self.assertIn("向量小题A/一、选择题", paths)
        self.assertIn("二、填空题", paths)

    def test_fingerprint_type_latex(self):
        ids = {
            "paper_01": [
                _make_identity("qb_1", "paper_01", text_fp="aaa", latex_fp="latex1"),
            ],
            "paper_02": [
                _make_identity("qb_2", "paper_02", text_fp="bbb", latex_fp="latex1"),
            ],
        }
        groups = generate_candidate_groups(ids, fingerprint_type="latex")
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].fingerprint, "latex1")


class TestGroupSerialization(unittest.TestCase):
    def test_groups_to_json_round_trips(self):
        ids = {
            "paper_01": [_make_identity("qb_1", "paper_01", text_fp="dup1")],
            "paper_02": [_make_identity("qb_2", "paper_02", text_fp="dup1")],
        }
        groups = generate_candidate_groups(ids)
        json_str = groups_to_json(groups)
        data = json.loads(json_str)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["fingerprint"], "dup1")
        self.assertEqual(data[0]["item_count"], 2)
        self.assertIn("items", data[0])
        self.assertIn("pairwise_similarities", data[0])

    def test_format_groups_summary_empty(self):
        result = format_groups_summary([])
        self.assertIn("No duplicate", result)

    def test_format_groups_summary_contains_key_info(self):
        ids = {
            "paper_01": [_make_identity("qb_1", "paper_01", text_fp="dup1")],
            "paper_02": [_make_identity("qb_2", "paper_02", text_fp="dup1")],
        }
        groups = generate_candidate_groups(ids)
        result = format_groups_summary(groups)
        self.assertIn(groups[0].id, result)
        self.assertIn("paper_01", result)
        self.assertIn("paper_02", result)


class TestRepositoryIntegration(unittest.TestCase):
    """Test the repository methods using FakeConnection/FakeCursor pattern."""

    def _make_group(self) -> DuplicateCandidateGroup:
        item_a = DuplicateCandidateItem(
            block_id="qb_001", paper_id="paper_01", section_path="一/选择题",
            question_number="1", source_position_key="paper_01#一/选择题#1",
            text_fingerprint="abc123", latex_fingerprint="xyz789",
            asset_signature="",
        )
        item_b = DuplicateCandidateItem(
            block_id="qb_002", paper_id="paper_02", section_path="二/填空题",
            question_number="5", source_position_key="paper_02#二/填空题#5",
            text_fingerprint="abc123", latex_fingerprint="xyz789",
            asset_signature="",
        )
        similarities = _compute_pairwise_similarity([item_a, item_b])
        return DuplicateCandidateGroup(
            id="dcg_abc123", fingerprint="abc123", fingerprint_type="text",
            items=[item_a, item_b], pairwise_similarities=similarities,
        )

    def _make_fake_connection(self):
        return FakeConnection(FakeCursor())

    def test_save_group_inserts_group_and_items(self):
        from question_bank.repository import PostgresQuestionBankRepository

        group = self._make_group()
        conn = self._make_fake_connection()
        repo = PostgresQuestionBankRepository(conn)
        repo.save_duplicate_candidate_group(group)

        tables = {s.table for s in conn.cursor_obj.statements}
        self.assertIn("duplicate_candidate_groups", tables)
        self.assertIn("duplicate_candidate_items", tables)

    def test_save_group_deletes_old_items_first(self):
        from question_bank.repository import PostgresQuestionBankRepository

        group = self._make_group()
        conn = self._make_fake_connection()
        repo = PostgresQuestionBankRepository(conn)
        repo.save_duplicate_candidate_group(group)

        delete_stmts = [
            s for s in conn.cursor_obj.statements
            if s.sql.strip().upper().startswith("DELETE")
        ]
        self.assertEqual(len(delete_stmts), 1)
        self.assertIn("duplicate_candidate_items", delete_stmts[0].sql)

    def test_save_decision_inserts(self):
        from question_bank.repository import PostgresQuestionBankRepository

        decision = ReviewDecision(
            group_id="dcg_abc123", decision="same",
            canonical_question_id="q_001", reviewer="test-user", reason="identical",
        )
        conn = self._make_fake_connection()
        repo = PostgresQuestionBankRepository(conn)
        repo.save_review_decision(decision)

        self.assertGreater(len(conn.cursor_obj.statements), 0)
        stmt = conn.cursor_obj.statements[0]
        self.assertIn("duplicate_review_decisions", stmt.sql)
        self.assertEqual(stmt.params["decision"], "same")
        self.assertEqual(stmt.params["reviewer"], "test-user")

    def test_list_groups_fetches(self):
        from question_bank.repository import PostgresQuestionBankRepository

        conn = FakeConnection(FakeCursor(rows=[
            ("dcg_abc123", "abc123", "text", 2, 1.0, "pending", "2026-01-01"),
        ]))
        repo = PostgresQuestionBankRepository(conn)
        groups = repo.list_duplicate_groups(limit=10)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["id"], "dcg_abc123")
        self.assertEqual(groups[0]["candidate_count"], 2)

    def test_list_groups_with_status_filter(self):
        from question_bank.repository import PostgresQuestionBankRepository

        conn = FakeConnection(FakeCursor(rows=[
            ("dcg_abc123", "abc123", "text", 2, 1.0, "resolved", "2026-01-01"),
        ]))
        repo = PostgresQuestionBankRepository(conn)
        groups = repo.list_duplicate_groups(status="resolved", limit=10)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["status"], "resolved")

    def test_get_duplicate_group_returns_full_detail(self):
        from question_bank.repository import PostgresQuestionBankRepository

        # Three fetches: group, items, decisions
        fake_cursor = FakeCursor()
        fake_cursor.setup_responses([
            [
                ("dcg_abc123", "abc123", "text", 2, 1.0, "pending", "2026-01-01"),
            ],  # group row
            [
                ("i1", "dcg_abc123", "qb_001", None, "paper_01", "一/选择题",
                 "1", "paper_01#一/选择题#1", "abc123", "xyz", ""),
            ],  # items
            [],  # decisions (none)
        ])
        conn = FakeConnection(fake_cursor)
        repo = PostgresQuestionBankRepository(conn)
        group = repo.get_duplicate_group("dcg_abc123")
        self.assertIsNotNone(group)
        self.assertEqual(group["id"], "dcg_abc123")
        self.assertEqual(len(group["items"]), 1)
        self.assertEqual(group["items"][0]["paper_id"], "paper_01")

    def test_save_decision_idempotent(self):
        from question_bank.repository import PostgresQuestionBankRepository

        decision = ReviewDecision(
            group_id="dcg_abc123", decision="same",
            canonical_question_id="q_001", reviewer="test-user", reason="identical",
        )
        conn = self._make_fake_connection()
        repo = PostgresQuestionBankRepository(conn)
        # First call
        repo.save_review_decision(decision)
        # Second call — should NOT raise
        repo.save_review_decision(decision)
        self.assertEqual(len(conn.cursor_obj.statements), 2)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class ExecutedStatement:
    def __init__(self, sql: str, params: dict):
        self.sql = sql
        self.params = params

    @property
    def table(self) -> str:
        """Best-effort table name extraction from INSERT INTO or DELETE FROM."""
        import re
        m = re.search(
            r"(?:INSERT\s+INTO|DELETE\s+FROM)\s+(\w+)",
            self.sql, re.IGNORECASE,
        )
        return m.group(1) if m else ""


class FakeCursor:
    def __init__(self, rows=None):
        self.statements: list[ExecutedStatement] = []
        self._response_queue: list[list] = []
        if rows is not None:
            self._response_queue.append(rows)

    def setup_responses(self, response_queue: list[list]):
        self._response_queue = response_queue

    def execute(self, sql: str, params: dict):
        self.statements.append(ExecutedStatement(sql, params))

    def fetchall(self) -> list:
        if self._response_queue:
            return self._response_queue.pop(0)
        return []

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None


class FakeConnection:
    def __init__(self, cursor: FakeCursor):
        self.cursor_obj = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


if __name__ == "__main__":
    unittest.main()
