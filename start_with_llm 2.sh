#!/bin/bash
# AgnesCode startup script with LLM gateway configuration (litellm)
# This script sets up the necessary environment variables before launching AgnesCode

echo "Starting AgnesCode with LLM Gateway (litellm) configuration..."

# Set required environment variables for the local litellm gateway
export AGNES_DEFAULT_PROVIDER="litellm"
export LLM_GATEWAY_URL="http://127.0.0.1:14040"    # Local litellm gateway (mapped from Docker container)
export LLM_MODEL="deepseek-v4-pro"                # Or deepseek-v4-flash, qwen-max, etc.
export LLM_API_KEY="sk-engflow-gateway-dev"       # Master key from model-stack-gateway

# Verify the gateway is reachable (health check with auth)
echo "Checking gateway connectivity..."
if python3 -c "import urllib.request, json; req = urllib.request.Request('http://127.0.0.1:14040/v1/models', headers={'Authorization': 'Bearer sk-engflow-gateway-dev', 'User-Agent': 'Mozilla/5.0'}); resp = urllib.request.urlopen(req, timeout=5); data = json.loads(resp.read()); print(f'✅ Found {len(data.get(\"data\", []))} models')" 2>/dev/null; then
    echo "✅ Litellm gateway is reachable at http://127.0.0.1:14040"
else
    echo "❌ Warning: May not be able to connect to litellm gateway at http://127.0.0.1:14040"
fi

echo ""
echo "Environment variables:"
echo "  AGNES_DEFAULT_PROVIDER=$AGNES_DEFAULT_PROVIDER"
echo "  LLM_GATEWAY_URL=$LLM_GATEWAY_URL"
echo "  LLM_MODEL=$LLM_MODEL"
echo "  LLM_API_KEY=[hidden]"
echo ""

# Verify the gateway is reachable (health check)
echo "Checking gateway connectivity..."
if python3 -c "import urllib.request; req = urllib.request.Request('http://100.96.188.77:14041/health', headers={'User-Agent': 'Mozilla/5.0'}); resp = urllib.request.urlopen(req, timeout=5); data = __import__('json').load(resp); print('Status:', data.get('status'))" 2>/dev/null; then
    echo "✅ Server gateway is reachable at http://100.96.188.77:14041 (healthy)"
else
    echo "❌ Warning: May not be able to connect to server gateway at http://100.96.188.77:14041"
fi

echo ""
echo "Environment variables:"
echo "  AGNES_DEFAULT_PROVIDER=$AGNES_DEFAULT_PROVIDER"
echo "  LLM_GATEWAY_URL=$LLM_GATEWAY_URL"
echo "  LLM_MODEL=[${LLM_MODEL:-not set}]"
echo "  LLM_API_KEY=[${LLM_API_KEY:-not set}]"
echo ""

# Verify the gateway is reachable
echo "Checking gateway connectivity..."
if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:14041/v1/models', timeout=5)" 2>/dev/null; then
    echo "✅ Gateway is reachable at http://127.0.0.1:14041"
else
    echo "❌ Warning: Gateway may not be running or accessible at http://127.0.0.1:14041"
fi

echo ""
echo "Environment variables:"
echo "  AGNES_DEFAULT_PROVIDER=$AGNES_DEFAULT_PROVIDER"
echo "  LLM_GATEWAY_URL=$LLM_GATEWAY_URL"
echo "  LLM_MODEL=$LLM_MODEL"
echo "  LLM_API_KEY=[hidden]"
echo ""

# Launch AgnesCode
echo "Launching AgnesCode..."
/Applications/AgnesCode.app/Contents/MacOS/AgnesCode "$@"
