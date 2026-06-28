from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
lines = (ROOT / 'js/fetcher-health.js').read_text(encoding='utf-8').splitlines()

def sl(a: int, b: int) -> str:
    return '\n'.join(lines[a - 1:b]) + '\n'
(ROOT / 'js/fetcher/_extract').mkdir(parents=True, exist_ok=True)
slices = {'runner_body.txt': (1278, 3165), 'render_dashboard.txt': (3370, 3754), 'render_stats.txt': (3177, 3368), 'global_indicator.txt': (910, 1129), 'source_meta.txt': (513, 909), 'freshness.txt': (1131, 1206), 'misc.txt': (404, 512), 'reconnect.txt': (87, 403)}
for name, (a, b) in slices.items():
    p = ROOT / 'js/fetcher/_extract' / name
    p.write_text(sl(a, b), encoding='utf-8')
    print(f'{name}: {b - a + 1} lines')