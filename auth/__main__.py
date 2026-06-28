import argparse
import getpass
import sys
from pathlib import Path

from auth.bundle import (
    BadMagic,
    BadPassphrase,
    BundleError,
    BundleTooLarge,
    UnsupportedVersion,
    bundle_filename,
    export_bundle,
    import_bundle,
)
from auth.registry import PROVIDERS, provider_order


def _prompt_passphrase(*, confirm=False):
    pw = getpass.getpass("Bundle passphrase: ")
    if confirm:
        again = getpass.getpass("Confirm passphrase: ")
        if pw != again:
            raise SystemExit("Passphrases do not match.")
    return pw


def cmd_export(args):
    passphrase = _prompt_passphrase(confirm=True)
    blob = export_bundle(passphrase, include_profiles=not args.no_profiles)
    out = Path(args.out) if args.out else Path(bundle_filename())
    out.write_bytes(blob)
    print(f"Wrote {len(blob)} bytes to {out}")
    return 0


def cmd_import(args):
    path = Path(args.path)
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 1
    blob = path.read_bytes()
    passphrase = _prompt_passphrase()
    try:
        summary = import_bundle(blob, passphrase, dry_run=args.dry_run)
    except BundleError as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    mode = "Dry run" if summary.dry_run else "Imported"
    print(
        f"{mode}: {len(summary.providers_imported)} provider(s), {len(summary.profiles_imported)} profile(s), {summary.bytes_written} bytes"
    )
    if summary.providers_imported:
        print("Providers:", ", ".join(summary.providers_imported))
    if summary.profiles_imported:
        print("Profiles:", ", ".join(summary.profiles_imported))
    return 0


def cmd_expire(args):
    from auth.manager import mark_invalid

    if args.list:
        for key in provider_order():
            spec = PROVIDERS[key]
            print(f"  {key:20}  {spec.label}")
        return 0
    provider = (args.provider or "").strip()
    if provider not in PROVIDERS:
        print(f"Unknown provider: {provider!r}. Run: python -m auth expire --list", file=sys.stderr)
        return 1
    mark_invalid(provider, error=args.error or "Forced expire (dev test)")
    print(f"Marked {provider} as expired (Session expired in Connections).")
    print("Refresh the dashboard or Connections tab to see the Reconnect chip.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m auth", description="BAKLOG auth utilities")
    sub = parser.add_subparsers(dest="command", required=True)
    export_p = sub.add_parser("export-bundle", help="Export encrypted credentials + profiles")
    export_p.add_argument("--out", help="Output path (default: baklog-secrets-<timestamp>.bundle)")
    export_p.add_argument(
        "--no-profiles", action="store_true", help="Export credentials only (omit CDP browser profile dirs)"
    )
    export_p.set_defaults(func=cmd_export)
    import_p = sub.add_parser("import-bundle", help="Import encrypted credentials + profiles")
    import_p.add_argument("path", help="Path to .bundle file")
    import_p.add_argument("--dry-run", action="store_true", help="Validate bundle without writing")
    import_p.set_defaults(func=cmd_import)
    expire_p = sub.add_parser("expire", help="Mark a provider Session expired (dev/test Reconnect chip)")
    expire_p.add_argument(
        "provider", nargs="?", help="Provider key (e.g. gog, epic_wishlist). Omit with --list to print keys."
    )
    expire_p.add_argument("--list", action="store_true", help="List valid provider keys")
    expire_p.add_argument("--error", default="", help="Optional last_error message stored on the provider blob")
    expire_p.set_defaults(func=cmd_expire)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (BadPassphrase, BadMagic, UnsupportedVersion, BundleTooLarge, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
