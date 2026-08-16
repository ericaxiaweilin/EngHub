#!/usr/bin/env bash
# ═══ 前端部署门禁 v2：拦截"缺import/未定义引用"类 P0 ═══
# 用法: bash scripts/deploy_frontend.sh
set -euo pipefail
cd "$(dirname "$0")/.."
FRONTEND=frontend
BASE_URL="http://127.0.0.1:18888"
TS_BASELINE=scripts/tsc_baseline.txt

echo "════════ 前端部署门禁 ════════"

cd $FRONTEND
echo "[1/4] tsc 全量检查..."
npx tsc --noEmit > /tmp/tsc_out.txt 2>&1 || true
cd ..

# 基线文件（每次部署后自动更新，含全量错误）
if [ ! -f "$TS_BASELINE" ]; then
    grep "error TS" /tmp/tsc_out.txt > "$TS_BASELINE" || true
    echo "✓ 首次运行，已建立基线 $(wc -l < $TS_BASELINE) 条"
fi

# ── 新增错误检查（按 文件:行 归一化 diff）──
norm() { sed 's/^\([^(]*([0-9]*,[0-9]*)\).*/\1/' ; }
grep "error TS" /tmp/tsc_out.txt | norm | sort > /tmp/tsc_now.txt
grep "error TS" "$TS_BASELINE" | norm | sort > /tmp/tsc_base.txt
NEW=$(comm -23 /tmp/tsc_now.txt /tmp/tsc_base.txt | grep -c . || true)
if [ "$NEW" -gt 0 ]; then
    echo "✗ 拦截：$NEW 个新增 TS 错误（相对基线）:"
    comm -23 /tmp/tsc_now.txt /tmp/tsc_base.txt | head -10
    exit 1
fi
echo "✓ tsc 无新增错误（存量 $(wc -l < /tmp/tsc_base.txt) 个在基线）"

# ── 未定义引用检查（Cannot find name，重点：会崩页面的引用）──
grep "Cannot find name" /tmp/tsc_out.txt | norm | sort > /tmp/tsc_cfn.txt
grep "Cannot find name" "$TS_BASELINE" | norm | sort > /tmp/tsc_cfn_base.txt
NEW_CFN=$(comm -23 /tmp/tsc_cfn.txt /tmp/tsc_cfn_base.txt | grep -c . || true)
if [ "$NEW_CFN" -gt 0 ]; then
    echo "✗ 拦截：$NEW_CFN 个新增未定义引用（会崩页面！）:"
    comm -23 /tmp/tsc_cfn.txt /tmp/tsc_cfn_base.txt | head -10
    exit 1
fi
echo "✓ 无新增未定义引用"

echo "[2/4] vite build..."
npm --prefix $FRONTEND run build 2>&1 | tail -1

echo "[3/4] 部署到容器..."
rm -rf /tmp/frontend_dist_new
cp -r $FRONTEND/dist /tmp/frontend_dist_new
docker exec -u root enghub-backend-1 bash -c "rm -rf /app/frontend_dist/assets /app/frontend_dist/index.html" 2>/dev/null || true
docker cp /tmp/frontend_dist_new/. enghub-backend-1:/app/frontend_dist/
docker exec -u root enghub-backend-1 bash -c "chown -R 1000:1000 /app/frontend_dist" 2>/dev/null || true

echo "[4/4] 冒烟..."
code=$(curl -s -o /dev/null -w "%{http_code}" $BASE_URL/)
if [ "$code" = "200" ]; then
    echo "✓ 部署成功 HTTP 200"
else
    echo "✗ 冒烟失败 HTTP $code"; exit 1
fi

# 更新基线
grep "error TS" /tmp/tsc_out.txt > "$TS_BASELINE" || true
echo "════════ 部署门禁通过 ✅ ════════"
