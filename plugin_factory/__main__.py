from __future__ import annotations

import argparse
import dataclasses
import json

from .factory import build_release, verify_release


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline inert plugin package verifier")
    subcommands = parser.add_subparsers(dest="command", required=True)
    build = subcommands.add_parser("build")
    build.add_argument("source")
    build.add_argument("destination")
    verify = subcommands.add_parser("verify")
    verify.add_argument("release")
    verify.add_argument("expected_digest")
    args = parser.parse_args()
    if args.command == "build":
        print(build_release(args.source, args.destination))
    else:
        receipt = verify_release(args.release, args.expected_digest)
        print(json.dumps(dataclasses.asdict(receipt), sort_keys=True))


if __name__ == "__main__":
    main()
