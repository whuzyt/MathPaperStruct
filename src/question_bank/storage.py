from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from question_bank.domain.models import QuestionAsset
from question_bank.domain.models import Question


class ObjectStorageProtocol(Protocol):
    def upload_file(self, file_path: Path, object_key: str, content_type: str) -> str:
        """Upload a local file and return its stable storage URL."""


@dataclass(slots=True)
class ObjectStorageAsset:
    id: str
    type: str
    storage_url: str
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    confidence: float = 1.0
    caption: str = ""

    def to_question_asset(self) -> QuestionAsset:
        return QuestionAsset(
            id=self.id,
            type=self.type,
            storage_url=self.storage_url,
            page=self.page,
            bbox=self.bbox,
            confidence=self.confidence,
            caption=self.caption,
        )


@dataclass(slots=True)
class FakeObjectStorage:
    bucket: str
    objects: dict[str, bytes] | None = None
    content_types: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.objects is None:
            self.objects = {}
        if self.content_types is None:
            self.content_types = {}

    def upload_file(self, file_path: Path, object_key: str, content_type: str) -> str:
        assert self.objects is not None
        assert self.content_types is not None
        self.objects[object_key] = file_path.read_bytes()
        self.content_types[object_key] = content_type
        return f"s3://{self.bucket}/{object_key}"


@dataclass(slots=True)
class MinIOObjectStorage:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    secure: bool = False

    def upload_file(self, file_path: Path, object_key: str, content_type: str) -> str:
        try:
            from minio import Minio
        except ImportError as exc:
            raise RuntimeError("minio is required for MinIO asset uploads.") from exc

        client = Minio(
            self.endpoint.removeprefix("http://").removeprefix("https://"),
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=self.secure,
        )
        if not client.bucket_exists(self.bucket):
            client.make_bucket(self.bucket)
        client.fput_object(self.bucket, object_key, str(file_path), content_type=content_type)
        return f"s3://{self.bucket}/{object_key}"


@dataclass(slots=True)
class LocalAssetUploader:
    storage: ObjectStorageProtocol

    def upload_question_asset(
        self,
        paper_id: str,
        question_id: str,
        file_path: Path,
        asset_type: str,
        page: int | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        confidence: float = 1.0,
        caption: str = "",
    ) -> ObjectStorageAsset:
        object_key = f"papers/{paper_id}/{question_id}/{file_path.name}"
        storage_url = self.storage.upload_file(file_path, object_key, _guess_content_type(file_path))
        return ObjectStorageAsset(
            id=f"{question_id}_{file_path.stem}",
            type=asset_type,
            storage_url=storage_url,
            page=page,
            bbox=bbox,
            confidence=confidence,
            caption=caption,
        )


def _guess_content_type(file_path: Path) -> str:
    return mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"


def attach_uploaded_asset(question: Question, asset: ObjectStorageAsset) -> Question:
    question.assets.append(asset.to_question_asset())
    return question
