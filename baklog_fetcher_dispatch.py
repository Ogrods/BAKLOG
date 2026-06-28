from __future__ import annotations
import importlib
import json
import os
import sys
from pathlib import Path
from fetchers.registry import MANIFEST_PATH
RUN_FETCHER_ENV = 'BAKLOG_RUN_FETCHER'
RUN_FETCHER_ARGS_ENV = 'BAKLOG_RUN_FETCHER_ARGS'

def _module_for_script(script: str) -> str:
    rel = Path(script).with_suffix('')
    return rel.as_posix().replace('/', '.')

def parse_runtime_request(argv: list[str] | None=None, environ: dict[str, str] | None=None) -> tuple[str, list[str]] | None:
    argv = sys.argv if argv is None else argv
    if len(argv) >= 3 and argv[1] == '--run-fetcher':
        return (argv[2], list(argv[3:]))
    env = os.environ if environ is None else environ
    key = (env.get(RUN_FETCHER_ENV) or '').strip()
    if not key:
        return None
    raw = env.get(RUN_FETCHER_ARGS_ENV) or ''
    extra: list[str] = []
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            extra = [str(a) for a in parsed]
    return (key, extra)

def dispatch_from_runtime(argv: list[str] | None=None, environ: dict[str, str] | None=None) -> int | None:
    request = parse_runtime_request(argv, environ)
    if request is None:
        return None
    key, extra = request
    return run_fetcher(key, extra)

def exit_if_fetcher_child() -> None:
    code = dispatch_from_runtime()
    if code is not None:
        raise SystemExit(code)

def apply_fetcher_env_mirror(argv: list[str], env: dict[str, str]) -> None:
    if len(argv) >= 3 and argv[1] == '--run-fetcher':
        env[RUN_FETCHER_ENV] = argv[2]
        env[RUN_FETCHER_ARGS_ENV] = json.dumps(argv[3:])

def run_fetcher(key: str, args: list[str]) -> int:
    raw = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
    entries = raw.get('fetchers') or []
    entry = next((e for e in entries if e.get('key') == key), None)
    if not entry:
        print(f'[fetcher] unknown key: {key!r}', file=sys.stderr)
        return 2
    script = entry.get('script')
    if not script:
        print(f'[fetcher] manifest entry {key!r} has no script', file=sys.stderr)
        return 2
    module_name = _module_for_script(str(script))
    mod = importlib.import_module(module_name)
    main = getattr(mod, 'main', None)
    if not callable(main):
        print(f'[fetcher] {module_name} has no main()', file=sys.stderr)
        return 2
    sys.argv = [str(script), *args]
    try:
        code = main()
    except SystemExit as exc:
        code = exc.code
    if code is None:
        return 0
    return int(code)