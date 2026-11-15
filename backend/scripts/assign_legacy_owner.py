"""Explicit local operator decision after reviewing the migrated ownership mapping."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import engine
from app.services.administration import assign_legacy_owner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Exact existing active account selected by the operator")
    parser.add_argument("--reviewed", action="store_true", help="Confirm the explicit ownership mapping and intended owner were reviewed")
    args = parser.parse_args()
    if not args.reviewed:
        parser.error("Review the mapping and intended owner, then supply --reviewed")
    try:
        result = assign_legacy_owner(engine, args.email, reviewed=args.reviewed)
    except ValueError as exc:
        parser.exit(1, str(exc) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
