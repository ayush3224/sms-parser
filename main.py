#!/usr/bin/env python3
"""
main.py — production entry point.
Railway detects this file and runs it. It unconditionally starts the webhook server.

For local interactive CLI, run:  python cli.py
"""
from server import main

if __name__ == "__main__":
    main()
