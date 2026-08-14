"""
auth_setup.py — One-time Clubhouse authentication helper.

Walks you through obtaining a Clubhouse auth token from your phone number
and saves it to auth_token.json so the bot can join rooms.

NOTE:
  Clubhouse's API has evolved since this library was written. If phone auth
  no longer works (Clubhouse now requires the official app + reCAPTCHA in
  many regions), you can instead extract the token from your own device:
    1. Install the Clubhouse app and log in normally.
    2. Use a proxy/debugger on the device to capture the `Authorization:
       Token <TOKEN>` header from any API request (e.g. mitmproxy, Charles,
       or a rooted device with logcat).
    3. Paste the token, your user_id and device_id into auth_token.json:
       {
         "user_id": "YOUR_USER_ID",
         "user_token": "YOUR_TOKEN",
         "device_id": "YOUR_DEVICE_UUID"
       }
"""

import json
import os
import uuid
import sys

try:
    from clubhouse.clubhouse import Clubhouse
except ImportError:
    print("clubhouse-py not installed. Run: pip install clubhouse-py")
    sys.exit(1)

TOKEN_FILE = "./auth_token.json"


def input_line(prompt: str, required: bool = True):
    value = input(prompt).strip()
    if required and not value:
        print("Value required, try again.")
        return input_line(prompt, required)
    return value


def main():
    print("=" * 70)
    print("ClubDJ — Clubhouse authentication setup")
    print("=" * 70)

    # If a token file already exists, offer to reuse it
    if os.path.isfile(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            stored = json.load(f)
        answer = input(
            f"auth_token.json already exists (user_id={stored.get('user_id')}).\n"
            "Overwrite? [y/N]: "
        ).strip().lower()
        if answer != "y":
            print("Keeping existing token. Exiting.")
            return

    print()
    print("Step 1: Enter your Clubhouse phone number (e.g. +91XXXXXXXXXX).")
    phone = input_line("Phone number: ")

    ch = Clubhouse()

    print("\nStep 2: Requesting verification code...")
    try:
        resp = ch.start_phone_number_auth(phone)
        print("API response:", json.dumps(resp, indent=2))
        if not resp.get("success"):
            print(
                "\nPhone auth was rejected by Clubhouse's servers.\n"
                "This usually means Clubhouse now requires the official app\n"
                "(with reCAPTCHA). See the note at the top of this file for\n"
                "how to extract a token from your logged-in app session\n"
                "instead — that is the most reliable method today."
            )
            sys.exit(1)
    except Exception as exc:
        print(f"Auth request failed: {exc}")
        sys.exit(1)

    print("\nStep 3: Enter the SMS verification code you received.")
    code = input_line("Verification code: ")

    print("\nStep 4: Completing authentication...")
    try:
        # rc_token can be None/empty in older API versions
        resp = ch.complete_phone_number_auth(phone, rc_token=None, verification_code=code)
        print("API response:", json.dumps(resp, indent=2))

        if resp.get("success") and resp.get("auth_token"):
            auth = {
                "user_id": str(resp["user_profile"].get("user_id", "")),
                "user_token": resp["auth_token"],
                "device_id": ch.HEADERS.get("CH-DeviceId", str(uuid.uuid4()).upper()),
            }
            with open(TOKEN_FILE, "w") as f:
                json.dump(auth, f, indent=2)
            print(f"\nSuccess! Token saved to {TOKEN_FILE}.")
            print("You can now run: python main.py")
        else:
            print(
                "\nAuthentication did not complete. Clubhouse likely requires\n"
                "app-based login now. Extract your token from the official\n"
                "app instead (see instructions at the top of this file)."
            )
            sys.exit(1)
    except Exception as exc:
        print(f"Completion failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
