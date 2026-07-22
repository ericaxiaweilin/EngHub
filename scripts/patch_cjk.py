path = '/app/core/capabilities/bom/truth_aggregation.py'
with open(path, 'r') as f:
    lines = f.readlines()

target_idx = None
for i, line in enumerate(lines):
    if line.strip() == 'if op == "contains":' and i > 400:
        target_idx = i
        break

if target_idx is None:
    print('ERROR: target line not found')
    exit(1)

print(f'Found at line {target_idx+1}: {lines[target_idx].rstrip()}')
print(f'Next: {lines[target_idx+1].rstrip()} | {lines[target_idx+2].rstrip()}')

indent = '            '
new_lines = [
    indent + '# CJK-variant-aware matching (simplified + traditional)\n',
    indent + '_cv = _text_variants(value)\n',
    indent + 'if len(_cv) > 1:\n',
    indent + '    _terms = []\n',
    indent + '    for _v in _cv:\n',
    indent + '        _terms.append(f"{expression} ILIKE %s")\n',
    indent + '        params.append(f"%{_v}%")\n',
    indent + '    clauses.append("(" + " OR ".join(_terms) + ")")\n',
    indent + 'else:\n',
    indent + '    clauses.append(f"{expression} ILIKE %s")\n',
    indent + '    params.append(f"%{value}%")\n',
]

lines[target_idx+1:target_idx+3] = new_lines

with open(path, 'w') as f:
    f.writelines(lines)
print('PATCHED OK')
