"""
VoxDesk — One-Click Launcher
Start the application with a single command.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    print()
    print("  🌐 VoxDesk — Local AI Desktop Assistant")
    print("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()

    from src.main import main as start_app
    start_app()


if __name__ == "__main__":
    main()
