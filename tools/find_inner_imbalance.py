"""Find where depth goes below function entry depth inside buildMarqueeItems."""
with open(r'c:\Users\DanOg\Documents\my-docs\coding-stuff\steam-backlog\js\dashboard-insights.js', 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')
in_block_comment = False
depth = 0
func_start_line = None

for i, line in enumerate(lines):
    in_block_comment = False  # reset for proper per-line handling (simplified)
    
# Better approach: track depth line by line with an AST-like walk
depth = 0
start_depth = 0
func_start = None
problem_lines = []

for i, line in enumerate(lines):
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
            break
        elif ch in ('"', "'", '`'):
            quote = ch
            j += 1
            while j < len(line):
                if line[j] == '\\': j += 1
                elif line[j] == quote: break
                j += 1
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
        j += 1
    
    if 'function buildMarqueeItems' in line:
        func_start = i
        start_depth = depth
        print(f"Function starts at line {i+1}, depth before: {start_depth}")
    
    # Check if depth dropped below start_depth AFTER function start
    if func_start is not None and i > func_start and depth < start_depth and i < 1250:
        print(f"PROBLEM at line {i+1}: depth={depth} (started at {start_depth})")
        print(f"  Line: {line.rstrip()[:150]}")

print(f"\nFinal depth: {depth}, Function start depth: {start_depth}")
