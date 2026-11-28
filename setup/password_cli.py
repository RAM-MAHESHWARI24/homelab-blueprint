#!/usr/bin/env python3
"""
Set the Control Hub dashboard password.

    sudo ./setup.sh password            asks for the new password twice
    echo 'pw' | sudo ./setup.sh password --stdin

Every browser that signed in with the old password has to sign in again.
"""

import argparse
import getpass
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import setup  # noqa: F401
from core.config_core import MIN_PASSWORD_LENGTH, PASSWORD_FILE, SERVICE_USER, set_password


def main() -> int:
    parser = argparse.ArgumentParser(description="Set the Control Hub dashboard password")
    parser.add_argument("--stdin", action="store_true", help="Read the new password from standard input")
    args = parser.parse_args()

    if args.stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("New dashboard password: ")
        if password != getpass.getpass("Repeat it: "):
            print("The passwords do not match; nothing changed.", file=sys.stderr)
            return 1
    try:
        path = set_password(password, owner=SERVICE_USER)
    except ValueError:
        print(f"Use at least {MIN_PASSWORD_LENGTH} characters; nothing changed.", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Could not write {PASSWORD_FILE}: {exc} (run with sudo)", file=sys.stderr)
        return 1
    print(f"Dashboard password saved ({path}). Browsers must sign in again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
