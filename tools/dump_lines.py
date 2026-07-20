with open(r'c:\Users\DanOg\Documents\my-docs\coding-stuff\steam-backlog\js\dashboard-insights.js', 'r', encoding='utf-8') as f:
    lines = f.readlines()
out = []
for i in range(1229, min(1242, len(lines))):
    out.append(f"{i+1}: {lines[i].rstrip()}")
with open(r'c:\Users\DanOg\Documents\my-docs\coding-stuff\steam-backlog\tools\braces_output.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print('Written to tools/braces_output.txt')
