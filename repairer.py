#!/usr/bin/env python3
import os
import subprocess
import sys
import ctypes
import struct

IN_MODIFY = 0x00000002
IN_ATTRIB = 0x00000004
IN_CLOSE_WRITE = 0x00000008
WATCH_MASK = IN_MODIFY | IN_ATTRIB | IN_CLOSE_WRITE

DONE_FILE = ".validation_done"
TRIGGER_FILE = ".validate_trigger"
ERROR_FILE = "error.txt"

def handle_repair():
    """Checks for errors and triggers GitHub Copilot CLI repair."""
    if not os.path.exists(ERROR_FILE) or os.path.getsize(ERROR_FILE) == 0:
        print("[Script B] No errors found. System is in a valid state.")
        return

    print("[Script B] Validation errors detected. Reading error.txt...")
    with open(ERROR_FILE, "r") as f:
        error_contents = f.read()

    prompt = (
        f"Fix only the Terraform files in the current working directory related to these errors:\n\n"
        f"{error_contents}\n\n"
        f"Apply the necessary corrections to resolve formatting, init, or syntax errors."
    )

    print("[Script B] Invoking GitHub Copilot CLI to apply repairs...")
    
    # Execute gh copilot command
    copilot_res = subprocess.run(
        ["gh", "copilot", "suggest", "-t", "shell", prompt],
        capture_output=False, text=True
    )

    if copilot_res.returncode == 0:
        print("[Script B] Copilot command finished execution.")
    else:
        print("[Script B] Copilot encountered an issue while generating fix.")

    # Re-trigger Script A to re-validate changes
    print(f"[Script B] Emitting change event to {TRIGGER_FILE} for re-validation...")
    with open(TRIGGER_FILE, "a"):
        os.utime(TRIGGER_FILE, None)

def watch_completion_loop():
    """Sets up inotify watch on .validation_done file."""
    libc = ctypes.CDLL("libc.so.6")
    
    fd = libc.inotify_init()
    if fd < 0:
        sys.exit("Failed to initialize inotify.")

    if not os.path.exists(DONE_FILE):
        open(DONE_FILE, 'a').close()

    wd = libc.inotify_add_watch(fd, DONE_FILE.encode('utf-8'), WATCH_MASK)
    if wd < 0:
        sys.exit(f"Failed to watch file {DONE_FILE}")

    print(f"[Script B] Listening for completion events on '{DONE_FILE}' (No polling)...")

    try:
        while True:
            data = os.read(fd, 1024)
            if data:
                handle_repair()
    except KeyboardInterrupt:
        print("\n[Script B] Stopping repairer.")
    finally:
        libc.inotify_rm_watch(fd, wd)
        os.close(fd)

if __name__ == "__main__":
    watch_completion_loop()
