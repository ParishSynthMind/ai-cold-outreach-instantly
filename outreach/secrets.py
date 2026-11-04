"""Read API keys at runtime: environment variable first, then the macOS Keychain.

Values are never logged or written to disk.
"""
import os
import subprocess


class MissingSecret(RuntimeError):
    pass


def get_secret(env_var, keychain_service, keychain_account=None):
    value = os.environ.get(env_var, "").strip()
    if value:
        return value
    cmd = ["security", "find-generic-password", "-s", keychain_service, "-w"]
    if keychain_account:
        cmd[2:2] = ["-a", keychain_account]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        out = None
    if out is not None and out.returncode == 0 and out.stdout.strip():
        return out.stdout.strip()
    raise MissingSecret(
        f"Set {env_var}, or store it in the Keychain as service '{keychain_service}'"
    )
