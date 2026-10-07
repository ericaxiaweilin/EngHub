"""只读接口巡检（回归用）。

遍历 openapi 里所有 GET，**参数值从库里取真实存在的主键**（employee→users、
schedule→aps_schedules…），并对配置里的每个工厂各跑一遍；按状态码归类。

用法（服务器上）::

    ENGHUB_PROBE_USER=… ENGHUB_PROBE_PASSWORD=… python3 scripts/api_read_probe.py

ENGHUB_BASE 默认 http://localhost:18888；ENGHUB_PROBE_FACTORIES 默认两个厂。
只发 GET 且跳过名字像写入/触发重计算的路径，所以不产生业务副作用，但确实执行读查询。

价值：静态 grep 看不见"路由调用服务上不存在的方法/库里不存在的列"——这类问题
只有真的打一次才暴露（首轮就靠它挖出 12 个必 500 的端点）。
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

BASE = os.environ.get('ENGHUB_BASE', 'http://localhost:18888')
FACTORIES = [f for f in os.environ.get('ENGHUB_PROBE_FACTORIES', 'FAC_MECH_001,FAC_ELEC_DEMO_2026').split(',') if f]

# 参数名 -> (取值的 SQL 列表)，按顺序尝试，取第一个能查到的
LOOKUPS = {
    'factory': ["SELECT factory_id FROM stations WHERE factory_id = :f LIMIT 1"],
    'employee': ["SELECT id FROM users LIMIT 1", "SELECT id FROM hr_employees LIMIT 1"],
    'user': ["SELECT id FROM users LIMIT 1"],
    'plan': ["SELECT id FROM pp_plans LIMIT 1", "SELECT plan_code FROM pp_plans LIMIT 1"],
    'schedule': ["SELECT id FROM aps_schedules ORDER BY version_number DESC LIMIT 1"],
    'task': ["SELECT id FROM aps_schedule_tasks LIMIT 1", "SELECT id FROM equipment_downtime LIMIT 1"],
    'work_order': ["SELECT id FROM work_orders LIMIT 1"],
    'wo': ["SELECT id FROM work_orders LIMIT 1"],
    'station': ["SELECT station_code FROM stations LIMIT 1", "SELECT id FROM stations LIMIT 1"],
    'equipment': ["SELECT id FROM equipment LIMIT 1"],
    'product': ["SELECT product_id FROM work_orders WHERE product_id IS NOT NULL LIMIT 1"],
    'material': ["SELECT id FROM materials LIMIT 1", "SELECT material_code FROM materials LIMIT 1"],
    'order': ["SELECT id FROM sales_orders LIMIT 1"],
    'case': ["SELECT id FROM capa_cases LIMIT 1"],
    'inspection': ["SELECT id FROM quality_inspections LIMIT 1"],
    'report': ["SELECT id FROM production_reports LIMIT 1"],
    'defect': ["SELECT id FROM defect_records LIMIT 1"],
    'routing': ["SELECT id FROM routings LIMIT 1", "SELECT id FROM routing_templates LIMIT 1"],
    'skill': ["SELECT id FROM skills LIMIT 1"],
    'role': ["SELECT id FROM roles LIMIT 1"],
    'supplier': ["SELECT id FROM suppliers LIMIT 1", "SELECT supplier_id FROM suppliers LIMIT 1"],
    'purchase': ["SELECT id FROM purchase_requests LIMIT 1"],
    'ticket': ["SELECT id FROM andon_tickets LIMIT 1", "SELECT id FROM tms_tasks LIMIT 1"],
    'alert': ["SELECT id FROM production_alerts LIMIT 1"],
    'warehouse': ["SELECT id FROM warehouses LIMIT 1"],
    'batch': ["SELECT id FROM materials LIMIT 1"],
    'line': ["SELECT station_code FROM stations LIMIT 1"],
    'center': ["SELECT station_code FROM stations LIMIT 1"],
    'category': ["SELECT station_type FROM stations WHERE station_type IS NOT NULL LIMIT 1"],
    'date': [None],
    'approval': ["SELECT id FROM rush_order_approvals LIMIT 1", "SELECT id FROM ai_action_approvals LIMIT 1"],
    'session': ["SELECT id FROM chat_sessions LIMIT 1"],
    'request': ["SELECT request_id FROM chat_messages WHERE request_id IS NOT NULL LIMIT 1"],
    'fai': ["SELECT id FROM quality_inspections WHERE inspect_type='FAI' LIMIT 1"],
    'emp': ["SELECT id FROM hr_employees LIMIT 1"],
    'sot': ["SELECT id FROM standard_operation_times LIMIT 1"],
    'lba': ["SELECT id FROM line_balance_analyses LIMIT 1"],
    'pa': ["SELECT id FROM process_analyses LIMIT 1"],
    'process_analysis': ["SELECT id FROM process_analyses LIMIT 1"],
    'workbook': ["SELECT id FROM workbooks LIMIT 1"],
    'group': ["SELECT id FROM chat_sessions LIMIT 1"],
    'part_number': ["SELECT material_code FROM bom_items LIMIT 1"],
    'model_name': ["SELECT DISTINCT model_name FROM bom_items WHERE model_name IS NOT NULL LIMIT 1"],
    'model': ["SELECT product_id FROM products LIMIT 1", "SELECT code FROM products LIMIT 1"],
    'id': ["SELECT id FROM work_orders LIMIT 1"],
}


# 自由文本类参数：给一个合理取值而不是跳过 —— 目的不是查出数据，是看它会不会崩
TEXT_DEFAULTS = {
    'year': '2026',
    'q': 'A',
    'question': '今天产量多少',
    'topic': '焊接',
    'fault_type': '主轴振动异常',
    'target_level': '2',
    'action': 'view',
    'event_key': 'equipment_breakdown',
    'from_date': '2026-10-01',
    'to_date': '2026-10-07',
    'date': '2026-10-07',
    'operator_id': None,
    'product_id': None,
    'station_id': None,
    'start_date': '2026-09-01',
    'end_date': '2026-10-07',
}



SKIP_WORDS = ('sync', 'refresh', 'generate', 'backfill', 'trigger', 'migrate', 'recompute',
              'run_', 'recalculate', 'warmup', 'restart', 'export', 'download', 'file')


def psql(sql, factory=None):
    if factory is not None:
        sql = sql.replace(':f', "'%s'" % factory)
    out = subprocess.run(['docker', 'exec', '-i', 'docker-postgres-1', 'psql', '-U', 'enghub', '-d', 'enghub',
                          '-A', '-t', '-c', sql], capture_output=True, text=True)
    if out.returncode != 0:
        return ''
    lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
    return lines[0] if lines else ''


_cache = {}


def value_for(name, factory):
    key = (str(name).lower(), factory)
    if key in _cache:
        return _cache[key]
    if name in ('from_date',):
        _cache[key] = TEXT_DEFAULTS.get('from_date', '')
        return _cache[key]
    key = (name, factory)
    if key in _cache:
        return _cache[key]
    stem = re_root(name)
    result = ''
    for cand in LOOKUPS.get(stem, []):
        if cand is None:
            result = '2026-10-07'
            break
        result = psql(cand, factory)
        if result:
            break
    if not result and name.lower() in TEXT_DEFAULTS:
        # 自由文本参数：给一个合理值，目标是"它会不会崩"，不是"能不能查到数据"
        result = TEXT_DEFAULTS[name.lower()] or ''
    _cache[key] = result
    return result


def re_root(name):
    n = str(name).lower().rstrip('s')
    for prefix in LOOKUPS:
        if n == prefix or n.startswith(prefix):
            return prefix
    return n


form = urllib.parse.urlencode({
    'username': os.environ.get('ENGHUB_PROBE_USER', ''),
    'password': os.environ.get('ENGHUB_PROBE_PASSWORD', ''),
}).encode()
lr = urllib.request.Request(BASE + '/api/v1/auth/login', method='POST', data=form,
                            headers={'Content-Type': 'application/x-www-form-urlencoded'})
TOK = json.loads(urllib.request.urlopen(lr).read())['access_token']

spec = json.loads(urllib.request.urlopen(BASE + '/openapi.json').read())

rows = []
for factory in FACTORIES:
    for path, ops in sorted(spec.get('paths', {}).items()):
        if 'get' not in ops:
            continue
        low = path.lower()
        if any(w in low for w in SKIP_WORDS):
            continue
        query = {}
        path_params = {}
        blocked = None
        for p in (ops['get'].get('parameters') or []):
            name, where, required = p.get('name'), p.get('in'), p.get('required', False)
            if where == 'path':
                v = value_for(name, factory) or value_for(name, None)
                if not v:
                    blocked = name
                    break
                path_params[name] = v
                continue
            if name == 'factory_id':
                query[name] = factory
                continue
            if not required:
                continue
            v = value_for(name, factory) or value_for(name, None)
            if not v:
                blocked = name
                break
            query[name] = v
        if blocked:
            rows.append((factory, path, 'SKIP', '需要取不到值的参数 %s' % blocked))
            continue

        real = path
        for k, v in path_params.items():
            real = real.replace('{%s}' % k, urllib.parse.quote(str(v)))
        url = BASE + real + ('?' + urllib.parse.urlencode(query) if query else '')
        req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + TOK})
        try:
            r = urllib.request.urlopen(req, timeout=20)
            r.read(1024)
            rows.append((factory, real, r.status, 'ok'))
        except urllib.error.HTTPError as e:
            rows.append((factory, real, e.code, e.read().decode('utf-8', 'ignore')[:200].replace('\n', ' ')))
        except Exception as e:  # noqa: BLE001
            rows.append((factory, real, 'ERR', str(e)[:120]))

print('探测 %d 次（%d 个工厂），状态分布: %s' % (len(rows), len(FACTORIES), dict(Counter(str(x[2]) for x in rows))))
print('仍未覆盖:', sum(1 for x in rows if x[2] == 'SKIP'))
print()
print('=== 5xx / ERR（真故障）===')
for f, p, code, note in rows:
    if (isinstance(code, int) and code >= 500) or code == 'ERR':
        print('  [%s] %-62s %s %s' % (f, p[:62], code, note[:130]))
