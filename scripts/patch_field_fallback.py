"""Patch: Add field fallback convergence in query_bom_truth.

When part_number filter returns 0 results and the values are non-numeric
(like "T6", "T9"), automatically retry with model_name field.
Architecture: infrastructure converges to data, not errors.
"""

path = '/app/core/capabilities/bom/truth_aggregation.py'
with open(path, 'r') as f:
    content = f.read()

# Find the location after the main query execution in query_bom_truth
# where we can add the fallback logic. Look for the return statement pattern.
# The fallback should go right after the first execution returns 0 rows.

# Strategy: patch the _where_clause function to add field fallback for part_number
# Actually better: patch query_bom_truth to retry with model_name when part_number gives 0

# Find the safe_limit line in query_bom_truth and add fallback after the main execution
old_marker = '''    where_sql, params, executed_filters = _where_clause(
        company_id=_text(company_id),
        query_text=_text(query_text),
        filters=resolved_filters,
        predicate_constraints=predicate_constraints,
    )'''

new_marker = '''    # --- Field fallback convergence: part_number → model_name ---
    # When part_number filter contains non-numeric values (like "T6", "T9"),
    # the data likely lives in model_name. Auto-redirect for convergence.
    _pn_filter = resolved_filters.get("part_number")
    if _pn_filter is not None:
        _pn_val = _pn_filter.get("value") if isinstance(_pn_filter, dict) else _pn_filter
        _pn_items = []
        if isinstance(_pn_val, (list, tuple)):
            _pn_items = [str(v) for v in _pn_val if v]
        else:
            _pn_items = [s.strip() for s in str(_pn_val or "").replace(",", " ").split() if s.strip()]
        # If ALL items are non-numeric, redirect to model_name
        _all_non_numeric = all(not item.replace(".", "").replace("-", "").isdigit() for item in _pn_items) if _pn_items else False
        if _all_non_numeric and _pn_items:
            resolved_filters = dict(resolved_filters)
            resolved_filters["model_name"] = _pn_filter
            del resolved_filters["part_number"]
    # --- End field fallback ---

    where_sql, params, executed_filters = _where_clause(
        company_id=_text(company_id),
        query_text=_text(query_text),
        filters=resolved_filters,
        predicate_constraints=predicate_constraints,
    )'''

if old_marker in content:
    content = content.replace(old_marker, new_marker)
    with open(path, 'w') as f:
        f.write(content)
    print('[OK] Patched query_bom_truth: part_number→model_name field fallback for non-numeric values')
else:
    print('[FAIL] Could not find marker')
    # Debug
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'where_sql, params, executed_filters = _where_clause' in line:
            print(f'  Found at line {i+1}: {line.strip()}')
