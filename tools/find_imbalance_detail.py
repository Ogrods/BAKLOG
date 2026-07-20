"""Find exact location of brace imbalance."""

with open(r'c:\Users\DanOg\Documents\my-docs\coding-stuff\steam-backlog\js\dashboard-insights.js', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')
in_block_comment = False

# Track depth per line (with full context handling)
depth = 0
line_starts_at = {}

for i, line in enumerate(lines):
    line_starts_at[i] = depth
    j = 0
    while j < len(line):
        ch = line[j]
        nxt = line[j+1] if j+1 < len(line) else ''
        
        if in_block_comment:
            if ch == '*' and nxt == '/':
                in_block_comment = False
                j += 1
        elif ch == '/' and nxt == '*':
            in_block_comment = True
            j += 1
        elif ch == '/' and nxt == '/':
            break  # rest of line is comment
        elif ch in ('"', "'", '`'):
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
    
    if depth < line_starts_at[i] and depth < 0:
        print(f"IMBALANCE at line {i+1}: depth dropped from {line_starts_at[i]} to {depth}")
        print(f"  Line: {line.rstrip()[:150]}")

print(f"Final depth: {depth}")
