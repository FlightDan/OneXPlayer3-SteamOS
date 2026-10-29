"""Stage both pinned OptiScaler releases; no download, extraction or installation."""
import argparse
import json
from pathlib import Path

from optiscaler_payload import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, action='append', type=Path,
                        help='Original official 7z; supply once for each pinned version')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.archive, args.output), indent=2))


if __name__ == '__main__':
    main()
