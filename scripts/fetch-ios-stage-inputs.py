#!/usr/bin/env python3
"""Fetch only the IPSW members needed by the Polaris iPadOS stage.

UniXNU's IPSW reader uses HTTP range requests, so this does not download the
whole restore archive when the Apple CDN supports ranges.  The downloaded
members are cached under the requested output root and checked against the
pins in ``board.toml``.  No device access is performed.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True,
                        help="pinned UniXNU checkout containing scripts/unixnu")
    parser.add_argument("--out", type=Path, required=True,
                        help="UniXNU output root used for the IPSW cache")
    parser.add_argument("components", nargs="*", default=[
        "KernelCache", "OS", "Cryptex1,SystemOS", "StaticTrustCache",
        "Cryptex1,SystemTrustCache"
    ])
    args = parser.parse_args()
    base = args.base.resolve()
    sys.path.insert(0, str(base / "scripts"))
    from unixnu import cli  # type: ignore

    argv = ["ipsw", "-D", str(ROOT), "--out", str(args.out.resolve()),
            "fetch", *args.components]
    cli.main(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
