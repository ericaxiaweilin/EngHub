#!/usr/bin/env python3
"""一次性脚本：从 EngFlow bom_intelligence 全量同步 BOM 至机械厂。"""
import asyncio
import sys

from database.db_config import db_config
from api.services.bom_sync_service import BomSyncService, MECH_FACTORY_ID


async def main() -> int:
    async with db_config.session_factory() as db:
        svc = BomSyncService(db)
        result = await svc.full_sync(
            factory_id=MECH_FACTORY_ID,
            company_id="jvn_enterprise",
        )
    print(result)
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
