# database/migrations

EngHub 的数据库迁移目录。

> ⚠️ **这个目录（逐个跑 `.sql`）重建不出生产库。** 动手前先读第 3 节。

## 1. 目录里有什么

| 东西 | 说明 |
|---|---|
| `NNN_*.sql` | 手写迁移，按**文件名字典序**执行 |
| `ledger_gaps.json` | 「台账有、仓库无」的迁移登记表（16 条，见 §3） |
| `baseline/schema_baseline_YYYYMMDD.sql` | 生产库当前形态的 schema 快照 **+ 台账种子**；新环境用它建库 |
| `../schema_contract.json` | 关键表/列清单，runner 跑完迁移后据此核对 |

## 2. 台账机制

runner 是 `scripts/schema_migrate.py`；台账表 `enghub_schema_migrations`
（`migration_name` PK + `checksum` SHA-256 + `applied_at`）。行为：

- 只处理版本号 **>= `MIN_MANAGED_VERSION = 42`** 的 `.sql`
  （常量在 `scripts/schema_migrate.py:25`，判断在 `:47`）。
  **042 以下的 44 个文件是故意不管的**，别当成漏记。
- 已在台账里 → 比对 checksum；不一致就 `RuntimeError("applied migration checksum changed")`。
- 不在台账里 → 执行 + 记台账。
- 跑完再按 `schema_contract.json` 核对表/列是否齐。

当前数量：仓库 **115** 个 `.sql`（其中 71 个 >= 42）/ 台账 **87** 行（全部 >= 42）。

## 3. ⚠️ 已知缺陷：账实分离（2026-10-11 审计）

**25 条已应用在生产库的迁移，仓库里没有源文件。** 处理情况：

- **9 条已从 git 历史找回**（sha256 与台账逐字节一致）：
  `058_user_password_reset_fields` `062_wms_material_volume` `063_wms_full_enhancement`
  `064_bom_factory_scope` `094_position_training_expand` `095_pmc_training_advanced`
  `096_pmc_training_question_types` `097_chat_memories` `098_chat_session_events`
- **16 条永久缺失**（从未进过 git，无法找回）→ 登记在 `ledger_gaps.json`：
  `065`–`070`、`071`–`077`、`079`、`080`、`081`

**后果**：新环境按仓库逐个跑 `.sql` **建不出生产库**（缺这 16 段 schema）。
**对策**：用 §4 的基线快照建库。

## 4. 新环境怎么建库

### 路径 A：建到「当前形态」（推荐）

```bash
createdb enghub
psql -U enghub -d enghub -f database/migrations/baseline/schema_baseline_20261011.sql
python scripts/schema_migrate.py      # 只补基线之后新增的迁移，通常 0 条
```

基线文件末尾**已经写了 87 行台账**，所以 runner 不会把 115 个 `.sql` 再跑一遍。

**不要删掉文件末尾那段 `INSERT INTO public.enghub_schema_migrations`。**
删了之后 runner 会**静默重跑全部 71 个受管迁移**（实测：台账清空后
`Applying migration` 行数 0 → 71）。当前这些迁移恰好都是幂等的所以没炸，
但只要以后有人写一个不幂等的迁移，就会当场报错或**重复写数据**。

> 注意 `public.` 前缀不能省：`pg_dump` 会在文件开头 `set_config('search_path','',false)`，
> 无限定名解析不到表。

### 路径 B：全新的空壳库

只适用于「不关心生产库历史、就要一个空壳」：空库 + `python scripts/schema_migrate.py`
（会跑 71 个受管迁移）。**建出来的库缺 §3 那 16 段 schema。**

## 5. 核对（改完迁移跑这个）

```bash
python scripts/check_migration_ledger.py           # 逐条报
python scripts/check_migration_ledger.py --quiet   # 一行摘要 + 退出码
```

三条判据：① 台账有、仓库无（**只有未登记的才报错**）② 内容与台账 checksum 漂移
③ 仓库有、台账无（只报 >= 42 的）。**退出码非 0 = 需要处理。**

### ⚠️ 部署注意：`scripts/` 不在 bind-mount 里

只有 `database/`、`api/`、`core/`、`main.py`、`engine_asgi.py`、`integrations/`、
`frontend_dist/` 是挂载的。容器里的 `/app/scripts/` 是**镜像里的旧快照** ——
实测冻结在 **2026-07-30**：比仓库**少 13 个脚本、多 1 个**，连 `schema_migrate.py`
都缺了 2026-08-22 才加的那行 `print("Applying migration: ...")`。

要在生产容器里跑核对器，得先拷进去：

```bash
docker cp scripts/check_migration_ledger.py enghub-backend-1:/app/scripts/
docker exec -w /app enghub-backend-1 python scripts/check_migration_ledger.py
```

`docker cp` 只进容器**可写层**，容器重建即丢；长期要靠重建镜像。
（脚本自己算 `ROOT = parents[1]`，所以必须落在 `/app/scripts/` 下，
拷到 `/tmp` 会 `ModuleNotFoundError: No module named 'database'`。）

## 6. 加新迁移的规矩

1. 版本号 **>= 42**，且**全局唯一**。
2. **必须幂等**（`CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`）——
   台账清空或基线重建时 runner 会把它们重跑一遍。
3. 写完**提交进 git**。没进 git 的迁移 = 下一个人重建不出这一段（§3 就是这么来的）。
4. 提交后跑一次 §5 的核对器。

### 关于编号重复

现有 115 个文件里有 **16 组版本号重复**：
`009 013 014 046 047 050 057 058 062 063 064 094 095 096 097 098`
（其中 **097、098 各有 3 个文件**）。
runner 用 `sorted(glob)` 即**文件名字典序**，所以同号文件之间的先后是**偶然的**，不是设计。
新迁移**不要再撞号**。

## 7. 相关文件

| 文件 | 作用 |
|---|---|
| `scripts/schema_migrate.py` | runner（`MIN_MANAGED_VERSION = 42`） |
| `scripts/check_migration_ledger.py` | 台账核对器（本目录 §5） |
| `database/schema_contract.json` | 表/列契约 |
| `scripts/apply_migration.py` | 一次性单文件工具，**硬编码文件名，不是 runner** |
