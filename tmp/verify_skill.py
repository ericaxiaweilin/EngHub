import sys, json
d = json.load(sys.stdin)
mode = sys.argv[1] if len(sys.argv) > 1 else "matrix"
if mode == "matrix":
    print("员工数:", len(d))
    total_skills = sum(len(e.get("skills", [])) for e in d)
    print("技能记录总数:", total_skills)
    if d:
        e0 = d[0]
        print("样例员工:", e0.get("user_id"), e0.get("name"), e0.get("department"), "技能数:", len(e0.get("skills", [])))
        if e0.get("skills"):
            print("样例技能:", json.dumps(e0["skills"][0], ensure_ascii=False, default=str))
else:
    print("到期认证数:", len(d))
    for r in d[:3]:
        print(" ", json.dumps(r, ensure_ascii=False, default=str))
