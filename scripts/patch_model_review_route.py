"""Patch: Fix _after_model_review routing for convergence.

When evidence exists (evidence_count > 0), force route to 'answer' even if
model_review action is not 'accept'. Retrying the same query will not produce
narrower results — the connector already converged.
"""

path = '/app/core/semantic_runtime/langgraph_business_mainline.py'
with open(path, 'r') as f:
    content = f.read()

old = '''def _after_model_review(state: BusinessMainlineState) -> str:
    review = _mapping(state.get("model_review"))
    if (
        _text(review.get("status")).casefold() == "reviewed"
        and _text(review.get("action")).casefold() == "accept"
    ):
        return "answer"
    return "interactive_correction"'''

new = '''def _after_model_review(state: BusinessMainlineState) -> str:
    review = _mapping(state.get("model_review"))
    if (
        _text(review.get("status")).casefold() == "reviewed"
        and _text(review.get("action")).casefold() == "accept"
    ):
        return "answer"
    # Convergence: when truth source returned evidence, accept and let the
    # answer node compose a qualified response. Retrying the same query will
    # not produce narrower results - the connector already converged.
    verification = _mapping(state.get("verification_receipt"))
    evidence_count = int(
        verification.get("evidence_count")
        or verification.get("evidence_sample_count")
        or 0
    )
    if evidence_count > 0:
        return "answer"
    return "interactive_correction"'''

if old in content:
    content = content.replace(old, new)
    with open(path, 'w') as f:
        f.write(content)
    print('[OK] Patched _after_model_review: evidence>0 forces answer (convergence)')
else:
    print('[FAIL] Pattern not found')
    # Debug
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'def _after_model_review' in line:
            print(f'  Found at line {i+1}')
            for j in range(i, min(i+10, len(lines))):
                print(f'    {j+1}: {lines[j]}')
            break
