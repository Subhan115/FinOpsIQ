#!/usr/bin/env python3
import os
import subprocess
import sys
import ctypes
import struct

# --- Inotify Constants for Linux ---
IN_MODIFY = 0x00000002
IN_ATTRIB = 0x00000004
IN_CLOSE_WRITE = 0x00000008
WATCH_MASK = IN_MODIFY | IN_ATTRIB | IN_CLOSE_WRITE

TRIGGER_FILE = ".validate_trigger"
DONE_FILE = ".validation_done"
ERROR_FILE = "error.txt"

def run_terraform_checks():
    """Executes non-destructive Terraform validation checks."""
    print("\n[Script A] Running Terraform validation checks...")
    errors = []

    # 1. terraform fmt check
    fmt_res = subprocess.run(
        ["terraform", "fmt", "-check", "-recursive"],
        capture_output=True, text=True
    )
    if fmt_res.returncode != 0:
        errors.append("=== terraform fmt errors ===\n" + fmt_res.stderr or fmt_res.stdout)

    # 2. terraform init (backend disabled, non-interactive)
    init_res = subprocess.run(
        ["terraform", "init", "-backend=false", "-input=false"],
        capture_output=True, text=True
    )
    if init_res.returncode != 0:
        errors.append("=== terraform init errors ===\n" + init_res.stderr)

    # 3. terraform validate
    val_res = subprocess.run(
        ["terraform", "validate"],
        capture_output=True, text=True
    )
    if val_res.returncode != 0:
        errors.append("=== terraform validate errors ===\n" + val_res.stderr or val_res.stdout)

    # Handle error reporting
    if errors:
        print("[Script A] Validation failed. Writing errors to error.txt.")
        with open(ERROR_FILE, "w") as f:
            f.write("\n\n".join(errors))
    else:
        print("[Script A] Validation passed cleanly!")
        if os.path.exists(ERROR_FILE):
            os.remove(ERROR_FILE)

    # Emit completion event for Script B
    print(f"[Script A] Emitting completion event to {DONE_FILE}")
    with open(DONE_FILE, "a"):
        os.utime(DONE_FILE, None)

def watch_event_loop():
    """Sets up a low-level Linux inotify watch without third-party dependencies."""
    libc = ctypes.CDLL("libc.so.6")
    
    # Initialize inotify
    fd = libc.inotify_init()
    if fd < 0:
        sys.exit("Failed to initialize inotify.")

    # Ensure trigger file exists to watch it
    if not os.path.exists(TRIGGER_FILE):
        open(TRIGGER_FILE, 'a').close()

    # Add watch
    wd = libc.inotify_add_watch(fd, TRIGGER_FILE.encode('utf-8'), WATCH_MASK)
    if wd < 0:
        sys.exit(f"Failed to watch file {TRIGGER_FILE}")

    print(f"[Script A] Listening for changes on '{TRIGGER_FILE}' (No polling)...")

    # Event loop blocking on read()
    EVENT_SIZE = struct.calcsize("iIII")
    try:
        while True:
            # Block until event occurs
            data = os.read(fd, 1024)
            if data:
                run_terraform_checks()
    except KeyboardInterrupt:
        print("\n[Script A] Stopping validator.")
    finally:
        libc.inotify_rm_watch(fd, wd)
        os.close(fd)

if __name__ == "__main__":
    watch_event_loop()
