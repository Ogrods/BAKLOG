"""Find the precise location of the extra closing brace in buildMarqueeItems."""
import re

with open(r'c:\Users\DanOg\Documents\my-docs\coding-stuff\steam-backlog\js\dashboard-insights.js', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Track brace depth per-line, skipping strings/template literals
depth = 0
in_template = False
in_string = False
string_char = None

for i, line in enumerate(lines):
    j = 0
    while j < len(line):
        ch = line[j]
        if in_template:
            if ch == '`':
                in_template = False
        elif in_string:
            if ch == '\\':
                j += 1  # skip escaped char
            elif ch == string_char:
                in_string = False
        else:
            if ch == '`':
                in_template = True
            elif ch in ('"', "'"):
                in_string = True
                string_char = ch
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
        j += 1
    if depth < 0:
        print(f"Depth went negative at line {i+1}: depth={depth}")
        print(f"  Content: {line.rstrip()[:120]}")
        depth = 0  # reset to find all issues
