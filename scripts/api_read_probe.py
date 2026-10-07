"""只读接口巡检（回归用）。

遍历 openapi 里所有 GET，用库里真实主键逐个打一遍，把 5xx 与"代码按不存在的
接口/表结构写"这类问题列出来。用法（服务器上）::

    python3 scripts/api_read_probe.py

默认打 http://localhost:18888，可用 ENGHUB_BASE 覆盖。刻意跳过名字像会写入或
触发重计算的路径，所以不产生业务副作用；但它确实会执行读查询。

登录账号取环境变量 ENGHUB_PROBE_USER / ENGHUB_PROBE_PASSWORD。
"""
import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request

BASE = __import__("os").environ.get("ENGHUB_BASE", "http://localhost:18888")
FID = 'FAC_MECH_001'

SKIP_WORDS = ('sync', 'refresh', 'generate', 'backfill', 'trigger', 'migrate', 'recompute',
              'run_', 'recalculate', 'warmup', 'restart', 'export', 'download', 'file')

import os  # noqa: E402
form = urllib.parse.urlencode({'username': os.environ.get('ENGHUB_PROBE_USER', ''), 'password': os.environ.get('ENGHUB_PROBE_PASSWORD', '')}).encode()
lr = urllib.request.Request(BASE + '/api/v1/auth/login', method='POST', data=form,
                            headers={'Content-Type': 'application/x-www-form-urlencoded'})
TOK = json.loads(urllib.request.urlopen(lr).read())['access_token']


def psql(sql):
    out = subprocess.run(['docker', 'exec', '-i', 'docker-postgres-1', 'psql', '-U', 'enghub',
                          '-d', 'enghub', '-A', '-t', '-c', sql],
                         capture_output=True, text=True).stdout.strip()
    return out.splitlines()[-1].strip() if out else ''


# 用库里真实存在的主键，避免"404 被当成 bug"
IDS = {
    'work_order_id': psql("SELECT id FROM work_orders WHERE factory_id='%s' LIMIT 1" % FID),
    'order_id': psql("SELECT id FROM sales_orders WHERE factory_id='%s' LIMIT 1" % FID),
    'product_id': psql("SELECT product_id FROM work_orders WHERE factory_id='%s' AND product_id IS NOT NULL LIMIT 1" % FID),
    'equipment_id': psql("SELECT id FROM equipment WHERE factory_id='%s' LIMIT 1" % FID),
    'station_id': psql("SELECT station_code FROM stations WHERE factory_id='%s' LIMIT 1" % FID),
    'plan_id': psql("SELECT id FROM pp_plans LIMIT 1"),
    'schedule_id': psql("SELECT id FROM aps_schedules WHERE factory_id='%s' ORDER BY version_number DESC LIMIT 1" % FID),
    'task_id': psql("SELECT id FROM equipment_downtime LIMIT 1"),
    'case_id': psql("SELECT id FROM capa_cases LIMIT 1"),
    'inspection_id': psql("SELECT id FROM quality_inspections LIMIT 1"),
    'defect_id': psql("SELECT id FROM defect_records LIMIT 1"),
    'material_id': psql("SELECT id FROM materials LIMIT 1"),
    'routing_id': psql("SELECT id FROM routings LIMIT 1"),
    'user_id': psql("SELECT id FROM users LIMIT 1"),
}
IDS.update({'id': IDS.get('work_order_id') or '1', 'report_id': IDS.get('defect_id') or '1',
            'record_id': IDS.get('task_id') or '1', 'downtime_id': IDS.get('task_id') or '1'})

spec = json.loads(urllib.request.urlopen(BASE + '/openapi.json').read())
rows = []
for path, ops in sorted(spec.get('paths', {}).items()):
    if 'get' not in ops:
        continue
    low = path.lower()
    if any(w in low for w in SKIP_WORDS):
        continue
    params = ops['get'].get('parameters') or []
    query = {}
    path_params = {}
    missing_required = None
    for p in params:
        name = p.get('name')
        where = p.get('in')
        required = p.get('required', False)
        if where == 'path':
            if name in IDS and IDS[name]:
                path_params[name] = IDS[name]
            else:
                missing_required = name
                break
            continue
        if not required and name not in ('factory_id',):
            continue
        if name == 'factory_id':
            query[name] = FID
        elif name in IDS and IDS[name]:
            query[name] = IDS[name]
        elif name in ('limit', 'page_size', 'days', 'horizon_days'):
            query[name] = '10' if 'limit' in name or 'size' in name else '30'
        elif required:
            missing_required = name
            break
    if missing_required:
        rows.append((path, 'SKIP', '需要未提供的参数 %s' % missing_required))
        continue

    real = path
    for k, v in path_params.items():
        real = real.replace('{%s}' % k, urllib.parse.quote(str(v)))
    url = BASE + real + ('?' + urllib.parse.urlencode(query) if query else '')
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + TOK})
    try:
        r = urllib.request.urlopen(req, timeout=25)
        code = r.status
        r.read(2048)
        rows.append((real, code, 'ok'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'ignore')[:160].replace('\n', ' ')
        rows.append((real, e.code, body))
    except Exception as e:  # noqa: BLE001
        rows.append((real, 'ERR', str(e)[:140]))

from collections import Counter  # noqa: E402
c = Counter(str(x[1]) for x in rows)
print('探测 %d 个只读端点，状态分布: %s' % (len(rows), dict(c)))
print()
print('=== 5xx（真故障）===')
for p, code, note in rows:
    if isinstance(code, int) and code >= 500 or code == 'ERR':
        print('  %-70s %s %s' % (p[:70], code, note[:120]))
print()
print('=== 4xx 里值得看的（422/400/404 且路径带 id）===')
n = 0
for p, code, note in rows:
    if isinstance(code, int) and code in (400, 404, 422) and '{' not in p and n < 15:
        print('  %-70s %s %s' % (p[:70], code, note[:120]))
        n += 1
