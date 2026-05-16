import tempfile
import unittest
from pathlib import Path

from question_bank.domain.models import Question
from question_bank.storage import (
    FakeObjectStorage,
    LocalAssetUploader,
    ObjectStorageAsset,
    attach_uploaded_asset,
)


class ObjectStorageTest(unittest.TestCase):
    def test_fake_storage_records_uploaded_file_and_returns_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "figure.png"
            image_path.write_bytes(b"png-bytes")
            storage = FakeObjectStorage(bucket="question-bank-assets")

            url = storage.upload_file(image_path, "papers/paper_001/q_001/figure.png", "image/png")

        self.assertEqual(url, "s3://question-bank-assets/papers/paper_001/q_001/figure.png")
        self.assertEqual(storage.objects["papers/paper_001/q_001/figure.png"], b"png-bytes")
        self.assertEqual(storage.content_types["papers/paper_001/q_001/figure.png"], "image/png")

    def test_asset_uploader_builds_stable_question_asset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "figure.png"
            image_path.write_bytes(b"png-bytes")
            storage = FakeObjectStorage(bucket="question-bank-assets")
            uploader = LocalAssetUploader(storage=storage)

            asset = uploader.upload_question_asset(
                paper_id="paper_001",
                question_id="q_001",
                file_path=image_path,
                asset_type="geometry",
                page=2,
                bbox=(1, 2, 3, 4),
            )

        self.assertIsInstance(asset, ObjectStorageAsset)
        self.assertEqual(asset.id, "q_001_figure")
        self.assertEqual(asset.type, "geometry")
        self.assertEqual(asset.storage_url, "s3://question-bank-assets/papers/paper_001/q_001/figure.png")
        self.assertEqual(asset.page, 2)
        self.assertEqual(asset.bbox, (1, 2, 3, 4))

    def test_attach_uploaded_asset_adds_question_asset_to_question(self):
        question = Question(id="q_001", question_type="short_answer", stem_latex="如图")
        asset = ObjectStorageAsset(
            id="q_001_figure",
            type="geometry",
            storage_url="s3://question-bank-assets/papers/paper_001/q_001/figure.png",
        )

        attach_uploaded_asset(question, asset)

        self.assertEqual(len(question.assets), 1)
        self.assertEqual(question.assets[0].id, "q_001_figure")
        self.assertEqual(question.assets[0].storage_url, asset.storage_url)


if __name__ == "__main__":
    unittest.main()
