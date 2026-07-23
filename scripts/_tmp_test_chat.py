import json, urllib.request, urllib.parse

BASE = "http://localhost:8000"

def post(path, data, token=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())

login_req = urllib.request.Request(
    BASE + "/api/v1/auth/login",
    data=urllib.parse.urlencode({"username": "admin", "password": "admin123"}).encode(),
    headers={"Content-Type": "application/x-www-form-urlencoded"})
with urllib.request.urlopen(login_req, timeout=30) as r:
    token = json.loads(r.read().decode())["access_token"]

questions = [
    "今天生产情况怎么样？",
    "今天生产情况怎么样？",
    "今天生产情况怎么样？",
    "查询在制工单",
    "最近有哪些不良品？",
]
for i, q in enumerate(questions, 1):
    payload = {"messages": [
        {"role": "assistant", "content": "你好！我是 EngHub MES 智能助手。"},
        {"role": "user", "content": q},
    ]}
    d = post("/api/v1/chat", payload, token)
    n = len(d.get("actions", []))
    reply = d.get("reply", "")
    vague = ("建议" in reply and ("看板" in reply or "日报" in reply)) or "实时看板" in reply or "日报中心" in reply
    tools = ",".join(a["tool"] for a in d.get("actions", []))
    print(f"第{i}次 [{q}] actions={n} degraded={d.get('degraded')} 模糊={'是⚠️' if vague else '否'} tools=[{tools}]")
    print(f"   前60字: {reply[:60].replace(chr(10), ' ')}")
