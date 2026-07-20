
with open(r'c:\Users\DanOg\Documents\my-docs\coding-stuff\steam-backlog\js\dashboard-insights.js', encoding='utf-8') as f:
    lines = f.readlines()

depth = 0
for i, line in enumerate(lines):
    # Remove string contents to avoid counting braces in strings
    # Simple approach: just count visible braces
    for c in line:
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
    if depth < 0:
        print(f"Imbalance at line {i+1}: depth={depth}")
        print(f"  Line: {line.rstrip()[:100]}")
        depth = 0

print(f"Final depth: {depth}")
