import os
import uuid
from pathlib import Path
from typing import Protocol

from PIL import Image

from app.errors import AppError


class StorageProvider(Protocol):
    def save_image(self, owner_id: uuid.UUID, image: Image.Image) -> tuple[str, int]: ...
    def resolve(self, key: str) -> Path: ...
    def delete(self, key: str) -> None: ...


class LocalStorageProvider:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def resolve(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise AppError("invalid_storage_key", 400)
        return path

    def save_image(self, owner_id: uuid.UUID, image: Image.Image) -> tuple[str, int]:
        key = f"{owner_id}/{uuid.uuid4()}.png"
        path = self.resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        try:
            image.save(temporary, format="PNG")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return key, path.stat().st_size

    def delete(self, key: str) -> None:
        self.resolve(key).unlink(missing_ok=True)
