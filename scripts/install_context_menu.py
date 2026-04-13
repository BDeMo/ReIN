"""Install/uninstall Windows Explorer right-click context menu for ReIN.

Usage:
  python scripts/install_context_menu.py install    — Add "Open with ReIN" to right-click
  python scripts/install_context_menu.py uninstall  — Remove context menu entries

Requires admin privileges (run as Administrator).
"""

from __future__ import annotations

import sys
import winreg

MENU_NAME = "Open with ReIN"
ICON_PATH = ""  # Optional: set to .ico path if available

# Registry paths for context menu
KEYS = [
    # Right-click on folder
    r"Directory\shell\ReIN",
    # Right-click on folder background (inside a folder)
    r"Directory\Background\shell\ReIN",
]


def get_rein_command() -> str:
    """Build the command that will be executed from context menu."""
    # Use 'rein' from PATH, open in direct mode at the clicked directory
    return 'cmd /k "cd /d "%V" && rein"'


def install():
    """Add ReIN to Windows Explorer context menu."""
    command = get_rein_command()

    for key_path in KEYS:
        try:
            # Create the menu entry
            key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_path)
            winreg.SetValue(key, "", winreg.REG_SZ, MENU_NAME)
            if ICON_PATH:
                winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, ICON_PATH)
            winreg.CloseKey(key)

            # Create the command subkey
            cmd_key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_path + r"\command")
            winreg.SetValue(cmd_key, "", winreg.REG_SZ, command)
            winreg.CloseKey(cmd_key)

            print(f"  Installed: HKCR\\{key_path}")
        except PermissionError:
            print(f"  ERROR: Permission denied for HKCR\\{key_path}")
            print("  Run this script as Administrator.")
            sys.exit(1)
        except Exception as e:
            print(f"  ERROR: {e}")
            sys.exit(1)

    print("\nDone! 'Open with ReIN' is now in your right-click menu.")
    print("Right-click any folder or folder background to use it.")


def uninstall():
    """Remove ReIN from Windows Explorer context menu."""
    for key_path in KEYS:
        try:
            # Delete command subkey first
            try:
                winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, key_path + r"\command")
            except FileNotFoundError:
                pass

            # Delete the menu entry
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, key_path)
            print(f"  Removed: HKCR\\{key_path}")
        except FileNotFoundError:
            print(f"  Not found: HKCR\\{key_path} (already removed)")
        except PermissionError:
            print(f"  ERROR: Permission denied for HKCR\\{key_path}")
            print("  Run this script as Administrator.")
            sys.exit(1)
        except Exception as e:
            print(f"  ERROR: {e}")
            sys.exit(1)

    print("\nDone! ReIN has been removed from the right-click menu.")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("install", "uninstall"):
        print(__doc__)
        sys.exit(0)

    action = sys.argv[1]
    print(f"ReIN Explorer Context Menu — {action}")
    print()

    if action == "install":
        install()
    else:
        uninstall()


if __name__ == "__main__":
    main()
