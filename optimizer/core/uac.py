import ctypes
import os
import sys
import winreg

# WinAPI Typen/Imports
advapi32 = ctypes.windll.advapi32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32
user32 = ctypes.windll.user32

# Konstanten
TOKEN_QUERY = 0x0008
TokenElevation = 20  # TOKEN_INFORMATION_CLASS für Elevation
SW_SHOWNORMAL = 1

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TOKEN_ELEVATION(ctypes.Structure):
    """Token elevation structure for UAC checks."""
    _fields_ = [("TokenIsElevated", ctypes.c_uint32)]  # DWORD

def is_token_elevated():
    """Checks if the current process is running with elevated privileges."""
    hProcess = kernel32.GetCurrentProcess()
    hToken = ctypes.c_void_p()
    if not advapi32.OpenProcessToken(hProcess, TOKEN_QUERY, ctypes.byref(hToken)):
        return False
    try:
        elev = TOKEN_ELEVATION()
        cb = ctypes.c_uint32(ctypes.sizeof(elev))
        retlen = ctypes.c_uint32(0)
        ok = advapi32.GetTokenInformation(hToken, TokenElevation,
                                          ctypes.byref(elev), cb,
                                          ctypes.byref(retlen))
        if not ok:
            return False
        return bool(elev.TokenIsElevated)
    finally:
        kernel32.CloseHandle(hToken)

def is_admin_fallback():
    """Fallback method to check for administrator privileges."""
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False

def win_msgbox(title, text, flags=0x00000010):
    """Displays a Windows message box."""
    try:
        user32.MessageBoxW(0, str(text), str(title), flags)
    except Exception:
        pass

def read_uac_policy():
    """Reads the UAC policy from the Windows Registry."""
    pol = {"EnableLUA": None, "ConsentPromptBehaviorAdmin": None, "PromptOnSecureDesktop": None}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System", 
                            0, winreg.KEY_READ) as k:
            for name in list(pol.keys()):
                try:
                    val, _ = winreg.QueryValueEx(k, name)
                    pol[name] = int(val)
                except FileNotFoundError:
                    pol[name] = None
    except Exception:
        pass
    return pol

def uac_policy_summary(pol: dict):
    """Returns a summary of the UAC policy."""
    ena = pol.get("EnableLUA")
    cpa = pol.get("ConsentPromptBehaviorAdmin")
    pod = pol.get("PromptOnSecureDesktop")
    if ena == 0:
        return "UAC disabled (EnableLUA=0): no UAC dialogs, elevation occurs silently."
    if cpa == 0:
        return "Admin without prompt (ConsentPromptBehaviorAdmin=0): no UAC query, elevation occurs silently."
    return f"UAC active (EnableLUA={ena}), Admin-Prompt-Mode={cpa}, SecureDesktop={pod}."

def shell_execute_runas(file, params, directory):
    """Executes a shell command with elevated privileges."""
    try:
        return shell32.ShellExecuteW(None, "runas", file, params, directory, SW_SHOWNORMAL)
    except Exception:
        return 0

def choose_interpreter_for_elevation():
    """Chooses the best Python interpreter for elevation."""
    exe = sys.executable or ""
    try_py_launcher = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "py.exe")
    if "windowsapps" in exe.lower() or (exe.lower().endswith("python.exe") and ("appx" in exe.lower() or "microsoft" in exe.lower())):
        if os.path.exists(try_py_launcher):
            return try_py_launcher
    if not os.path.exists(exe) and os.path.exists(try_py_launcher):
        return try_py_launcher
    return exe

def ensure_elevated_or_exit():
    """Ensures that the script is running with elevated privileges, or exits."""
    pol = read_uac_policy()
    if pol.get("EnableLUA") == 0 or pol.get("ConsentPromptBehaviorAdmin") == 0:
        win_msgbox("UAC Note",
                   "Windows is configured so that administrators are elevated without prompt.\n"
                   "Therefore no UAC query appears; the program still starts as administrator.",
                   0x40)
    if is_token_elevated() or is_admin_fallback():
        return
    interp = choose_interpreter_for_elevation()
    # In the new structure, the main script is one level up.
    script = os.path.abspath(os.path.join(BASE_DIR, 'main.py'))
    params = f'\"{script}\"' 
    if len(sys.argv) > 1:
        params += " " + " ".join(f'\"{arg}\"' for arg in sys.argv[1:])
    ret = shell_execute_runas(interp, params, BASE_DIR)
    if ret and ret > 32:
        sys.exit(0)
    ps_arglist = params.replace('"', '""')
    ps_cmd = f"Start-Process -FilePath \'{interp}\' -ArgumentList \'{ps_arglist}\' -WorkingDirectory \'{BASE_DIR}\' -Verb RunAs"
    ret2 = shell_execute_runas(
        "powershell.exe",
        f'-NoProfile -ExecutionPolicy Bypass -Command "{ps_cmd}"',
        None
    )
    if ret2 and ret2 > 32:
        sys.exit(0)
    win_msgbox("Administrator Rights Required",
               "The UAC request was denied or failed.\nThis program requires administrator rights and will be terminated.",
               0x10)
    sys.exit(1)
