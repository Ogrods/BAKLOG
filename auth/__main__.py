"""CLI for portable secrets bundle export/import."""

from __future__ import annotations

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


def _prompt_passphrase(*, confirm: bool = False) -> str:
    pw = getpass.getpass("Bundle passphrase: ")
    if confirm:
        again = getpass.getpass("Confirm passphrase: ")
        if pw != again:
            raise SystemExit("Passphrases do not match.")
    return pw


def cmd_export(args: argparse.Namespace) -> int:
    passphrase = _prompt_passphrase(confirm=True)
    blob = export_bundle(passphrase, include_profiles=not args.no_profiles)
    out = Path(args.out) if args.out else Path(bundle_filename())
    out.write_bytes(blob)
    print(f"Wrote {len(blob)} bytes to {out}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
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
        f"{mode}: {len(summary.providers_imported)} provider(s), "
        f"{len(summary.profiles_imported)} profile(s), "
        f"{summary.bytes_written} bytes"
    )
    if summary.providers_imported:
        print("Providers:", ", ".join(summary.providers_imported))
    if summary.profiles_imported:
        print("Profiles:", ", ".join(summary.profiles_imported))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m auth", description="BAKLOG auth utilities")
    sub = parser.add_subparsers(dest="command", required=True)

    export_p = sub.add_parser("export-bundle", help="Export encrypted credentials + profiles")
    export_p.add_argument("--out", help="Output path (default: baklog-secrets-<timestamp>.bundle)")
    export_p.add_argument(
        "--no-profiles",
        action="store_true",
        help="Export credentials only (omit Playwright profile dirs)",
    )
    export_p.set_defaults(func=cmd_export)

    import_p = sub.add_parser("import-bundle", help="Import encrypted credentials + profiles")
    import_p.add_argument("path", help="Path to .bundle file")
    import_p.add_argument("--dry-run", action="store_true", help="Validate bundle without writing")
    import_p.set_defaults(func=cmd_import)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (BadPassphrase, BadMagic, UnsupportedVersion, BundleTooLarge, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
