import argparse

from fetchers._base import configure_stdout
from fetchers._progress import RunStats, started
from shared.fx import ensure_fx_rates
from shared.profile_paths import fx_rates_path


def main():
    parser = argparse.ArgumentParser(description="Fetch FX rates into cache/fx_rates.json")
    parser.add_argument("--force", action="store_true", help="Ignore 24h cache and refetch")
    args = parser.parse_args()
    configure_stdout()
    t0 = started("fetch_fx")
    stats = RunStats()
    try:
        doc = ensure_fx_rates(force=args.force, warn_stale=False)
    except RuntimeError as e:
        stats.error(str(e))
        return stats.finish("fetch_fx", t0, exit_code=1)
    rates = doc.get("rates") or {}
    stats.ok = len(rates)
    print(f"FX cache ready ({len(rates)} pairs, base {doc.get('base')}) at {fx_rates_path()}.", flush=True)
    return stats.finish("fetch_fx", t0, exit_code=0)


if __name__ == "__main__":
    raise SystemExit(main())
