import subprocess
import os

os.chdir(r'c:\Users\DanOg\Documents\my-docs\coding-stuff\steam-backlog')
result = subprocess.run(['git', 'show', 'HEAD:js/dashboard-insights.js'], capture_output=True, text=True)
head_content = result.stdout

with open(r'c:\Users\DanOg\Documents\my-docs\coding-stuff\steam-backlog\js\dashboard-insights.js', 'r', encoding='utf-8') as f:
    wc_content = f.read()

head_opens = head_content.count('{')
head_closes = head_content.count('}')
wc_opens = wc_content.count('{')
wc_closes = wc_content.count('}')

with open(r'c:\Users\DanOg\Documents\my-docs\coding-stuff\steam-backlog\tools\diff_result.txt', 'w', encoding='utf-8') as f:
    f.write(f'HEAD: opens={head_opens}, closes={head_closes}, diff={head_opens - head_closes}\n')
    f.write(f'WC:   opens={wc_opens}, closes={wc_closes}, diff={wc_opens - wc_closes}\n')
    # Also check if HEAD has the same bug
    head_lines = head_content.split('\n')
    f.write(f'HEAD line count: {len(head_lines)}\n')
    head_depth = 0
    for i, line in enumerate(head_lines):
        for c in line:
            if c == '{': head_depth += 1
            elif c == '}': head_depth -= 1
        if head_depth < 0 and i < 1240:
            f.write(f'HEAD imbalance at line {i+1}: depth={head_depth}\n')
