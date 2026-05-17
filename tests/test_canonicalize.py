from __future__ import annotations

import unittest

from question_bank.services.canonicalize import (
    CanonicalQuestion,
    CanonicalizationEvent,
    QuestionVariant,
    build_canonical_id,
    canonicalize_group,
    is_eligible_for_canonicalization,
    select_representative,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(
    block_id: str = "qb_001",
    paper_id: str = "paper_01",
    section_path: str = "一/选择题",
    question_number: str = "1",
    source_position_key: str | None = None,
    text_fp: str = "abc123",
    latex_fp: str = "",
    asset_sig: str = "",
    question_id: str | None = None,
) -> dict:
    if source_position_key is None:
        source_position_key = f"{paper_id}#{section_path}#{question_number}"
    return {
        "block_id": block_id,
        "paper_id": paper_id,
        "section_path": section_path,
        "question_number": question_number,
        "source_position_key": source_position_key,
        "text_fingerprint": text_fp,
        "latex_fingerprint": latex_fp,
        "asset_signature": asset_sig,
        "question_id": question_id,
    }


def _make_group(
    group_id: str = "dcg_abc123",
    fingerprint: str = "abc123",
    items: list[dict] | None = None,
    decisions: list[dict] | None = None,
) -> dict:
    return {
        "id": group_id,
        "fingerprint": fingerprint,
        "fingerprint_type": "text",
        "candidate_count": len(items or []),
        "max_similarity": 1.0,
        "status": "pending",
        "items": items or [],
        "decisions": decisions or [],
    }


def _make_same_decision(group_id: str = "dcg_abc123", reviewer: str = "test-user") -> dict:
    return {
        "id": f"drd_{group_id}_{reviewer}_same",
        "group_id": group_id,
        "decision": "same",
        "canonical_question_id": None,
        "reviewer": reviewer,
        "reason": "identical",
    }


# ---------------------------------------------------------------------------
# TestIsEligible
# ---------------------------------------------------------------------------


class TestIsEligible(unittest.TestCase):
    def test_group_with_same_decision_is_eligible(self):
        group = _make_group(
            decisions=[_make_same_decision()],
        )
        self.assertTrue(is_eligible_for_canonicalization(group))

    def test_group_with_variant_only_not_eligible(self):
        group = _make_group(
            decisions=[{"id": "drd_1", "group_id": "dcg_X", "decision": "variant"}],
        )
        self.assertFalse(is_eligible_for_canonicalization(group))

    def test_no_decisions_not_eligible(self):
        group = _make_group()
        self.assertFalse(is_eligible_for_canonicalization(group))


# ---------------------------------------------------------------------------
# TestSelectRepresentative
# ---------------------------------------------------------------------------


class TestSelectRepresentative(unittest.TestCase):
    def test_highest_avg_similarity_wins(self):
        items = [
            _make_item(block_id="qb_1", paper_id="p1", text_fp="aaa", latex_fp="x"),
            _make_item(block_id="qb_2", paper_id="p2", text_fp="aaa", latex_fp="x"),
            _make_item(block_id="qb_3", paper_id="p3", text_fp="bbb", latex_fp="y"),
        ]
        rep = select_representative(items)
        # qb_1 and qb_2 share both fingerprints → highest avg
        self.assertIn(rep["block_id"], ["qb_1", "qb_2"])

    def test_tie_break_by_source_position_key(self):
        items = [
            _make_item(block_id="qb_B", paper_id="p2", text_fp="aaa",
                       source_position_key="p2#一#1"),
            _make_item(block_id="qb_A", paper_id="p1", text_fp="aaa",
                       source_position_key="p1#一#1"),
        ]
        rep = select_representative(items)
        self.assertEqual(rep["block_id"], "qb_A")

    def test_single_item_returns_itself(self):
        items = [_make_item(block_id="qb_1")]
        rep = select_representative(items)
        self.assertEqual(rep["block_id"], "qb_1")

    def test_empty_items_returns_empty(self):
        self.assertEqual(select_representative([]), {})


# ---------------------------------------------------------------------------
# TestCanonicalizeGroup
# ---------------------------------------------------------------------------


class TestCanonicalizeGroup(unittest.TestCase):
    def test_generates_canonical_with_correct_id(self):
        items = [
            _make_item(block_id="qb_1", paper_id="p1", text_fp="abc"),
            _make_item(block_id="qb_2", paper_id="p2", text_fp="abc"),
        ]
        group = _make_group(
            group_id="dcg_abc123",
            items=items,
            decisions=[_make_same_decision("dcg_abc123")],
        )
        result = canonicalize_group(group, "test-user")
        cq = result["canonical"]
        expected_id = build_canonical_id("dcg_abc123")
        self.assertEqual(cq.id, expected_id)
        self.assertTrue(cq.id.startswith("cqn_"))

    def test_generates_one_variant_per_item(self):
        items = [
            _make_item(block_id="qb_1", paper_id="p1"),
            _make_item(block_id="qb_2", paper_id="p2"),
        ]
        group = _make_group(
            group_id="dcg_X",
            items=items,
            decisions=[_make_same_decision("dcg_X")],
        )
        result = canonicalize_group(group, "test-user")
        self.assertEqual(len(result["variants"]), 2)

    def test_representative_is_correct(self):
        items = [
            _make_item(block_id="qb_1", paper_id="p1", text_fp="abc", latex_fp="x"),
            _make_item(block_id="qb_2", paper_id="p2", text_fp="abc", latex_fp="x"),
            _make_item(block_id="qb_3", paper_id="p3", text_fp="xyz", latex_fp=""),
        ]
        group = _make_group(
            group_id="dcg_X",
            items=items,
            decisions=[_make_same_decision("dcg_X")],
        )
        result = canonicalize_group(group, "test-user")
        cq = result["canonical"]
        self.assertIn(cq.representative_item_id, ["qb_1", "qb_2"])

    def test_stem_answer_empty_by_default(self):
        items = [_make_item(block_id="qb_1", paper_id="p1")]
        group = _make_group(
            group_id="dcg_X",
            items=items,
            decisions=[_make_same_decision("dcg_X")],
        )
        result = canonicalize_group(group, "test-user")
        cq = result["canonical"]
        self.assertEqual(cq.stem_latex, "")
        self.assertEqual(cq.answer_latex, "")

    def test_canonical_is_idempotent(self):
        items = [_make_item(block_id="qb_1", paper_id="p1", text_fp="abc")]
        group = _make_group(
            group_id="dcg_X",
            items=items,
            decisions=[_make_same_decision("dcg_X")],
        )
        r1 = canonicalize_group(group, "test-user")
        r2 = canonicalize_group(group, "test-user")
        self.assertEqual(r1["canonical"].id, r2["canonical"].id)
        self.assertEqual(
            r1["canonical"].representative_item_id,
            r2["canonical"].representative_item_id,
        )

    def test_raises_on_group_without_same_decision(self):
        group = _make_group(group_id="dcg_X")
        with self.assertRaises(ValueError) as ctx:
            canonicalize_group(group, "test-user")
        self.assertIn("no 'same' decision", str(ctx.exception).lower())

    def test_raises_on_group_without_items(self):
        group = _make_group(
            group_id="dcg_X",
            decisions=[_make_same_decision("dcg_X")],
        )
        with self.assertRaises(ValueError) as ctx:
            canonicalize_group(group, "test-user")
        self.assertIn("no items", str(ctx.exception).lower())

    def test_build_canonical_id_deterministic(self):
        a = build_canonical_id("dcg_abc123")
        b = build_canonical_id("dcg_abc123")
        self.assertEqual(a, b)

    def test_build_canonical_id_different_for_different_groups(self):
        a = build_canonical_id("dcg_aaa")
        b = build_canonical_id("dcg_bbb")
        self.assertNotEqual(a, b)


# ---------------------------------------------------------------------------
# TestRepositoryIntegration
# ---------------------------------------------------------------------------


class TestRepositoryIntegration(unittest.TestCase):
    def _make_fake_connection(self, cursor=None):
        if cursor is None:
            cursor = FakeCursor()
        return FakeConnection(cursor)

    def _setup_group_with_same_decision(self):
        """Setup cursor with group, items, and a 'same' decision."""
        fake_cursor = FakeCursor()
        fake_cursor.setup_responses([
            # get_duplicate_group: group row
            [
                ("dcg_abc123", "abc123", "text", 2, 1.0, "pending", "2026-01-01"),
            ],
            # get_duplicate_group: items
            [
                ("i1", "dcg_abc123", "qb_001", None, "paper_01", "一/选择题",
                 "1", "paper_01#一/选择题#1", "abc123", "", ""),
                ("i2", "dcg_abc123", "qb_002", None, "paper_02", "一/选择题",
                 "2", "paper_02#一/选择题#2", "abc123", "", ""),
            ],
            # get_duplicate_group: decisions
            [
                ("drd_1", "dcg_abc123", "same", None, "test-user", "identical", "2026-01-01"),
            ],
            # _SELECT_CANONICAL_BY_GROUP_ID: no existing canonical
            [],
        ])
        conn = self._make_fake_connection(fake_cursor)
        return conn

    def test_canonicalize_group_creates_canonical_and_variants(self):
        from question_bank.repository import PostgresQuestionBankRepository

        conn = self._setup_group_with_same_decision()
        repo = PostgresQuestionBankRepository(conn)
        result = repo.canonicalize_group("dcg_abc123", "test-user")

        self.assertIn("canonical", result)
        self.assertEqual(result["canonical"]["status"], "active")
        self.assertIn("cqn_", result["canonical"]["id"])

        variants = result["variants"]
        self.assertEqual(len(variants), 2)
        papers = {v["paper_id"] for v in variants}
        self.assertEqual(papers, {"paper_01", "paper_02"})

        # Verify INSERT statements were executed
        tables = {s.table for s in conn.cursor_obj.statements if s.table}
        self.assertIn("canonical_questions", tables)
        self.assertIn("question_variants", tables)
        self.assertIn("canonicalization_events", tables)

    def test_save_canonical_question_upserts(self):
        from question_bank.repository import PostgresQuestionBankRepository

        conn = self._make_fake_connection()
        repo = PostgresQuestionBankRepository(conn)
        cq = CanonicalQuestion(
            id="cqn_abc123", canonical_fingerprint="fp_abc",
            representative_item_id="qb_001", stem_latex="stem",
            answer_latex="ans", analysis_latex="", question_type="",
            difficulty=None, status="active", created_from_group_id="dcg_X",
        )
        repo.save_canonical_question(cq)
        self.assertGreater(len(conn.cursor_obj.statements), 0)
        stmt = conn.cursor_obj.statements[0]
        self.assertIn("canonical_questions", stmt.sql)
        self.assertEqual(stmt.params["id"], "cqn_abc123")

    def test_save_question_variant_upserts(self):
        from question_bank.repository import PostgresQuestionBankRepository

        conn = self._make_fake_connection()
        repo = PostgresQuestionBankRepository(conn)
        v = QuestionVariant(
            id="cqn_X_var_qb_1", canonical_question_id="cqn_X",
            question_id=None, paper_id="paper_01", variant_type="candidate",
            source_position_key="paper_01#一#1", text_fingerprint="abc",
            latex_fingerprint="", asset_signature="",
        )
        repo.save_question_variant(v)
        self.assertGreater(len(conn.cursor_obj.statements), 0)

    def test_save_canonicalization_event_inserts(self):
        from question_bank.repository import PostgresQuestionBankRepository

        conn = self._make_fake_connection()
        repo = PostgresQuestionBankRepository(conn)
        e = CanonicalizationEvent(
            id="cqn_X_evt_created", canonical_question_id="cqn_X",
            group_id="dcg_X", event_type="created",
            payload_json='{"item_count": 2}', created_by="test-user",
        )
        repo.save_canonicalization_event(e)
        stmt = conn.cursor_obj.statements[0]
        self.assertIn("canonicalization_events", stmt.sql)

    def test_list_canonical_questions(self):
        from question_bank.repository import PostgresQuestionBankRepository

        conn = self._make_fake_connection(FakeCursor(rows=[
            ("cqn_1", "fp1", "qb_1", "", "", "", "", None, "active", "dcg_1",
             "2026-01-01", "2026-01-01"),
        ]))
        repo = PostgresQuestionBankRepository(conn)
        results = repo.list_canonical_questions(limit=10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "cqn_1")

    def test_list_canonical_questions_with_status_filter(self):
        from question_bank.repository import PostgresQuestionBankRepository

        conn = self._make_fake_connection(FakeCursor(rows=[
            ("cqn_1", "fp1", "qb_1", "", "", "", "", None, "reverted", "dcg_1",
             "2026-01-01", "2026-01-01"),
        ]))
        repo = PostgresQuestionBankRepository(conn)
        results = repo.list_canonical_questions(status="reverted", limit=10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "reverted")

    def test_get_canonical_question_returns_full_detail(self):
        from question_bank.repository import PostgresQuestionBankRepository

        fake_cursor = FakeCursor()
        fake_cursor.setup_responses([
            [
                ("cqn_1", "fp1", "qb_1", "", "", "", "", None, "active", "dcg_1",
                 "2026-01-01", "2026-01-01"),
            ],
            [
                ("var1", "cqn_1", None, "paper_01", "candidate",
                 "paper_01#一#1", "abc", "", "", True, "2026-01-01"),
            ],
        ])
        conn = self._make_fake_connection(fake_cursor)
        repo = PostgresQuestionBankRepository(conn)
        result = repo.get_canonical_question("cqn_1")
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "cqn_1")
        self.assertEqual(len(result["variants"]), 1)
        self.assertEqual(result["variants"][0]["paper_id"], "paper_01")

    def test_rollback_canonical_updates_status(self):
        from question_bank.repository import PostgresQuestionBankRepository

        conn = self._make_fake_connection()
        repo = PostgresQuestionBankRepository(conn)
        repo.rollback_canonical("cqn_X", "test-user")

        update_stmts = [
            s for s in conn.cursor_obj.statements
            if "UPDATE" in s.sql.upper()
        ]
        self.assertEqual(len(update_stmts), 2)
        self.assertIn("reverted", update_stmts[0].params.get("status", ""))

    def test_rollback_writes_event(self):
        from question_bank.repository import PostgresQuestionBankRepository

        conn = self._make_fake_connection()
        repo = PostgresQuestionBankRepository(conn)
        repo.rollback_canonical("cqn_X", "test-user")

        insert_evt = [
            s for s in conn.cursor_obj.statements
            if "canonicalization_events" in s.sql
        ]
        self.assertEqual(len(insert_evt), 1)
        self.assertEqual(insert_evt[0].params["event_type"], "reverted")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class ExecutedStatement:
    def __init__(self, sql: str, params: dict):
        self.sql = sql
        self.params = params

    @property
    def table(self) -> str:
        import re
        m = re.search(
            r"(?:INSERT\s+INTO|DELETE\s+FROM|UPDATE)\s+(\w+)",
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

    def execute(self, sql: str, params: dict = None):
        self.statements.append(ExecutedStatement(sql, params or {}))

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
