# src/auth.py
import os
from kiteconnect import KiteConnect
from config.credentials import API_KEY, API_SECRET

# Build an absolute path to config/, regardless of where this script is run from
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_PATH = os.path.join(PROJECT_ROOT, "config", "access_token.txt")

def get_kite():
    kite = KiteConnect(api_key=API_KEY)

    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, "r") as f:
            access_token = f.read().strip()
        kite.set_access_token(access_token)
        try:
            kite.profile()
            return kite
        except Exception:
            print("Saved token expired, need fresh login.")

    print("Login here:", kite.login_url())
    request_token = input("Paste the request_token from the redirected URL: ").strip()

    session = kite.generate_session(request_token, api_secret=API_SECRET)
    access_token = session["access_token"]

    kite.set_access_token(access_token)
    with open(TOKEN_PATH, "w") as f:
        f.write(access_token)

    return kite