"""Prepare pinned independent Opti2XMX assets in a fresh isolated directory.

No network, code execution, research cache reconstruction, or shared-cache edits.
After review, copy plugin/ to components/opti2xmx and merge integration/ into
the installer integration cache. Existing inputs and outputs are never replaced.
"""
import argparse
import json
from pathlib import Path

from opti_payload import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin', required=True, type=Path)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.plugin, args.runtime, args.output), indent=2))


if __name__ == '__main__':
    main()
