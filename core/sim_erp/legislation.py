"""
Legislation pack loading and hashing helpers.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict


class LegislationCatalog:
    def __init__(self, base_path: Path | None = None):
        self.base_path = base_path or Path(__file__).resolve().parent / "data" / "packs"

    def load_pack(self, pack_name: str) -> Dict[str, Any]:
        path = self.base_path / f"{pack_name}.json"
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def hash_pack(self, pack_name: str) -> str:
        payload = self.load_pack(pack_name)
        normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(normalized.encode("utf-8")).hexdigest()
