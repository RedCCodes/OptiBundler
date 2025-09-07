import sys
import os
import io

from optimizer.core.uac import ensure_elevated_or_exit
from optimizer.core.dependencies import ensure_dependencies
from optimizer.ui.gui import ModernOptimizerGUI


def main():
    """
    Main function to run the optimizer.
    """
    ensure_elevated_or_exit()

    # Perform dependency check and install if necessary
    # This must happen before importing any modules that use these packages
    if ensure_dependencies():
        # If packages were installed, restart the application
        os.execv(sys.executable, [sys.executable] + sys.argv)

    # Now that dependencies are confirmed, import the main GUI
    ModernOptimizerGUI()


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    main()
