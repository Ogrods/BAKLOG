"""Fix launch_persistent_profile close blocking pattern.

For each file:
1. Add 'import threading' to imports  
2. Change 'with launch_persistent_profile(...) as VAR:' -> 'VAR = launch_persistent_profile(...)' + 'try:'
3. Before the next top-level 'def'/'class' after the last 'return'/'raise' in the
   with block, insert 'finally:' + daemon close at the try indent level.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FIXES = [
    # (path, import_line_before, with_lineno_0based, def_lineno_0based)
    ("clients/nintendo_client.py", "import json", 334, 419),
    ("clients/nintendo_vgc.py", "import json", 356, 432),
    ("clients/amazon_web_client.py", "import json", 721, 766),
    ("fetchers/fetch_ubisoft_wishlist.py", "import json", 131, 150),
    ("auth/xbox_wishlist_session.py", "import time", 51, 96),
]

for path_rel, import_before, with_line, def_line in FIXES:
    path = ROOT / path_rel
    subprocess.run(["git", "checkout", "--", str(path)], capture_output=True, cwd=ROOT)
    
    lines = path.read_text(encoding="utf-8").split("\n")
    
    # 1. Add threading import
    for i, line in enumerate(lines):
        if line.strip() == import_before and "threading" not in line:
            lines.insert(i + 1, "import threading")
            # Adjust line numbers after insertion
            if with_line >= i + 1:
                with_line += 1
            if def_line >= i + 1:
                def_line += 1
            break
    
    # 2. Parse the with line to get var name and indent
    with_text = lines[with_line]
    m = re.match(r'^(\s*)with launch_persistent_profile\((.+?)\) as (\w+):', with_text.rstrip())
    if not m:
        # Multi-line with - need to combine
        combined = with_text
        j = with_line + 1
        while j < len(lines):
            combined += " " + lines[j].strip()
            if "):" in lines[j]:
                break
            j += 1
        m = re.match(r'^(\s*)with launch_persistent_profile\((.+?)\) as (\w+):', combined)
    
    if not m:
        print(f"{path_rel}: cannot parse with line")
        continue
    
    indent = m.group(1)
    args = m.group(2).strip()
    var = m.group(3)
    
    # Replace the with line with var = launch + try:
    lines[with_line] = f"{indent}{var} = launch_persistent_profile({args})"
    lines.insert(with_line + 1, f"{indent}try:")
    
    # Adjust def_line since we inserted a line
    def_line += 1
    
    # 3. Insert finally: before def_line (at match indent)
    final_indent = " " * len(indent)
    body_indent = " " * (len(indent) + 4)
    
    # Check: if def_line has a blank line before it, insert before the blank
    insert_pos = def_line
    if insert_pos > 0 and lines[insert_pos - 1].strip() == "":
        insert_pos = insert_pos - 1
    
    lines.insert(insert_pos, f"{body_indent}threading.Thread(target={var}.close, daemon=True).start()")
    lines.insert(insert_pos, f"{final_indent}finally:")
    lines.insert(insert_pos, "")
    
    content = "\n".join(lines)
    
    try:
        compile(content, str(path), "exec")
        path.write_text(content, encoding="utf-8")
        print(f"{path_rel}: OK (var={var}, indent={len(indent)})")
    except SyntaxError as e:
        print(f"{path_rel}: SYNTAX ERROR at line {e.lineno}: {e.msg}")
        # Show context
        err = e.lineno or 0
        for j in range(max(0, err-3), min(len(lines), err+3)):
            marker = ">>>" if j == err-1 else "   "
            print(f"  {marker} {j+1}: {lines[j]}")

# epic_wishlist and humble_wishlist have multi-line with blocks
# that need special handling
for path_rel, import_before in [
    ("fetchers/fetch_epic_wishlist.py", "import sys"),
    ("fetchers/fetch_humble_wishlist.py", "import sys"),
]:
    path = ROOT / path_rel
    subprocess.run(["git", "checkout", "--", str(path)], capture_output=True, cwd=ROOT)
    lines = path.read_text(encoding="utf-8").split("\n")
    
    # Add threading import
    for i, line in enumerate(lines):
        if line.strip() == import_before and "threading" not in line:
            lines.insert(i + 1, "import threading")
            break
    
    # Find multi-line with
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("with launch_persistent_profile(") and not s.rstrip().endswith(":"):
            # Multi-line - combine until ):
            combined = s
            j = i + 1
            while j < len(lines):
                combined += " " + lines[j].strip()
                if "):" in lines[j]:
                    break
                j += 1
            
            m = re.search(r'as (\w+)\):', combined)
            if not m:
                continue
            
            var = m.group(1)
            indent = re.match(r'^(\s*)', line).group(1)
            
            # Find the end of this function (next top-level def or class)
            func_indent = len(indent)
            end_func = len(lines)
            for k in range(i + 1, len(lines)):
                line = lines[k]
                stripped = line.strip()
                if stripped.startswith(("def ", "class ")) and (len(line) - len(line.lstrip())) <= func_indent:
                    end_func = k
                    break
            
            # Replace opening
            lines[i] = f"{indent}{var} = launch_persistent_profile("
            lines[i+1] = lines[i+1].lstrip()
            # Find the closing line with ):
            for k in range(i+1, j+1):
                if "):" in lines[k]:
                    lines[k] = lines[k].replace("):", ")\n" + indent + "try:")
                    break
            
            # Insert finally before end_func
            insert_pos = end_func
            if insert_pos > 0 and lines[insert_pos - 1].strip() == "":
                insert_pos -= 1
            close_line = (
                f"{' ' * (func_indent + 4)}threading.Thread"
                f"(target={var}.close, daemon=True).start()"
            )
            lines.insert(insert_pos, close_line)
            lines.insert(insert_pos, f"{' ' * func_indent}finally:")
            lines.insert(insert_pos, "")
            
            break
    
    content = "\n".join(lines)
    try:
        compile(content, str(path), "exec")
        path.write_text(content, encoding="utf-8")
        print(f"{path_rel}: OK")
    except SyntaxError as e:
        print(f"{path_rel}: SYNTAX ERROR line {e.lineno}: {e.msg}")
        err = e.lineno or 0
        for j in range(max(0, err-3), min(len(lines), err+3)):
            marker = ">>>" if j == err-1 else "   "
            print(f"  {marker} {j+1}: {lines[j]}")
