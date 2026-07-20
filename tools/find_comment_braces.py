"""Find braces inside comments that confuse the brace counter."""
with open(r'c:\Users\DanOg\Documents\my-docs\coding-stuff\steam-backlog\js\dashboard-insights.js', encoding='utf-8') as f:
    content = f.read()

# Count only braces NOT in comments or strings
lines = content.split('\n')
in_block_comment = False
depth = 0

for i, line in enumerate(lines):
    j = 0
    while j < len(line):
        ch = line[j]
        if in_block_comment:
            if ch == '*' and j+1 < len(line) and line[j+1] == '/':
                in_block_comment = False
                j += 1
        elif ch == '/' and j+1 < len(line):
            if line[j+1] == '*':
                in_block_comment = True
                j += 1
            elif line[j+1] == '/':
                break  # skip rest of line
        elif ch in ('"', "'", '`'):
            # Skip string
            quote = ch
            j += 1
            while j < len(line):
                if line[j] == '\\':
                    j += 1
                elif line[j] == quote:
                    break
                j += 1
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
        j += 1
    if depth < 0 and i < 1240:
        print(f"Depth went negative at line {i+1}: depth={depth}")
        print(f"  Line: {line.rstrip()[:120]}")
        depth = 0

print(f"Final depth: {depth}")
