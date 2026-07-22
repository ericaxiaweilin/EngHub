"""Patch: Change multi-token free text from AND to OR for fuzzy convergence.

Architecture principle: connector layer retrieves broadly (OR),
model review layer narrows with intelligence.
Also patch search_aggregation_engine.py with same logic.
"""
import re

# === Patch 1: truth_aggregation.py - _append_text_search ===
path1 = '/app/core/capabilities/bom/truth_aggregation.py'
with open(path1, 'r') as f:
    content = f.read()

old_func = '''def _append_text_search(
    clauses: List[str],
    params: List[Any],
    value: Any,
    *,
    mode: str = "contains",
) -> None:
    tokens = _free_text_tokens(value)
    if not tokens:
        return
    # Multi-token free text is an AND of independent contains clauses.
    for token in tokens:
        _append_text_token_clause(clauses, params, token, mode=mode)'''

new_func = '''def _append_text_search(
    clauses: List[str],
    params: List[Any],
    value: Any,
    *,
    mode: str = "contains",
) -> None:
    tokens = _free_text_tokens(value)
    if not tokens:
        return
    if len(tokens) == 1:
        _append_text_token_clause(clauses, params, tokens[0], mode=mode)
        return
    # Fuzzy convergence: multi-token free text uses OR across tokens.
    # Architecture: connector retrieves broadly, model review narrows.
    # Each token still gets CJK-variant expansion via _append_text_token_clause.
    _or_groups: List[str] = []
    for token in tokens:
        variants = _text_variants(token)
        if not variants:
            continue
        if mode == "prefix":
            patterns = [f"{item}%" for item in variants]
        else:
            patterns = [f"%{item}%" for item in variants]
        _terms = []
        for pattern in patterns:
            _terms.append("COALESCE(b.description, '') ILIKE %s")
            params.append(pattern)
        _or_groups.append("(" + " OR ".join(_terms) + ")")
    if _or_groups:
        clauses.append("(" + " OR ".join(_or_groups) + ")")'''

if old_func in content:
    content = content.replace(old_func, new_func)
    with open(path1, 'w') as f:
        f.write(content)
    print(f'[OK] Patched {path1}: _append_text_search AND->OR')
else:
    print(f'[WARN] {path1}: exact old_func not found, trying line-based patch')
    # Fallback: find and replace by line markers
    lines = content.split('\n')
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if 'def _append_text_search(' in line:
            start_idx = i
        if start_idx is not None and i > start_idx and line.strip().startswith('def '):
            end_idx = i
            break
    if start_idx is not None:
        if end_idx is None:
            end_idx = len(lines)
        # Find the actual end (before next def)
        new_lines = lines[:start_idx] + new_func.split('\n') + ['', ''] + lines[end_idx:]
        with open(path1, 'w') as f:
            f.write('\n'.join(new_lines))
        print(f'[OK] Patched {path1} via line-based replacement (lines {start_idx+1}-{end_idx+1})')
    else:
        print(f'[FAIL] Could not find _append_text_search in {path1}')

# === Patch 2: search_aggregation_engine.py - same pattern ===
path2 = '/app/core/search_aggregation_engine.py'
try:
    with open(path2, 'r') as f:
        content2 = f.read()
    
    # Check if it has similar AND-token logic
    if '_free_text_tokens' in content2 and 'AND' in content2:
        # Find the equivalent function
        old2 = '    # Multi-token free text is an AND of independent contains clauses.\n    for token in tokens:\n        _append_text_token_clause(clauses, params, token, mode=mode)'
        if old2 in content2:
            new2 = '''    if len(tokens) == 1:
        _append_text_token_clause(clauses, params, tokens[0], mode=mode)
        return
    # Fuzzy convergence: multi-token free text uses OR across tokens.
    _or_groups: List[str] = []
    for token in tokens:
        variants = _text_variants(token)
        if not variants:
            continue
        if mode == "prefix":
            patterns = [f"{item}%" for item in variants]
        else:
            patterns = [f"%{item}%" for item in variants]
        _terms = []
        for pattern in patterns:
            _terms.append("COALESCE(b.description, '') ILIKE %s")
            params.append(pattern)
        _or_groups.append("(" + " OR ".join(_terms) + ")")
    if _or_groups:
        clauses.append("(" + " OR ".join(_or_groups) + ")")'''
            content2 = content2.replace(old2, new2)
            with open(path2, 'w') as f:
                f.write(content2)
            print(f'[OK] Patched {path2}: AND->OR')
        else:
            print(f'[SKIP] {path2}: pattern not found (may differ)')
    else:
        print(f'[SKIP] {path2}: no _free_text_tokens AND pattern')
except FileNotFoundError:
    print(f'[SKIP] {path2}: file not found')

print('\nDone.')
