import sys
import subprocess
import importlib.util
from ttkbootstrap.dialogs import Messagebox

REQUIRED_PACKAGES = ["ttkbootstrap", "requests"]


def ensure_dependencies():
    """Checks if the required packages are installed and installs them if not."""
    installed_any = False
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "--version"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pip_ok = True
    except Exception:
        pip_ok = False
    if not pip_ok:
        try:
            subprocess.check_call([sys.executable, "-m", "ensurepip",
                                   "--upgrade", "--default-pip"],
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
            installed_any = True
            pip_ok = True
        except Exception:
            pip_ok = False
    missing = [pkg for pkg in REQUIRED_PACKAGES if
               importlib.util.find_spec(pkg) is None]
    if missing:
        if not pip_ok:
            Messagebox.showerror(
                "Fehler",
                "pip ist nicht verfügbar. Pakete können nicht installiert werden."
            )
            sys.exit(1)

        msg = (
            "Die folgenden Python-Pakete sind nicht installiert und werden "
            f"benötigt:\n{', '.join(missing)}\n\n"
            "Sollen diese Pakete jetzt installiert werden? "
            "Das Programm wird danach neu gestartet."
        )
        if Messagebox.yesno(msg, title="Pakete installieren"):
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "--user"] + missing)
                installed_any = True
            except Exception as e:
                Messagebox.showerror(
                    "Fehler",
                    f"Fehler bei Paketinstallation {missing}: {e}\n"
                    "Programm wird beendet."
                )
                sys.exit(1)
        else:
            Messagebox.showinfo(
                "Information",
                "Paketinstallation abgebrochen. Programm wird beendet."
            )
            sys.exit(0)
    return installed_any
