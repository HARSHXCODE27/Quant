#!/usr/bin/env python3
"""
Morning Kite login. Run once per trading day, before the scheduled list runs.

Zerodha access tokens expire overnight by design — there is no way around the
browser login, so this is the one manual step in the day. get_kite() reuses the
saved token if it is still valid, so running this twice costs nothing.

    python scripts/refresh_token.py
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.auth import get_kite


def main():
    kite = get_kite()
    profile = kite.profile()
    print(f"OK — {profile.get('user_name')} ({profile.get('user_id')}) token is live.")


if __name__ == "__main__":
    main()
