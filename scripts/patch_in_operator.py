"""Patch: Fix 'in' operator to use ILIKE fuzzy matching for generalized fields.

For fields like model_name, the 'in' operator should use ILIKE (partial match)
instead of exact IN, because user shorthand "T6" must match "T6-AC-110V-500lbs".
This is consistent with the existing _GENERALIZE_EQUALS_FIELDS policy for 'equals'.
"""

path = '/app/core/capabilities/bom/truth_aggregation.py'
with open(path, 'r') as f:
    content = f.read()

old_in = '''        elif op == "in":
            # Support multi-value IN predicate (e.g. part_number IN (T6, T9))
            if isinstance(value, (list, tuple)):
                items = [_text(v) for v in value if _text(v)]
            else:
                items = [_text(v).strip() for v in _text(value).replace(",", " ").split() if _text(v).strip()]
            if not items:
                clauses.append("FALSE")
            else:
                placeholders = ", ".join(["%s"] * len(items))
                clauses.append(f"LOWER({expression}) IN ({placeholders})")
                params.extend([v.lower() for v in items])'''

new_in = '''        elif op == "in":
            # Support multi-value IN predicate (e.g. part_number IN (T6, T9))
            if isinstance(value, (list, tuple)):
                items = [_text(v) for v in value if _text(v)]
            else:
                items = [_text(v).strip() for v in _text(value).replace(",", " ").split() if _text(v).strip()]
            if not items:
                clauses.append("FALSE")
            elif field in _GENERALIZE_EQUALS_FIELDS:
                # Fuzzy convergence: user shorthand "T6" must match full model
                # names like "T6-AC-110V-500lbs". Use ILIKE OR for each item,
                # with CJK-variant expansion for non-ASCII tokens.
                _or_terms = []
                for _item in items:
                    _variants = _text_variants(_item)
                    for _v in _variants:
                        _or_terms.append(f"{expression} ILIKE %s")
                        params.append(f"%{_v}%")
                if _or_terms:
                    clauses.append("(" + " OR ".join(_or_terms) + ")")
                else:
                    clauses.append("FALSE")
            else:
                placeholders = ", ".join(["%s"] * len(items))
                clauses.append(f"LOWER({expression}) IN ({placeholders})")
                params.extend([v.lower() for v in items])'''

if old_in in content:
    content = content.replace(old_in, new_in)
    with open(path, 'w') as f:
        f.write(content)
    print('[OK] Patched: in operator now uses ILIKE for generalized fields (model_name, project_id)')
else:
    print('[FAIL] Could not find exact old_in pattern')
    # Debug: show what's around line 501
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'elif op == "in"' in line and i > 490:
            print(f'Found at line {i+1}')
            for j in range(i, min(i+14, len(lines))):
                print(f'  {j+1}: {lines[j]}')
            break
