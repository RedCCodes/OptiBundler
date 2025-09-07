import os
import sys
import subprocess
import time
import getpass
import re
import platform
import tkinter as tk
import logging
import json
import threading
from tkinter import simpledialog
import ttkbootstrap as tb
from ttkbootstrap.dialogs import Messagebox
from ttkbootstrap import ttk as ttk

from optimizer.core import uac
from optimizer.core import operations
from optimizer.core import config
from optimizer.core import diagnostics
from optimizer.core.logging_setup import setup_logging, PhaseLoggerAdapter, log_event, log_exceptions, SESSION_ID

class ModernOptimizerGUI:
    """Main GUI of the application.

    Thread Safety:
        All UI updates occur exclusively via the Tk main thread
        (e.g. via self.root.after(...)). Background work uses threads.
    """

    # Internal Tab Identifiers
    TAB_RESTORE = "wiederherstellung_tab"
    TAB_ANTIVIRUS = "antivirus_tab"
    TAB_DOWNLOAD = "download_tab"
    TAB_TALON = "talon_tab"
    TAB_TWEAKER = "tweaker_tab"
    TAB_LIFETIME_LICENSE = "lifetime_license_tab"
    TAB_APPS = "apps_tab" # This phase also handles Chocolatey installations
    TAB_GUIDE = "guide_tab"
    TAB_FINAL = "final_tab"
    TAB_ADMIN = "admin_tab"

    def __init__(self):
        """Initializes the main GUI."""
        setup_logging(logging.INFO)
        base_logger = logging.getLogger("optimizer")
        self.log = PhaseLoggerAdapter(base_logger, {"phase": "init", "sid": SESSION_ID})

        self.uac_policy = uac.read_uac_policy()
        log_event(self.log, "uac_policy",
                  EnableLUA=self.uac_policy.get("EnableLUA"),
                  ConsentAdmin=self.uac_policy.get("ConsentPromptBehaviorAdmin"),
                  SecureDesktop=self.uac_policy.get("PromptOnSecureDesktop"))

        self.root = tb.Window(themename="cyborg")
        self.root.title("Windows Optimizer Pro")
        self.root.minsize(780, 600)
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Center main window
        try:
            self.center_window(self.root)
        except Exception:
            pass

        self.container = ttk.Frame(self.root)
        self.container.grid(row=0, column=0, sticky="nsew")
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        self.downloads_completed = False
        self.antivirus_configured = False
        self.talon_completed = False
        self.exm_used = False
        self.boosterx_used = False
        self.resume_after_restart = None
        self.guide_completed = False
        self.apps_phase_done = False

        self.restore_last_action = None
        self.restore_last_point = None

        self._admin_win = None
        self._admin_authed = False

        self._install_button = None
        self._continue_button = None
        self._back_button = None

        self.dev_skip_talon = False
        self.dev_skip_to_final_after_av = False

        self.config_file = config.CONFIG_FILE
        self.BASE_DIR = config.BASE_DIR
        # Set theme default before loading status, so load_status can override it
        self.current_theme = "cyborg"
        config.load_status(self)
        # GEMINI PATCH START: Initialize new tweaker flags
        self.exm_done_once = getattr(self, 'exm_done_once', False)
        self.boosterx_done_once = getattr(self, 'boosterx_done_once', False)
        self.tweaker_autoadvance_locked = getattr(self, 'tweaker_autoadvance_locked', False)
        self.last_tweaker_autoadvance_at = getattr(self, 'last_tweaker_autoadvance_at', None)
        # GEMINI PATCH END: Initialize new tweaker flags

        self.tweaker_progress_text = tk.StringVar(value="") # Added for live progress update

        self.startup_batch = operations.get_startup_batch_path()

        # Windows-Version erkennen
        self.windows_version, self.windows_build = self.detect_windows_version()
        self.is_win10 = self.detect_windows_10()
        self.is_win11 = self.windows_version == "Windows 11"
        self.is_win12_plus = self.windows_version.startswith("Windows ") and int(self.windows_version.split()[1]) >= 12
        
        self.setup_download_urls()

        # Alle Downloads in einen Ordner konsolidieren
        self.download_dir = os.path.join(config.BASE_DIR, "optimizer_downloads")
        os.makedirs(self.download_dir, exist_ok=True)

        # Tweaker tools verwenden den gleichen Download-Ordner
        self.tweaker_dir = self.download_dir

        self.phase_token = 0
        self.current_phase = None

        log_event(self.log, "app_start",
                  user=getpass.getuser(),
                  py=sys.version.split()[0],
                  os=f"{platform.system()} {platform.release()}",
                  win10=self.is_win10,
                  sid=SESSION_ID)

        self._click_buffer = []
        self._click_window_secs = 1.5
        self.root.bind_all("<Button-1>", self._secret_click_detector, add="+ ")

        # Create theme control frame that stays on top
        self.theme_frame = ttk.Frame(self.root)
        self.theme_frame.grid(row=0, column=1, sticky="ne", padx=(0, 10), pady=(10, 0))
        
        # Theme toggle button with dynamic icon
        self.theme_toggle_btn = ttk.Button(self.theme_frame, text="☀️ Light Mode", 
                                          command=self.toggle_theme, 
                                          bootstyle="outline-secondary")
        self.theme_toggle_btn.grid(row=0, column=0, pady=(0, 5))
        
        # Make sure theme frame stays on top of other content
        self.theme_frame.lift()

        # Aktuelles Theme anwenden (inkl. geladenem Status) und Button-Text setzen
        try:
            # Check if current theme is valid, fallback to cyborg if not
            if self.current_theme not in self.root.style.theme_names():
                self.current_theme = "cyborg"
            self.root.style.theme_use(self.current_theme)
            if self.current_theme == "cyborg":
                self.theme_toggle_btn.configure(text="☀️ Light Mode")
            else:
                self.theme_toggle_btn.configure(text="🌙 Dark Mode")
        except Exception:
            # Fallback ohne Abbruch
            pass

        self.show_restore_prompt()

        self.root.mainloop()

    def center_window(self, win, width=None, height=None):
        """Centers a window on the screen or relative to its current size."""
        try:
            win.update_idletasks()
            if width is not None and height is not None:
                w, h = width, height
            else:
                w = win.winfo_width() or 780
                h = win.winfo_height() or 600
            sw = win.winfo_screenwidth()
            sh = win.winfo_screenheight()
            x = int((sw - w) / 2)
            y = int((sh - h) / 2)
            win.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def save_status(self):
        """Persistiert den aktuellen App-Status nach `optimizer_status.json`."""
        config.save_status(self)

    def toggle_theme(self):
        """Toggles between dark and light themes (cyborg/simplex)."""
        if self.current_theme == "cyborg":
            # Switch to light theme
            target_theme = "simplex"
            # Check if simplex is available, fallback to lumen if not
            if target_theme not in self.root.style.theme_names():
                target_theme = "lumen"
            self.current_theme = target_theme
            self.root.style.theme_use(target_theme)
            self.theme_toggle_btn.configure(text="🌙 Dark Mode")
        else:
            # Switch to dark theme
            self.current_theme = "cyborg"
            self.root.style.theme_use("cyborg")
            self.theme_toggle_btn.configure(text="☀️ Light Mode")
        
        # Ensure theme frame stays visible
        self.theme_frame.lift()
        
        # Log theme change
        log_event(self.log, "theme_changed", theme=self.current_theme)
        # Persistiere Auswahl
        try:
            self.save_status()
        except Exception:
            pass

    def detect_windows_version(self):
        """Detects the Windows version and build number accurately.
        
        Supports only Windows 10 and Windows 11.
        Returns None for unsupported Windows versions.
        """
        try:
            # Method 1: Via ver command (more accurate)
            output = subprocess.check_output("ver", shell=True, text=True)
            
            # Search for version and build
            version_match = re.search(r'(\d+)\.(\d+)\.(\d+)', output)
            if version_match:
                major, minor, build = map(int, version_match.groups())
                
                # Windows 10: 10.0.x with Build < 22000
                if major == 10 and minor == 0 and build < 22000:
                    return "Windows 10", build
                
                # Windows 11: 10.0.x with Build >= 22000
                elif major == 10 and minor == 0 and build >= 22000:
                    return "Windows 11", build
                
                # Unsupported Windows versions (Windows 12+, older versions)
                else:
                    return None, build
            
        except Exception:
            pass
        
        try:
            # Method 2: Via platform module (Fallback)
            import platform
            system = platform.system()
            version = platform.version()
            
            if system == "Windows":
                # Windows 11 hat Build >= 22000
                if "10.0.22000" in version or "10.0.22621" in version:
                    return "Windows 11", 22000
                elif "10.0" in version:
                    return "Windows 10", 19000
                else:
                    # Unsupported Windows version
                    return None, 0
            
        except Exception:
            pass
        
        # Fallback: Assume Windows 10 by default
        return "Windows 10", 19000

    def detect_windows_10(self):
        """Detects if the operating system is Windows 10 (for backward compatibility)."""
        version, build = self.detect_windows_version()
        return version == "Windows 10"

    def setup_download_urls(self):
        """Sets up the download URLs for the optimizer tools."""
        with open(os.path.join(config.BASE_DIR, "optimizer", "core", "links.json")) as f:
            links = json.load(f)
        
        if self.is_win10:
            talon_url = links["download_urls"]["talon_win10"]
            self.talon_name = 'TalonLite'
        else:
            talon_url = links["download_urls"]["talon_win11"]
            self.talon_name = 'Talon'
        
        # Downloads-Phase: Nur Talon/TalonLite vorbereiten.
        self.download_urls = {
            'talon': talon_url
        }

        # Tweaker on-demand: Keep EXM Tweaks and BoosterX URLs ready for later installation.
        self.tweaker_urls = {
            'exm_tweaks': links["download_urls"]["exm_tweaks"],
            'boosterx': links["download_urls"]["boosterx"]
        }
        
        # Guide-Tab Downloads
        self.guide_downloads = links.get("guide_downloads", {})

        self.choco_apps = links["choco_apps"]
        # Optionale Download-Hashes laden (falls vorhanden)
        self.download_hashes = links.get("hashes", {})
        # Admin-Passwort cachen
        self.admin_password = links.get("admin_password")

    def clear_frame(self):
        """Clears the main container frame."""
        for widget in self.container.winfo_children():
            try:
                widget.destroy()
            except Exception:
                pass

    def make_responsive_frame(self, pad_x=36, pad_y=28):
        """Creates a responsive frame."""
        main = ttk.Frame(self.container, padding=(pad_x, pad_y))
        main.grid(row=0, column=0, sticky='nsew')
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)
        for i in range(6):
            main.grid_rowconfigure(i, weight=1)
        for j in range(2):
            main.grid_columnconfigure(j, weight=1)
        return main

    def headline(self, parent, text, icon=""):
        """Creates a headline label."""
        return ttk.Label(parent, text=f"{icon} {text}", font=("Segoe UI", 20, "bold"))

    def sublabel(self, parent, text, justify="center"):
        """Creates a sublabel with word wrap."""
        return ttk.Label(parent, text=text, wraplength=720, justify=justify)

    def button_row(self, parent):
        """Creates a button row frame."""
        row = ttk.Frame(parent)
        row.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(1, weight=1)
        return row

    def ui_set(self, percent=None, text=None, token=None):
        """Updates the UI with progress."""
        def _do():
            if token is not None and token != self.phase_token:
                return
            if percent is not None and hasattr(self, "progress_bar") and self.progress_bar.winfo_exists():
                self.progress_bar['value'] = percent
            if text is not None and hasattr(self, "progress_var"):
                self.progress_var.set(text)
        try:
            self.root.after(0, _do)
        except Exception as e:
            self.log.warning(f"ui_after_failed={e}")

    def _secret_click_detector(self, event):
        """Detects secret clicks to open the admin panel."""
        now = time.time()
        if getattr(event, "num", 1) != 1:
            return
        if self._admin_win and self._admin_win.winfo_exists():
            try:
                self._admin_win.lift()
                self._admin_win.focus_force()
                self._admin_win.attributes("-topmost", True)
                self._admin_win.after(100, lambda: self._admin_win.attributes("-topmost", False))
            except Exception:
                pass
            return
        self._click_buffer = [t for t in self._click_buffer if now - t <= self._click_window_secs]
        self._click_buffer.append(now)
        if len(self._click_buffer) >= 5:
            self._click_buffer.clear()
            pwd = simpledialog.askstring("Admin-Tool", "Passwort eingeben:", show="*")
            # Admin-Passwort: ENV-Override (OPTIMIZER_ADMIN_PASSWORD) > gecachter Wert > Fehler
            expected = os.environ.get("OPTIMIZER_ADMIN_PASSWORD") or getattr(self, "admin_password", None)
            if not expected:
                Messagebox.showerror("Fehler", "Kein Admin-Passwort konfiguriert. Bitte ENV oder links.json nutzen.")
                return
            if pwd != expected:
                Messagebox.showerror("Fehler", "Falsches Passwort.")
                return
            self._admin_authed = True
            self.open_admin_panel()

    def open_admin_panel(self):
        """Opens the admin panel."""
        if self._admin_win and self._admin_win.winfo_exists():
            try:
                self._admin_win.lift()
                self._admin_win.focus_force()
                self._admin_win.attributes("-topmost", True)
                self._admin_win.after(100, lambda: self._admin_win.attributes("-topmost", False))
            except Exception:
                pass
            return

        if not self._admin_authed:
            return

        log_event(self.log, "admin_panel_open", phase=self.TAB_ADMIN) # Added phase for admin panel
        self._admin_win = tb.Toplevel(self.root)
        self._admin_win.title("Admin-Tool")
        # More compact default size
        self._admin_win.geometry("560x640")
        self._admin_win.minsize(520, 600)

        def _close_admin():
            try:
                self._admin_win.destroy()
            finally:
                self._admin_win = None
                self._admin_authed = False
        self._admin_win.protocol("WM_DELETE_WINDOW", _close_admin)

        self._admin_win.transient(self.root)
        self._admin_win.lift()
        self._admin_win.focus_force()
        self._admin_win.attributes("-topmost", True)
        self._admin_win.after(100, lambda: self._admin_win.attributes("-topmost", False))
        # Fenster rechts neben dem Hauptfenster positionieren (und vertikal zentrieren)
        try:
            self.root.update_idletasks()
            rw = self.root.winfo_width() or 780
            rh = self.root.winfo_height() or 600
            rx = self.root.winfo_x()
            ry = self.root.winfo_y()
            aw = self._admin_win.winfo_width() or 560
            ah = self._admin_win.winfo_height() or 640
            x = rx + rw + 12
            y = ry + max(0, int((rh - ah) / 2))
            self._admin_win.geometry(f"{aw}x{ah}+{x}+{y}")
        except Exception:
            # Fallback: zentrieren
            try:
                self.center_window(self._admin_win, 560, 640)
            except Exception:
                pass

        frm = ttk.Frame(self._admin_win, padding=16)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Admin-Tool: Phase wechseln, Status & UAC/Restore-Infos",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 10))

        self._admin_phase = tk.StringVar(value=self.current_phase or self.TAB_TWEAKER) # Default to tweaker_tab
        phases = [
            ("Wiederherstellung", self.TAB_RESTORE),
            ("Antivirus", self.TAB_ANTIVIRUS),
            ("Download", self.TAB_DOWNLOAD),
            ("Talon", self.TAB_TALON),
            ("Tweaker-Hub", self.TAB_TWEAKER),
            ("Lifetime License", self.TAB_LIFETIME_LICENSE),
            ("Optionale Apps", self.TAB_APPS),
            ("Guide", self.TAB_GUIDE),
            ("Finaler Schritt", self.TAB_FINAL),
        ]
        ph_frame = ttk.Labelframe(frm, text="Ziel-Ansicht")
        ph_frame.pack(fill="x", pady=8)
        for txt, val in phases:
            ttk.Radiobutton(ph_frame, text=txt, value=val, variable=self._admin_phase).pack(anchor="w")

        flags = ttk.Labelframe(frm, text="Status-Flags")
        flags.pack(fill="x", pady=8)
        self._var_av = tk.BooleanVar(value=self.antivirus_configured)
        self._var_dl = tk.BooleanVar(value=self.downloads_completed)
        self._var_ta = tk.BooleanVar(value=self.talon_completed)
        self._var_ap = tk.BooleanVar(value=self.apps_phase_done)
        self._var_gu = tk.BooleanVar(value=self.guide_completed)
        
        ttk.Checkbutton(flags, text="Antivirus configured", variable=self._var_av, bootstyle="round-toggle").pack(anchor="w")
        ttk.Checkbutton(flags, text="Downloads completed", variable=self._var_dl, bootstyle="round-toggle").pack(anchor="w")
        ttk.Checkbutton(flags, text="Talon done", variable=self._var_ta, bootstyle="round-toggle").pack(anchor="w")
        ttk.Checkbutton(flags, text="Apps phase done", variable=self._var_ap, bootstyle="round-toggle").pack(anchor="w")
        ttk.Checkbutton(flags, text="Guide done", variable=self._var_gu, bootstyle="round-toggle").pack(anchor="w")

        tweaker_flags = ttk.Labelframe(frm, text="Tweaker Progress")
        tweaker_flags.pack(fill="x", pady=8)
        self._var_exm_done = tk.BooleanVar(value=self.exm_done_once)
        self._var_boosterx_done = tk.BooleanVar(value=self.boosterx_done_once)
        ttk.Checkbutton(tweaker_flags, text="EXM completed", variable=self._var_exm_done, bootstyle="round-toggle").pack(anchor="w")
        ttk.Checkbutton(tweaker_flags, text="BoosterX completed", variable=self._var_boosterx_done, bootstyle="round-toggle").pack(anchor="w")

        info = ttk.Labelframe(frm, text="UAC/Restore-Info")
        info.pack(fill="x", pady=8)
        pol = self.uac_policy or {}
        ttk.Label(info, text=f"UAC: EnableLUA={pol.get('EnableLUA')} | ConsentAdmin={pol.get('ConsentPromptBehaviorAdmin')} | SecureDesktop={pol.get('PromptOnSecureDesktop')}").pack(anchor="w")
        ttk.Label(info, text=f"Restore: action={self.restore_last_action or '-'} | point={self.restore_last_point or '-'} ").pack(anchor="w")

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="Switch Only", bootstyle="secondary",
                   command=lambda: self._admin_go(apply_flags=False)).pack(side="left", expand=True, fill="x", padx=(0, 6))
        ttk.Button(btns, text="Apply & Switch", bootstyle="success",
                   command=lambda: self._admin_go(apply_flags=True)).pack(side="left", expand=True, fill="x", padx=(6, 0))

        ttk.Separator(frm).pack(fill="x", pady=10)
        
        # Diagnose-Bereich mit Status-Anzeige
        diag_frame = ttk.Labelframe(frm, text="🔍 System-Diagnose")
        diag_frame.pack(fill="x", pady=(0, 10))
        
        # Status label for diagnosis
        self._diag_status = tk.StringVar(value="Ready for Diagnosis")
        ttk.Label(diag_frame, textvariable=self._diag_status, bootstyle="secondary").pack(anchor="w", pady=(0, 8))
        
        # Diagnose-Button mit Icon
        self._diag_button = ttk.Button(
            diag_frame, 
            text="🔍 Start Diagnosis", 
            bootstyle="info", 
            command=self._start_diagnostics
        )
        self._diag_button.pack(anchor="w", fill="x")
        
        # Fortschrittsbalken (anfangs versteckt)
        self._diag_progress = ttk.Progressbar(diag_frame, mode='indeterminate', bootstyle="info")
        
        ttk.Button(frm, text="Close", command=_close_admin).pack(anchor="e")

    def _admin_go(self, apply_flags=True):
        """Switches to the selected phase in the admin panel."""
        target = self._admin_phase.get()
        before = {
            "av": self.antivirus_configured,
            "dl": self.downloads_completed,
            "ta": self.talon_completed,
            "ap": self.apps_phase_done,
            "gu": self.guide_completed,
            "exm_done": self.exm_done_once,
            "boosterx_done": self.boosterx_done_once,
        }
        if apply_flags:
            self.antivirus_configured = self._var_av.get()
            self.downloads_completed = self._var_dl.get()
            self.talon_completed = self._var_ta.get()
            self.apps_phase_done = self._var_ap.get()
            self.guide_completed = self._var_gu.get()
            self.exm_done_once = self._var_exm_done.get()
            self.boosterx_done_once = self._var_boosterx_done.get()
            self.save_status()
            self._check_and_maybe_autoadvance_from_tweaker()

        after = {
            "av": self.antivirus_configured,
            "dl": self.downloads_completed,
            "ta": self.talon_completed,
            "ap": self.apps_phase_done,
            "gu": self.guide_completed,
            "exm_done": self.exm_done_once,
            "boosterx_done": self.boosterx_done_once,
        }
        log_event(self.log, "admin_apply", target=target, changed=(before != after))

        if target == self.TAB_APPS:
            self.visited_apps = True
        if target == self.TAB_GUIDE:
            self.visited_guide = True

        phase_map = {
            self.TAB_RESTORE: self.show_restore_prompt,
            self.TAB_ANTIVIRUS: self.show_antivirus_phase,
            self.TAB_DOWNLOAD: self.show_download_phase,
            self.TAB_TALON: self.show_talon_phase,
            self.TAB_TWEAKER: self.show_tweaker_hub,
            self.TAB_LIFETIME_LICENSE: self.show_lifetime_license_phase,
            self.TAB_APPS: self.show_apps_phase,
            self.TAB_GUIDE: self.show_guide_phase,
            self.TAB_FINAL: self.show_final_step,
        }

        if target in phase_map:
            phase_map[target]()

    @log_exceptions()
    def show_restore_prompt(self):
        """Shows the restore point phase."""
        self.clear_frame()
        self.phase_token += 1
        self.current_phase = self.TAB_RESTORE
        self.log.phase = self.TAB_RESTORE
        # Phase sofort persistieren, damit der Start immer auf Restore abbildbar ist
        try:
            self.save_status()
        except Exception:
            pass
        
        main = self.make_responsive_frame()
        self.headline(main, "Restore Point", icon="♻️").grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        txt = ("As a safety measure, a system restore point can be created or an existing one can be used.\n" 
               "This allows returning to a previous state if something goes wrong.")
        self.sublabel(main, txt, justify="left").grid(row=1, column=0, columnspan=2, sticky="nsew")

        pol_text = uac.uac_policy_summary(self.uac_policy or {})
        ttk.Label(main, text=f"UAC: {pol_text}", bootstyle="secondary").grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 8))

        btns = self.button_row(main)
        btns.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        ttk.Button(btns, text="Create Restore Point", bootstyle="primary",
                   command=lambda: operations._create_restore_point(self)).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(btns, text="Use Restore Point", bootstyle="secondary",
                   command=lambda: operations._choose_and_restore_point(self)).grid(row=0, column=1, sticky="ew", padx=(8, 0))

        nxt = ttk.Frame(main)
        nxt.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        nxt.grid_columnconfigure(0, weight=1)
        ttk.Button(nxt, text="Skip", bootstyle="success",
                   command=self._restore_skip_and_continue).grid(row=0, column=0, sticky="ew")

    def _restore_skip_and_continue(self):
        """Skips the restore point phase and continues to the next phase."""
        self.restore_last_action = "skipped"
        self.restore_last_point = None
        self.save_status()
        self.determine_current_phase()

    def determine_current_phase(self):
        """Determines the current phase of the optimizer and shows the corresponding UI."""
        self.log.phase = "flow"
        log_event(self.log, "determine_phase", resume=self.resume_after_restart)
        if self.resume_after_restart == "talon_tab" and self.talon_completed and self.downloads_completed:
            self.resume_after_restart = None
            self.save_status()
            try:
                operations.remove_startup_batch(self)
            except Exception:
                pass
            log_event(self.log, "resume_after_restart", at="talon_tab")
            self.show_tweaker_hub()
            return

        if not self.antivirus_configured:
            self.show_antivirus_phase()
        elif not self.downloads_completed:
            self.show_download_phase()
        elif not self.talon_completed:
            self.show_talon_phase()
        else:
            self.show_tweaker_hub()

    @log_exceptions()
    def show_antivirus_phase(self):
        """Shows the antivirus configuration phase."""
        self.clear_frame()
        self.phase_token += 1
        self.log.phase = self.TAB_ANTIVIRUS
        log_event(self.log, "enter_phase", name=self.TAB_ANTIVIRUS)
        main = self.make_responsive_frame()
        self.headline(main, "Antivirus Configuration", icon="🛡️").grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        if self.is_win10:
            txt = (f"{self.windows_version} (Build {self.windows_build}) detected: Antivirus exception can be skipped (not recommended). "
                   "It will be removed at the end.")
            label = "Optional"
        elif self.is_win11:
            txt = (f"{self.windows_version} (Build {self.windows_build}) detected: Antivirus exception for drive C: is required. "
                   "It will be removed at the end.")
            label = "Required"
        else:
            txt = (f"{self.windows_version} (Build {self.windows_build}) detected: Antivirus exception for drive C: is required. "
                   "It will be removed at the end.")
            label = "Required"
        ttk.Label(main, text=f"Status: {label}").grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self.sublabel(main, txt, justify="left").grid(row=2, column=0, columnspan=2, sticky="nsew")
        btns = self.button_row(main)
        btns.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        ttk.Button(btns, text="🛡️ Configure Antivirus", bootstyle="success",
                   command=self.configure_antivirus).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        if self.is_win10:
            ttk.Button(btns, text="Skip (not recommended)", bootstyle="secondary-outline",
                       command=self.skip_antivirus).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        else:
            ttk.Label(btns, text=f"Action required on {self.windows_version}").grid(row=0, column=1, sticky="ew", padx=(8, 0))

    def skip_antivirus(self):
        """Skips the antivirus configuration phase."""
        if not self.is_win10:
            Messagebox.showwarning("Note", f"Antivirus configuration is required on {self.windows_version}.")
            return
        self.antivirus_configured = False
        self.save_status()
        log_event(self.log, "av_skipped", windows_version=self.windows_version, build=self.windows_build)
        self.show_download_phase()

    @log_exceptions()
    def configure_antivirus(self):
        """Configures the antivirus exclusions."""
        self.log.phase = "antivirus"
        try:
            subprocess.run(['powershell.exe', '-ExecutionPolicy', 'Bypass', '-Command',
                            'Add-MpPreference -ExclusionPath "C:\"'],
                           check=True, capture_output=True, text=True)
            self.antivirus_configured = True
            self.save_status()
            log_event(self.log, "av_configured", path="C:\\")
            Messagebox.showinfo("Erfolg", "Antivirus-Konfiguration abgeschlossen!")
            if self.dev_skip_to_final_after_av:
                self.dev_skip_to_final_after_av = False
                if not self.downloads_completed:
                    self.dev_skip_talon = True
                    self.show_download_phase()
                else:
                    self.show_tweaker_hub()
                return
            self.show_download_phase()
        except Exception as e:
            if Messagebox.askretrycancel("Antivirus-Fehler",
                                         f"Antivirus-Konfiguration fehlgeschlagen:\n{e}\n\nErneut versuchen?"):
                self.configure_antivirus()

    @log_exceptions()
    def show_download_phase(self):
        """Shows the download phase."""
        self.clear_frame()
        self.phase_token += 1
        token = self.phase_token
        self.log.phase = self.TAB_DOWNLOAD
        log_event(self.log, "enter_phase", name=self.TAB_DOWNLOAD)
        main = self.make_responsive_frame()
        win_str = "Windows 10" if self.is_win10 else "Windows 11+"
        self.headline(main, "Prepare Downloads", icon="🚀").grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        ttk.Label(main, text=f"🖥️ Detected: {win_str}").grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        # Note: EXM Tweaks and BoosterX are no longer loaded automatically.
        dl_text = f"{self.talon_name} will be loaded. EXM Tweaks and BoosterX will be installed in the Tweaker Hub as needed."
        self.sublabel(main, dl_text, justify="left").grid(row=2, column=0, columnspan=2, sticky="nsew")

        self.progress_var = tk.StringVar(value="Ready for download...")
        ttk.Label(main, textvariable=self.progress_var).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 6))
        self.progress_bar = ttk.Progressbar(main, mode='determinate', bootstyle="success-striped", maximum=100)
        self.progress_bar.grid(row=4, column=0, columnspan=2, sticky="ew")

        btns = self.button_row(main)
        btns.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        ttk.Button(btns, text="✓ Start Download", bootstyle="primary-outline",
                   command=lambda: self.start_downloads(token)).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(btns, text="✗ Cancel", bootstyle="danger", command=self.root.quit).grid(row=0, column=1, sticky="ew", padx=(8, 0))

    def start_downloads(self, token):
        """Starts the download process."""
        threading.Thread(target=operations.download_files, args=(self, token,), daemon=True, name="dl-worker").start()

    @log_exceptions()
    def show_talon_phase(self):
        """Shows the Talon phase."""
        self.clear_frame()
        self.phase_token += 1
        self.log.phase = self.TAB_TALON
        log_event(self.log, "enter_phase", name=self.TAB_TALON)
        main = self.make_responsive_frame()
        self.headline(main, "System Optimization", icon="⚡").grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        self.sublabel(main, f"{self.talon_name} will be started. After completion, a restart will occur and the app will continue.",
                      justify="left").grid(row=1, column=0, columnspan=2, sticky="nsew")
        btns = self.button_row(main)
        btns.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        ttk.Button(btns, text=f"🚀 Start {self.talon_name}", bootstyle="primary",
                   command=lambda: operations.start_talon(self)).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(btns, text="✗ Cancel", bootstyle="danger",
                   command=self.root.quit).grid(row=0, column=1, sticky="ew", padx=(8, 0))

    @log_exceptions()
    def show_tweaker_hub(self):
        """Shows the Tweaker Hub phase."""
        self.clear_frame()
        self.phase_token += 1
        self.current_phase = self.TAB_TWEAKER
        self.log.phase = self.TAB_TWEAKER
        log_event(self.log, "enter_phase", name=self.TAB_TWEAKER)
        
        # Reload flags from saved status to ensure they're current
        import json
        import os
        config_file = os.path.join(self.BASE_DIR, "optimizer_status.json")
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    st = json.load(f)
                self.exm_done_once = st.get('exm_done_once', False)
                self.boosterx_done_once = st.get('boosterx_done_once', False)
                print(f"DEBUG: Tab loaded from file - exm_done_once={self.exm_done_once}, boosterx_done_once={self.boosterx_done_once}")
            except Exception as e:
                print(f"DEBUG: Error loading status: {e}")
                self.exm_done_once = getattr(self, 'exm_done_once', False)
                self.boosterx_done_once = getattr(self, 'boosterx_done_once', False)
        else:
            self.exm_done_once = getattr(self, 'exm_done_once', False)
            self.boosterx_done_once = getattr(self, 'boosterx_done_once', False)
            print(f"DEBUG: No config file - exm_done_once={self.exm_done_once}, boosterx_done_once={self.boosterx_done_once}")
        
        # Persist phase
        self.save_status()
        main = self.make_responsive_frame()
        self.headline(main, "Tweaker", icon="🔧").grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Label(main, text="Welcome back! System successfully restarted.").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))
        
        self.tweaker_progress_label = ttk.Label(main, textvariable=self.tweaker_progress_text)
        self.tweaker_progress_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.tweaker_progress_bar = ttk.Progressbar(main, mode='determinate', bootstyle="success-striped", maximum=2) # Value set by update method
        self.tweaker_progress_bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        
        # Force update the progress display with current values
        self._update_tweaker_progress_display() # Initial update

        # Vereinfachte Status-Anzeige - automatische Installation/Deinstallation
        exm_status = "completed" if self.exm_done_once else "pending"
        boosterx_status = "completed" if self.boosterx_done_once else "pending"
        
        status = (f"Status:\n"
                  f"• Downloads: {'completed' if self.downloads_completed else 'pending'}\n"
                  f"• Antivirus: {'configured' if self.antivirus_configured else 'skipped/not set'}\n"
                  f"• {self.talon_name}: {'done' if self.talon_completed else 'pending'}\n"
                  f"• EXM Tweaks: {exm_status}\n"
                  f"• BoosterX: {boosterx_status}\n"
                  f"• Restore: {self.restore_last_action or '–'} ({self.restore_last_point or '–'})")
        self.sublabel(main, status, justify="left").grid(row=4, column=0, columnspan=2, sticky="nsew")

        btns = ttk.Frame(main)
        btns.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        btns.grid_columnconfigure(0, weight=1)
        btns.grid_columnconfigure(1, weight=1)
        btns.grid_columnconfigure(2, weight=1)

        # Vereinfachte Button-Labels - automatische Installation/Deinstallation
        if self.exm_done_once:
            label_exm = "Reopen EXM Tweaks"
        else:
            label_exm = "Start EXM Tweaks"
        
        if self.boosterx_done_once:
            label_boosterx = "Reopen BoosterX"
        else:
            label_boosterx = "Start BoosterX"
        
        ttk.Button(btns, text=label_exm, bootstyle="secondary", command=lambda: operations.start_exm(self)).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(btns, text=label_boosterx, bootstyle="secondary", command=lambda: operations.start_boosterx(self)).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        ttk.Button(btns, text="Continue to Lifetime License", bootstyle="primary",
                   command=self.show_lifetime_license_phase).grid(row=0, column=2, sticky="ew", padx=(8, 0))

    def _check_and_maybe_autoadvance_from_tweaker(self):
        """Checks if auto-advance from tweaker hub is possible and performs it."""
        if (
            self.current_phase == self.TAB_TWEAKER and
            self.exm_done_once and
            self.boosterx_done_once and
            not self.tweaker_autoadvance_locked
        ):
            
            self.tweaker_autoadvance_locked = True
            self.last_tweaker_autoadvance_at = time.strftime("%Y-%m-%d %H:%M:%S")
            self.save_status()
            log_event(self.log, "tweaker_autoadvance", at=self.last_tweaker_autoadvance_at)
            self.show_lifetime_license_phase()
        else:
            return

    @log_exceptions()
    def show_lifetime_license_phase(self):
        """Shows the lifetime license phase."""
        self.clear_frame()
        self.phase_token += 1
        self.current_phase = self.TAB_LIFETIME_LICENSE
        self.log.phase = self.TAB_LIFETIME_LICENSE
        log_event(self.log, "enter_phase", name=self.TAB_LIFETIME_LICENSE)
        self.save_status()

        main = self.make_responsive_frame()
        self.headline(main, "Lifetime Windows License", icon="🔑").grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        self.sublabel(main, "This tool uses the Microsoft Activation Scripts (MAS) from massgrave.dev to activate Windows.\nIt is a safe and open-source script that provides a permanent activation for your system.", justify="left").grid(row=1, column=0, columnspan=2, sticky="nsew")

        nav = ttk.Frame(main)
        nav.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Button(nav, text="← Back (Tweaker)", bootstyle="secondary", command=self.show_tweaker_hub).grid(row=0, column=0, sticky="w")

        btns = self.button_row(main)
        btns.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(18, 0))

        ttk.Button(btns, text="Get License", bootstyle="success",
                   command=lambda: self.start_lifetime_license_and_continue()).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(btns, text="Continue to optionale app (skip)", bootstyle="primary",
                     command=self.show_apps_phase).grid(row=0, column=1, sticky="ew", padx=(8, 0))

    def start_lifetime_license_and_continue(self):
        """Starts the lifetime license tool and continues to the next phase."""
        # Bestätigung im Hauptthread
        if not Messagebox.yesno(
            "Do you want to start the download?", title="Confirm"
        ):
            return
            
        def _wait_and_continue():
            process = operations.start_lifetime_license_tool(self)
            if process:
                process.wait()
                self.root.after(0, self.show_apps_phase)

        threading.Thread(target=_wait_and_continue, daemon=True).start()

    def _return_to_tweaker_hub(self):
        """Sets tweaker_autoadvance_locked and returns to tweaker hub."""
        if not self.tweaker_autoadvance_locked:
            self.tweaker_autoadvance_locked = True
            self.save_status()
            log_event(self.log, "tweaker_locked_on_return")
        self.show_tweaker_hub()

    @log_exceptions()
    def show_apps_phase(self):
        """Shows the optional apps phase."""
        self.clear_frame()
        self.phase_token += 1
        self.current_phase = self.TAB_APPS
        self.log.phase = self.TAB_APPS
        self.visited_apps = True
        log_event(self.log, "enter_phase", name=self.TAB_APPS)
        # Phase persistieren
        self.save_status()
        main = self.make_responsive_frame()
        self.headline(main, "Install Optional Apps (Chocolatey)", icon="🧩").grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        self.sublabel(main, "Select and install apps; skipping leads directly to the guide.", justify="left").grid(row=1, column=0, columnspan=2, sticky="nsew")

        nav = ttk.Frame(main)
        nav.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Button(nav, text="← Back (Lifetime License)", bootstyle="secondary", command=self.show_lifetime_license_phase).grid(row=0, column=0, sticky="w")

        apps_frame = ttk.Frame(main)
        apps_frame.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        self.app_vars = {a["key"]: tk.BooleanVar(value=False) for a in self.choco_apps}
        for i, a in enumerate(self.choco_apps):
            ttk.Checkbutton(apps_frame, text=f"{a['name']}{' (pre-release)' if a['prerelease'] else ''}",
                            variable=self.app_vars[a["key"]], bootstyle="round-toggle").grid(row=i, column=0, sticky="w", pady=2, padx=4)

        self._choco_progress_prepare(main)
        self._choco_progress_container.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self._choco_progress_container.grid_remove()

        btns = self.button_row(main)
        btns.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        ttk.Button(btns, text="Install Selected with Chocolatey", bootstyle="primary",
                   command=lambda: operations.install_selected_apps_choco(self)).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(btns, text="Continue to Guide (skip)", bootstyle="success",
                   command=self._complete_apps_and_continue).grid(row=0, column=1, sticky="ew", padx=(8, 0))

    def _complete_apps_and_continue(self):
        """Completes the optional apps phase and continues to the next phase."""
        self.apps_phase_done = True
        self.save_status()
        self.show_guide_phase()

    @log_exceptions()
    def show_guide_phase(self):
        """Shows the guide phase."""
        self.clear_frame()
        self.phase_token += 1
        self.current_phase = self.TAB_GUIDE
        self.log.phase = self.TAB_GUIDE
        self.visited_guide = True
        log_event(self.log, "enter_phase", name=self.TAB_GUIDE)
        # Phase persistieren
        self.save_status()

        main = self.make_responsive_frame()
        self.headline(main, "DLSS Enabler x OptiScaler – Guide", icon="📘").grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        text = ("• DLSS Enabler and OptiScaler can be downloaded here.\n" 
                "• Both tools will be downloaded to the desktop and extracted if necessary.\n" 
                "• If problems occur: check game profiles, overlays, anti-cheat.")
        self.sublabel(main, text, justify="left").grid(row=1, column=0, columnspan=2, sticky="nsew")

        nav = ttk.Frame(main)
        nav.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Button(nav, text="← Back (Optional Apps)", bootstyle="secondary", command=self.show_apps_phase).grid(row=0, column=0, sticky="w")

        links = ttk.Frame(main)
        links.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        links.grid_columnconfigure(0, weight=1)
        links.grid_columnconfigure(1, weight=1)
        
        # Download Buttons mit Bestätigung im Hauptthread
        ttk.Button(links, text="Download DLSS Enabler", bootstyle="primary",
                   command=lambda: self._download_with_confirmation('dlss_enabler')).grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=4)
        ttk.Button(links, text="Download OptiScaler", bootstyle="primary",
                   command=lambda: self._download_with_confirmation('optiscaler')).grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=4)

        # Info Links
        ttk.Button(links, text="DLSS Enabler – Releases", bootstyle="primary-outline",
                   command=lambda: operations.open_url(self, "https://github.com/artur-graniszewski/DLSS-Enabler/releases")).grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=4)
        ttk.Button(links, text="OptiScaler – GitHub", bootstyle="secondary-outline",
                   command=lambda: operations.open_url(self, "https://github.com/optiscaler/OptiScaler")).grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=4)
        ttk.Button(links, text="Video: DLSS 4/DLSS Enabler Basics", bootstyle="info",
                   command=lambda: operations.open_url(self, "https://www.youtube.com/watch?v=hZC83zTVfXk")).grid(row=2, column=0, columnspan=2, sticky="ew", pady=4)
        ttk.Button(links, text="Video: OptiScaler Praxis & Setup", bootstyle="info",
                   command=lambda: operations.open_url(self, "https://www.youtube.com/watch?v=gmZwJmgOdg4")).grid(row=3, column=0, columnspan=2, sticky="ew", pady=4)
        ttk.Button(links, text="Video: FSR3/DLSS FG Mods Explained", bootstyle="info",
                   command=lambda: operations.open_url(self, "https://www.youtube.com/watch?v=7aYjsYDEcYg")).grid(row=4, column=0, columnspan=2, sticky="ew", pady=4)

        btns = self.button_row(main)
        btns.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        ttk.Button(btns, text="Continue", bootstyle="success", command=self._complete_guide_and_continue).grid(row=0, column=1, sticky="ew", padx=(8, 0))

    def _complete_guide_and_continue(self):
        """Completes the guide phase and continues to the next phase."""
        self.guide_completed = True
        self.save_status()
        self.show_final_step()

    @log_exceptions()
    def show_final_step(self):
        """Shows the final step phase."""
        self.clear_frame()
        self.phase_token += 1
        self.current_phase = self.TAB_FINAL
        self.log.phase = self.TAB_FINAL
        log_event(self.log, "enter_phase", name=self.TAB_FINAL)
        # Phase persistieren
        self.save_status()
        main = self.make_responsive_frame()
        self.headline(main, "Final Step", icon="🏁").grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Label(main, text="Final step: Restart and cleanup.").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))

        # Hinweis, falls Antivirus nicht konfiguriert wurde
        if not self.antivirus_configured:
            ttk.Label(main, text="⚠️ Note: Antivirus exception was not configured. Recommended before completion.", bootstyle="warning").grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 8))

        nav = ttk.Frame(main)
        nav.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 6))
        ttk.Button(nav, text="← Back (Guide)", bootstyle="secondary", command=self.show_guide_phase).grid(row=0, column=0, sticky="w")

        # Final tab no longer contains uninstall options; query occurs after closing programs.

        btns = ttk.Frame(main)
        btns.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        btns.grid_columnconfigure(0, weight=1)
        ttk.Button(btns, text="Complete Optimization (Restart)", bootstyle="success",
                   command=lambda: operations.finish_optimization(self)).grid(row=0, column=0, sticky="ew")

    def _on_close(self):
        """Called when the main window is closed."""
        try:
            # Automatische Deinstallation aller Tools beim Schließen
            self._auto_cleanup_tools()
            self.root.destroy()
        except Exception:
            os._exit(0)
    
    def _auto_cleanup_tools(self):
        """Automatische Deinstallation aller Tools beim Schließen."""
        try:
            import shutil
            
            # Talon deinstallieren
            talon_dir = os.path.join(self.download_dir, 'talon')
            if os.path.isdir(talon_dir):
                shutil.rmtree(talon_dir, ignore_errors=True)
                log_event(self.log, 'talon_auto_cleanup_on_exit', path=talon_dir)
            
            # Talon ZIP-Datei entfernen (Windows 10: TalonLite.zip, Windows 11: talon.zip)
            talon_zip_win10 = os.path.join(self.download_dir, 'TalonLite.zip')
            talon_zip_win11 = os.path.join(self.download_dir, 'talon.zip')
            
            if os.path.exists(talon_zip_win10):
                os.remove(talon_zip_win10)
                log_event(self.log, 'talon_zip_auto_cleanup_on_exit', path=talon_zip_win10)
            elif os.path.exists(talon_zip_win11):
                os.remove(talon_zip_win11)
                log_event(self.log, 'talon_zip_auto_cleanup_on_exit', path=talon_zip_win11)
            
            # EXM Tweaks deinstallieren
            exm_dir = os.path.join(self.download_dir, 'exm_tweaks')
            if os.path.isdir(exm_dir):
                shutil.rmtree(exm_dir, ignore_errors=True)
                log_event(self.log, 'exm_auto_cleanup_on_exit', path=exm_dir)
            
            # EXM Tweaks ZIP-Datei entfernen
            exm_zip = os.path.join(self.download_dir, 'exm_tweaks.zip')
            if os.path.exists(exm_zip):
                os.remove(exm_zip)
                log_event(self.log, 'exm_zip_auto_cleanup_on_exit', path=exm_zip)
            
            # BoosterX deinstallieren
            bx_dir = os.path.join(self.download_dir, 'boosterx')
            if os.path.isdir(bx_dir):
                shutil.rmtree(bx_dir, ignore_errors=True)
                log_event(self.log, 'boosterx_auto_cleanup_on_exit', path=bx_dir)
                
            log_event(self.log, 'auto_cleanup_completed')
        except Exception as e:
            log_event(self.log, 'auto_cleanup_failed', err=str(e))
    
    def _download_with_confirmation(self, tool_name: str):
        """Download mit Bestätigung im Hauptthread."""
        if Messagebox.yesno(
            f"Do you really want to download {tool_name}?", title="Confirm Download"
        ):
            operations.download_from_guide(self, tool_name)

    def _update_tweaker_progress_display(self):
        """Updates the tweaker progress text and bar."""
        progress_x = int(self.exm_done_once) + int(self.boosterx_done_once)
        self.tweaker_progress_text.set(f"Fortschritt: {progress_x}/2 abgeschlossen (EXM, BoosterX)")
        self.tweaker_progress_bar.config(value=progress_x)
        print(f"DEBUG: Progress updated - exm_done_once={self.exm_done_once}, boosterx_done_once={self.boosterx_done_once}, progress_x={progress_x}")
        

    def _choco_progress_prepare(self, parent):
        """Initializes the Chocolatey progress bar widgets."""
        if not hasattr(self, "_choco_progress_container") or not self._choco_progress_container.winfo_exists():
            self._choco_progress_container = ttk.Frame(parent)
            self._choco_progressbar = ttk.Progressbar(self._choco_progress_container, mode="indeterminate", bootstyle="success-striped")
            self._choco_progressbar.pack(fill="x", expand=True)

    def _choco_progress_show_start(self):
        """Shows the Chocolatey progress bar and starts the animation."""
        if hasattr(self, "_choco_progress_container") and self._choco_progress_container.winfo_exists():
            self._choco_progress_container.grid()
            if hasattr(self, "_choco_progressbar"):
                self._choco_progressbar.start(10)

    def _choco_progress_stop_hide(self):
        """Stops the Chocolatey progress bar and hides it."""
        if hasattr(self, "_choco_progress_container") and self._choco_progress_container.winfo_exists():
            if hasattr(self, "_choco_progressbar"):
                self._choco_progressbar.stop()
            self._choco_progress_container.grid_remove()

    @log_exceptions()
    def _start_diagnostics(self):
        """Starts the diagnostic process in a separate thread."""
        try:
            # UI-Status aktualisieren
            self._diag_status.set("Starting diagnosis...")
            self._diag_button.config(state="disabled", text="🔍 Diagnosis running...")
            self._diag_progress.pack(fill="x", pady=(0, 8))
            self._diag_progress.start()
            
            # Chocolatey-Fortschritt verstecken falls vorhanden
            if hasattr(self, '_choco_progress_container'):
                self._choco_progress_stop_hide()

            # Diagnose in separatem Thread starten
            diagnostics._run_diagnostics_threaded(
                self, 
                self._diagnostics_callback, 
                self._diagnostics_progress, 
                self._diagnostics_finished
            )
            
        except Exception as e:
            # Fehlerbehandlung
            self._diag_status.set(f"❌ Fehler: {str(e)}")
            self._diag_button.config(state="normal", text="🔍 Diagnose starten")
            self._diag_progress.pack_forget()
            
            # Fehlermeldung anzeigen
            Messagebox.showerror(
                "Diagnose-Fehler",
                f"Fehler beim Starten der Diagnose:\n{str(e)}"
            )

    def _diagnostics_callback(self, message):
        """Callback for diagnostic messages."""
        self._diag_status.set(message)
        self.log.info(f"Diagnostic message: {message}")

    def _diagnostics_progress(self, percent):
        """Callback for diagnostic progress."""
        self._diag_progress.config(value=percent)
        self.log.info(f"Diagnostic progress: {percent}%")

    def _diagnostics_finished(self, success):
        """Callback for diagnostic process finished."""
        self._diag_button.config(state="normal")
        self._diag_progress.pack_forget()
        self._choco_progress_show_start() # Ensure Chocolatey progress is shown

        if success:
            Messagebox.showinfo("Diagnosis Complete", "System diagnosis successfully completed!")
            self.log.info("System diagnosis successfully completed.")
        else:
            Messagebox.showerror("Diagnosis Failed", "System diagnosis failed.")
            self.log.error("System diagnosis failed.")