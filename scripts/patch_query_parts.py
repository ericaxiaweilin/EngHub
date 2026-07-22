"""Patch: Fix _connector_query_parts dict key collision.

When multiple filters target the same attribute (e.g. name_or_description=T6
and name_or_description=T9), the dict key collision causes only the LAST value
to survive. Fix: merge same-attribute equals filters into an 'in' operator.

Architecture: fuzzy commands produce multiple entity references on the same
field. The infrastructure must converge (merge to IN) not silently drop data.
"""

path = '/app/core/semantic_runtime/governed_query_binder.py'
with open(path, 'r') as f:
    content = f.read()

old_func = '''def _connector_query_parts(
    semantic_plan: Mapping[str, Any],
) -> tuple[Dict[str, Any], str]:
    output: Dict[str, Any] = {}
    query_text = _text(semantic_plan.get("query_text"))
    query_text_field = _text(
        semantic_plan.get(
            "query_text_field"
        )
    )

    for item in (
        semantic_plan.get("filters")
        or []
    ):
        if not isinstance(item, Mapping):
            continue

        attribute = _text(
            item.get("attribute")
        )
        operator = _text(
            item.get("operator")
        ).casefold()
        value = item.get("value")

        if not attribute:
            continue

        if (
            query_text_field
            and attribute
            == query_text_field
            and not query_text
            and operator == "contains"
            and _text(value)
        ):
            query_text = _text(value)
            continue

        if operator != "equals":
            output[attribute] = {
                "operator": operator,
                "value": value,
            }
        else:
            output[attribute] = value

    return output, query_text'''

new_func = '''def _connector_query_parts(
    semantic_plan: Mapping[str, Any],
) -> tuple[Dict[str, Any], str]:
    output: Dict[str, Any] = {}
    query_text = _text(semantic_plan.get("query_text"))
    query_text_field = _text(
        semantic_plan.get(
            "query_text_field"
        )
    )

    for item in (
        semantic_plan.get("filters")
        or []
    ):
        if not isinstance(item, Mapping):
            continue

        attribute = _text(
            item.get("attribute")
        )
        operator = _text(
            item.get("operator")
        ).casefold()
        value = item.get("value")

        if not attribute:
            continue

        if (
            query_text_field
            and attribute
            == query_text_field
            and not query_text
            and operator == "contains"
            and _text(value)
        ):
            query_text = _text(value)
            continue

        if operator != "equals":
            # Merge with existing if same attribute already present
            if attribute in output:
                existing = output[attribute]
                existing_val = existing.get("value") if isinstance(existing, dict) else existing
                existing_op = existing.get("operator") if isinstance(existing, dict) else "equals"
                # Combine into in-operator for multi-value convergence
                if isinstance(existing_val, (list, tuple)):
                    merged = list(existing_val) + [value]
                else:
                    merged = [existing_val, value]
                output[attribute] = {"operator": "in", "value": merged}
            else:
                output[attribute] = {
                    "operator": operator,
                    "value": value,
                }
        else:
            # Fuzzy convergence: multiple equals on same attribute → merge to in
            if attribute in output:
                existing = output[attribute]
                existing_val = existing.get("value") if isinstance(existing, dict) else existing
                existing_op = existing.get("operator") if isinstance(existing, dict) else "equals"
                if isinstance(existing_val, (list, tuple)):
                    merged = list(existing_val) + [value]
                else:
                    merged = [existing_val, value]
                output[attribute] = {"operator": "in", "value": merged}
            else:
                output[attribute] = value

    return output, query_text'''

if old_func in content:
    content = content.replace(old_func, new_func)
    with open(path, 'w') as f:
        f.write(content)
    print('[OK] Patched _connector_query_parts: same-attribute filters merge to IN operator')
else:
    print('[FAIL] Could not find exact old_func pattern')
    # Debug
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'def _connector_query_parts' in line:
            print(f'Found at line {i+1}')
            for j in range(i, min(i+5, len(lines))):
                print(f'  {j+1}: {lines[j]}')
            break
