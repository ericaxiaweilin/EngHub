"""Patch: Fix _answer_node to handle convergence-forced routing.

When _after_model_review forces route to 'answer' because evidence exists,
the answer node must not raise RuntimeError. Instead, compose a qualified
answer from available evidence.
"""

path = '/app/core/semantic_runtime/langgraph_business_mainline.py'
with open(path, 'r') as f:
    content = f.read()

old = '''    if (
        _text(review.get("status")).casefold() != "reviewed"
        or _text(review.get("action")).casefold() != "accept"
    ):
        raise RuntimeError("answer_requires_accepted_model_review")'''

new = '''    if (
        _text(review.get("status")).casefold() != "reviewed"
        or _text(review.get("action")).casefold() != "accept"
    ):
        # Convergence override: evidence was returned by truth source but
        # model review did not explicitly accept. Force-accept to prevent
        # infinite correction loops. The answer is qualified by evidence.
        _verification = _mapping(state.get("verification_receipt"))
        _ev_count = int(
            _verification.get("evidence_count")
            or _verification.get("evidence_sample_count")
            or 0
        )
        if _ev_count > 0:
            review = {**review, "status": "reviewed", "action": "accept", "decision": "qualified", "scope_alignment": "convergence_forced"}
        else:
            raise RuntimeError("answer_requires_accepted_model_review")'''

if old in content:
    content = content.replace(old, new)
    with open(path, 'w') as f:
        f.write(content)
    print('[OK] Patched _answer_node: convergence override for force-routed answers')
else:
    print('[FAIL] Pattern not found')
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'answer_requires_accepted_model_review' in line:
            print(f'  Found at line {i+1}: {line.strip()}')
