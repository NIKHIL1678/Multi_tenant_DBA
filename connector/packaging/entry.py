"""Entry point PyInstaller freezes into zipzy-connector.exe (see scripts/build-windows.ps1).

Double-clicked without arguments, the .exe runs the guided desktop start; with arguments it
behaves like the `zipzy-connector` command (check, run, start).
"""

from zipzy_connector.cli import main

if __name__ == "__main__":
    main()
