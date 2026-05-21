"""
Audit trail construction and in-memory storage.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from .models import ArbiterResult, AuditRecord, PhysicalInput, PhysicalSnapshot, PluginExecutionRecord


class AuditTrail:
    def __init__(self, storage_path: Path | None = None):
        self._records: List[AuditRecord] = []
        self.storage_path = storage_path

    def create_record(
        self,
        physical_input: PhysicalInput,
        snapshot: PhysicalSnapshot,
        plugin_records: List[PluginExecutionRecord],
        arbiter_result: ArbiterResult,
        physics_core_version: str,
        plugin_manifest_hash: str,
        legislation_pack_hash: str,
        arbiter_version: str,
        optimizer_version: str = "manual",
        random_seed: Optional[int] = None,
    ) -> AuditRecord:
        input_hash = self._hash_payload(physical_input.model_dump(mode="json"))
        record = AuditRecord(
            simulation_id=str(uuid4()),
            simulation_input_hash=input_hash,
            physics_core_version=physics_core_version,
            plugin_manifest_hash=plugin_manifest_hash,
            legislation_pack_hash=legislation_pack_hash,
            arbiter_version=arbiter_version,
            optimizer_version=optimizer_version,
            random_seed=random_seed,
            snapshot=snapshot,
            plugin_records=plugin_records,
            arbiter_result=arbiter_result,
        )
        self._records.append(record)
        self._persist(record)
        return record

    def latest(self) -> Optional[AuditRecord]:
        if self._records:
            return self._records[-1]
        if not self.storage_path or not self.storage_path.exists():
            return None

        last_line = ""
        with self.storage_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last_line = line
        return AuditRecord.model_validate_json(last_line) if last_line else None

    def all(self) -> List[AuditRecord]:
        if self._records:
            return list(self._records)
        if not self.storage_path or not self.storage_path.exists():
            return []

        with self.storage_path.open("r", encoding="utf-8") as handle:
            return [AuditRecord.model_validate_json(line) for line in handle if line.strip()]

    @staticmethod
    def _hash_payload(payload) -> str:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(body.encode("utf-8")).hexdigest()

    def _persist(self, record: AuditRecord) -> None:
        if not self.storage_path:
            return

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json())
            handle.write("\n")
