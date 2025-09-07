import os
import subprocess
import time
import getpass
import shutil
import zipfile
import json
import webbrowser
import requests
import threading
import sys
import ttkbootstrap as tb
from ttkbootstrap.dialogs import Messagebox
from ttkbootstrap import ttk
from typing import Any, Optional

from .logging_setup import log_event
from . import utils

def _set_ui_disabled(app: Any, disabled: bool) -> None:
    """En-/Disable Hauptfenster-Interaktion global."""
    try:
        app.root.attributes("-disabled", bool(disabled))
    except Exception:
        pass


def _confirm_elevated_start(app: Any, title: str, tool_name: str) -> bool:
    """Shows a modal confirmation dialog with OK/Cancel and return value."""
    _set_ui_disabled(app, True)
    win = tb.Toplevel(app.root)
    win.title(title)
    win.geometry("360x160")
    win.transient(app.root)
    win.grab_set()
    win.resizable(False, False)
    frm = ttk.Frame(win, padding=16)
    frm.pack(fill="both", expand=True)
    ttk.Label(
        frm, text=f"{tool_name} will be executed as Administrator."
    ).pack(anchor="w", pady=(0, 8))
    ttk.Label(frm, text="Click OK to continue.").pack(anchor="w")

    result = {"ok": False}

    def _ok():
        result["ok"] = True
        try:
            win.grab_release()
        except Exception:
            pass
        win.destroy()
        _set_ui_disabled(app, False)

    def _cancel():
        result["ok"] = False
        try:
            win.grab_release()
        except Exception:
            pass
        win.destroy()
        _set_ui_disabled(app, False)

    btns = ttk.Frame(frm)
    btns.pack(fill="x", pady=(12, 0))
    ttk.Button(btns, text="OK", bootstyle="success",
               command=_ok).pack(side="left")
    ttk.Button(btns, text="Cancel", bootstyle="secondary",
               command=_cancel).pack(side="right")

    win.protocol("WM_DELETE_WINDOW", _cancel)
    try:
        if hasattr(app, 'center_window'):
            app.center_window(win, 360, 160)
    except Exception:
        pass
    win.wait_window()
    return result["ok"]


def get_startup_batch_path() -> str:
    """Returns the path to the autostart batch file."""
    appdata = os.environ.get("APPDATA") or os.path.join(
        "C:\\Users", getpass.getuser(), "AppData", "Roaming"
    )
    folder = os.path.join(
        appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
    )
    return os.path.join(folder, "optimizer_restart.bat")


def create_startup_batch(app: Any) -> bool:
    """Creates the autostart batch for restart. Returns True on success."""
    try:
        py = sys.executable
        main_script_path = os.path.join(app.BASE_DIR, 'main.py')
        content = (
            f'@echo off\r\ncd /d "{app.BASE_DIR}"\r\n'
            f'"{py}" "{main_script_path}"\r\n'
        )
        os.makedirs(os.path.dirname(app.startup_batch), exist_ok=True)
        with open(app.startup_batch, 'w', encoding='utf-8') as f:
            f.write(content)
        log_event(app.log, "startup_batch_created", path=app.startup_batch)
        return True
    except Exception as e:
        app.log.warning(f"startup_batch_create_failed={e}")
        Messagebox.showerror(
            "Error", f"Startup batch could not be created: {e}")
        return False

def remove_startup_batch(app: Any) -> None:
    """Removes the autostart batch file if present."""
    try:
        if os.path.exists(app.startup_batch):
            os.remove(app.startup_batch)
            log_event(app.log, "startup_batch_removed", path=app.startup_batch)
    except Exception as e:
        app.log.warning(f"startup_batch_remove_failed={e}")

def get_choco_exe() -> str:
    """Liefert Pfad zu choco.exe oder 'choco' als Fallback."""
    programdata = os.environ.get("ALLUSERSPROFILE", r"C:\\ProgramData")
    choco_path = os.path.join(programdata, "chocolatey", "bin", "choco.exe")
    return choco_path if os.path.exists(choco_path) else "choco"


def ensure_chocolatey(app: Any) -> bool:
    """Ensures that Chocolatey is available; installs if necessary."""
    app.log.phase = "choco"
    choco_exe = get_choco_exe()
    try:
        subprocess.run([choco_exe, "-v"], capture_output=True,
                       text=True, timeout=5, check=True)
        os.environ["PATH"] = (
            os.environ.get("PATH", "") + ";" + os.path.dirname(get_choco_exe())
        )
        log_event(app.log, "choco_detected", path=get_choco_exe())
        return True
    except Exception:
        pass
    try:
        ps = (
            "[System.Net.ServicePointManager]::SecurityProtocol = 3072; "
            "Set-ExecutionPolicy Bypass -Scope Process -Force; "
            "iex ((New-Object System.Net.WebClient).DownloadString("
            "'https://community.chocolatey.org/install.ps1'))"
        )
        log_event(app.log, "choco_install_start")
        subprocess.check_call(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy",
                "Bypass", "-Command", ps]
        )
        deadline = time.time() + 90
        while time.time() < deadline:
            if os.path.exists(get_choco_exe()):
                break
            time.sleep(1)
        if not os.path.exists(get_choco_exe()):
            raise RuntimeError("choco.exe not found after install")
        os.environ["PATH"] = (
            os.environ.get("PATH", "") + ";" + os.path.dirname(get_choco_exe())
        )
        log_event(app.log, "choco_install_done", path=get_choco_exe())
        return True
    except Exception as e:
        app.log.error(f"choco_install_failed={e}")
        Messagebox.showerror(
            "Chocolatey", f"Chocolatey-Installation fehlgeschlagen:\n{e}")
        return False

def choco_upgrade(app: Any, pkg: str, prerelease: bool = False) -> bool:
    """Aktualisiert/Installiert ein Paket via Chocolatey. True bei Erfolg."""
    app.log.phase = "choco"
    choco_exe = get_choco_exe()
    args = [choco_exe, "upgrade", pkg, "-y", "--limit-output"]
    if prerelease:
        args.append("--prerelease")
    t0 = time.time()
    try:
        log_event(app.log, "choco_upgrade_start",
                  pkg=pkg, prerelease=prerelease)
        subprocess.check_call(args)
        dt = round(time.time() - t0, 2)
        log_event(app.log, "choco_upgrade_ok", pkg=pkg, seconds=dt)
        return True
    except subprocess.CalledProcessError as e:
        log_event(app.log, "choco_upgrade_fail", pkg=pkg, rc=e.returncode)
        return False
    except Exception as e:
        app.log.error(f"choco_upgrade_error pkg={pkg} err={e}")
        return False


def get_desktop_path() -> str:
    """Pfad zum Desktop des aktuellen Benutzers (Fallback: cwd)."""
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        desk = os.path.join(userprofile, "Desktop")
        if os.path.isdir(desk):
            return desk
    return os.getcwd()


def download_from_guide(app: Any, tool_name: str) -> None:
    """Downloads a tool from the Guide tab to the desktop."""
    app.log.phase = "guide_download"
    log_event(app.log, "guide_download_start", tool=tool_name)

    # Bestätigung muss im Hauptthread erfolgen - wird von GUI gehandhabt
    # if not Messagebox.yesno(
    #     f"Do you really want to download {tool_name}?", title="Confirm Download"
    # ):
    #     log_event(app.log, "guide_download_cancelled", tool=tool_name)
    #     return

    _set_ui_disabled(app, True)

    def _worker():
        result_message = None
        result_title = "Success"
        try:
            if not hasattr(app, 'guide_downloads') or not app.guide_downloads:
                import json
                links_path = os.path.join(
                    getattr(app, 'BASE_DIR', os.getcwd()),
                    "optimizer", "core", "links.json"
                )
                with open(links_path) as f:
                    links = json.load(f)
                app.guide_downloads = links.get("guide_downloads", {})

            url = app.guide_downloads.get(tool_name)
            if not url:
                raise ValueError(
                    f"URL for {tool_name} not found in guide_downloads")

            desktop = get_desktop_path()
            filename = utils.filename_from_url(url, f"{tool_name}.zip")
            target_path = os.path.join(desktop, filename)

            r = requests.get(url, stream=True, timeout=120)
            r.raise_for_status()
            with open(target_path, 'wb') as f:
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk)

            log_event(app.log, "guide_download_ok",
                      tool=tool_name, dest=target_path)

            if filename.lower().endswith('.zip'):
                extract_dir = os.path.join(
                    desktop, os.path.splitext(filename)[0])
                os.makedirs(extract_dir, exist_ok=True)
                with zipfile.ZipFile(target_path, 'r') as z:
                    z.extractall(extract_dir)
                log_event(app.log, "guide_unzip_ok",
                          tool=tool_name, dest=extract_dir)
                result_message = (
                    f"{tool_name} was downloaded and extracted to {extract_dir}."
                )
            else:
                result_message = (
                    f"{tool_name} was downloaded to {target_path}.")

        except Exception as e:
            log_event(app.log, "guide_download_fail",
                      tool=tool_name, err=str(e))
            result_title = "Error"
            result_message = f"Download of {tool_name} failed:\n{e}"
        finally:
            def _show_result():
                try:
                    if result_title == "Error":
                        Messagebox.showerror(result_title, result_message)
                    else:
                        Messagebox.showinfo(result_title, result_message)
                finally:
                    _set_ui_disabled(app, False)
            app.root.after(0, _show_result)

    threading.Thread(
        target=_worker, daemon=True, name=f"{tool_name}-guide-dl").start()

def download_files(app: Any, token: int) -> None:
    """Lädt benötigte Dateien herunter."""
    app.log.phase = "download"
    try:
        total = len(app.download_urls)
        done = 0
        session = requests.Session()
        for name, url in app.download_urls.items():
            app.ui_set(text=f"Lade {name}...", token=token)
            app.ui_set(percent=int((done / total) * 100), token=token)
            t0 = time.time()

            if name == 'talon':
                filename = 'TalonLite.zip' if app.is_win10 else 'talon.zip'
                fp = os.path.join(app.download_dir, filename)
            elif name == 'exm_tweaks':
                filename = 'exm_tweaks.zip'
                fp = os.path.join(app.download_dir, filename)
            elif name == 'boosterx':
                filename = 'BoosterX.exe'
                fp = os.path.join(app.download_dir, 'boosterx', filename)
                utils.ensure_dir(os.path.dirname(fp))
            else:
                filename = 'unknown.bin'
                fp = os.path.join(app.download_dir, filename)

            max_attempts = 3
            attempt = 0
            while True:
                try:
                    log_event(app.log, "download_start", name=name, url=url,
                              filename=filename, dest=fp, attempt=attempt + 1)
                    r = session.get(url, stream=True, timeout=120)
                    r.raise_for_status()
                    with open(fp, 'wb') as f:
                        for chunk in r.iter_content(8192):
                            if chunk:
                                f.write(chunk)

                    expected = getattr(app, 'download_hashes', {}).get(name)
                    if expected:
                        try:
                            algo, hexval = (expected.split(":", 1) + [
                                None])[:2] if ":" in expected else (
                                    "sha256", expected)
                            hexval = (hexval or "").strip().lower()
                            if algo.lower() != "sha256":
                                raise ValueError("Only sha256 is supported")
                            actual = utils.compute_sha256(fp)
                            if actual.lower() != hexval:
                                raise ValueError(
                                    f"SHA256-Mismatch: expected {hexval}, "
                                    f"got {actual}")
                            log_event(app.log, "download_hash_ok", name=name,
                                      filename=filename, dest=fp,
                                      sha256_expected=hexval,
                                      sha256_actual=actual)
                        except Exception as he:
                            log_event(
                                app.log, "download_hash_fail", name=name,
                                filename=filename, dest=fp,
                                sha256_expected=hexval, err=str(he))
                            raise

                    if name in ('talon', 'exm_tweaks') and \
                            filename.lower().endswith('.zip'):
                        out = os.path.join(app.download_dir, name)
                        os.makedirs(out, exist_ok=True)
                        with zipfile.ZipFile(fp, 'r') as z:
                            z.extractall(out)
                        log_event(app.log, "unzipped", name=name,
                                  src_zip=fp, dest_dir=out)

                    dt = round(time.time() - t0, 2)
                    file_bytes = os.path.getsize(fp)
                    log_event(app.log, "download_ok", name=name,
                              filename=filename, dest=fp, seconds=dt,
                              bytes=file_bytes)
                    break
                except Exception as e:
                    attempt += 1
                    if attempt < max_attempts:
                        delay = 2 ** attempt
                        log_event(app.log, "download_retry", name=name,
                                  filename=filename, dest=fp, attempt=attempt,
                                  delay_s=delay)
                        time.sleep(delay)
                        continue
                    if Messagebox.askretrycancel(
                        "Error", f"Download failed for {name}: {e}\n\nRetry?"
                    ):
                        attempt = 0
                        continue
                    else:
                        log_event(
                            app.log, "download_fail", name=name,
                            filename=filename, dest=fp, err=type(e).__name__)
                        return

            done += 1

        app.ui_set(percent=100, text="Downloads abgeschlossen!", token=token)
        app.downloads_completed = True
        app.save_status()

        def _go_next():
            if token != app.phase_token:
                return
            if app.dev_skip_talon:
                app.dev_skip_talon = False
                app.show_tweaker_hub()
            else:
                app.show_talon_phase()
        app.root.after(800, _go_next)
    except Exception as e:
        app.root.after(
            0,
            lambda: Messagebox.showerror(
                "Fehler", f"Unerwarteter Download-Fehler:\n{e}")
        )


def start_talon(app: Any) -> None:
    """Startet Talon im Hintergrund und setzt Resume-Status; UI-Fehlerdialoge bei Bedarf."""
    app.log.phase = "talon"
    if not create_startup_batch(app):
        return
    try:
        talon_dir = os.path.join(app.download_dir, 'talon')
        talon_exe = None
        for root_dir, _, files in os.walk(talon_dir):
            for f in files:
                name = f.lower()
                if name.endswith('.exe') and ('talon' in name or 'talonlite' in name):
                    talon_exe = os.path.join(root_dir, f)
                    break
            if talon_exe:
                break
        if not talon_exe:
            raise FileNotFoundError(f"{app.talon_name}-Executable nicht gefunden!")
        ps_cmd = f'Start-Process -FilePath "{talon_exe}" -WindowStyle Hidden'
        subprocess.Popen(
            ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-NoProfile', '-Command', ps_cmd],
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        log_event(app.log, "talon_started", exe=talon_exe)
        app.talon_completed = True
        app.resume_after_restart = "talon_tab"
        app.save_status()
        app.root.quit()
    except Exception as e:  # noqa: F841, F821
        error_message = f"{app.talon_name} could not be started: {e}"
        app.log.error("talon_start_failed=%s", e)
        Messagebox.showerror("Error", error_message)
        remove_startup_batch(app)


def start_lifetime_license_tool(app: Any) -> None:
    """Starts the lifetime license tool after confirmation."""
    app.log.phase = "lifetime_license"
    
    def _worker():
        try:
            # Download and execute the script
            ps_command = "irm https://get.activated.win | iex"
            process = subprocess.Popen(
                ["powershell.exe", "-Command", ps_command],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            return process
        except Exception as e:
            log_event(app.log, "lifetime_license_error", err=str(e))
            app.root.after(0, lambda: Messagebox.showerror("Error", f"An error occurred: {e}"))
            return None

    return _worker()


def is_exm_installed(app: Any) -> bool:
    """Überprüft ob EXM Tweaks bereits installiert ist."""
    exm_dir = os.path.join(app.download_dir, 'exm_tweaks')
    target_cmd = os.path.join(exm_dir, '!EXM Free Tweaking Utility V9.3.cmd')
    
    if os.path.exists(target_cmd):
        return True
    
    # Suche nach alternativen .cmd-Dateien
    for root_dir, _, files in os.walk(exm_dir):
        for f in files:
            if f.lower().endswith('.cmd') and 'exm' in f.lower():
                return True
    return False

def is_boosterx_installed(app: Any) -> bool:
    """Überprüft ob BoosterX bereits installiert ist."""
    boosterx_exe = os.path.join(app.download_dir, 'boosterx', 'BoosterX.exe')
    return os.path.exists(boosterx_exe)

def start_exm(app: Any) -> None:
    """Starts EXM Tweaks after confirmation; without busy cursor."""
    app.log.phase = "exmhub"
    try:
        # Überprüfe ob EXM bereits installiert ist
        exm_installed = is_exm_installed(app)
        
        # Vorab-Dialog (modal). Abbruch öffnet nichts
        if not _confirm_elevated_start(app, title="EXM Tweaks", tool_name="EXM Tweaks"):
            return

        # Automatische Installation wenn nicht vorhanden
        if not exm_installed:
            log_event(app.log, "exm_auto_install_start")
            # Automatische Installation ohne Nachfrage
            try:
                _attempt_repair_exm(app, os.path.join(app.download_dir, 'exm_tweaks'))
                log_event(app.log, "exm_auto_install_completed")
            except Exception as e:
                log_event(app.log, "exm_auto_install_failed", err=str(e))
                Messagebox.showerror("Error", f"EXM Tweaks could not be automatically installed: {e}")
                return

        # Busy-Cursor für EXM auf Wunsch entfernen (keine Anzeige)

        exm_dir = os.path.join(app.download_dir, 'exm_tweaks')
        target_cmd = os.path.join(exm_dir, '!EXM Free Tweaking Utility V9.3.cmd')
        if not os.path.exists(target_cmd):
            # Reparaturversuch: ZIP erneut entpacken oder Datei im Ordner suchen
            _attempt_repair_exm(app, exm_dir)
            if not os.path.exists(target_cmd):
                # Suche nach einer passenden .cmd-Datei, falls der Name abweicht
                for root_dir, _, files in os.walk(exm_dir):
                    for f in files:
                        if f.lower().endswith('.cmd') and 'exm' in f.lower():
                            target_cmd = os.path.join(root_dir, f)
                            break
                    if os.path.exists(target_cmd):
                        break
            if not os.path.exists(target_cmd):
                raise FileNotFoundError(f"EXM Batch-Datei nicht gefunden: {target_cmd}")
        
        # GEMINI PATCH START: Start EXM with PID tracking
        ps_cmd = f"$p = Start-Process -FilePath '{target_cmd}' -Verb RunAs -PassThru; $p.Id"
        result = subprocess.run(
            ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-NoProfile', '-Command', ps_cmd],
            capture_output=True, text=True, check=True
        )
        pid = int(result.stdout.strip())
        app._exm_pid = pid
        log_event(app.log, "exm_started", cmd=target_cmd, pid=pid)

        # Set flag immediately when EXM starts
        app.exm_done_once = True
        app.save_status()
        print(f"DEBUG: EXM started - exm_done_once set to {app.exm_done_once}")
        app.root.after(0, app._update_tweaker_progress_display)

        # Warten bis Prozess wirklich sichtbar ist (kurzes Polling)
        # Kein Busy-Cursor-Handling für EXM

        # Während EXM läuft, UI deaktivieren; Re-Enable nach Prozessende
        _set_ui_disabled(app, True)
        def _wait_and_enable_exm():
            try:
                wait_for_process_exit(app, pid, 'exm')
            finally:
                app.root.after(0, lambda: _set_ui_disabled(app, False))
        threading.Thread(target=_wait_and_enable_exm, daemon=True, name="exm-waiter").start()
        # GEMINI PATCH END: Start EXM with PID tracking
    except Exception as e:
        app.log.error(f"exm_start_failed={e}")
        Messagebox.showerror("Error", f"EXM Tweaks could not be started: {e}")
        # Kein Cursor-Reset nötig

def start_boosterx(app: Any) -> None:
    """Starts BoosterX after confirmation; shows 1s busy cursor during startup."""
    app.log.phase = "tweakerhub"
    try:
        # Überprüfe ob BoosterX bereits installiert ist
        boosterx_installed = is_boosterx_installed(app)
        
        # Vorab-Dialog (modal). Abbruch öffnet nichts
        if not _confirm_elevated_start(app, title="BoosterX", tool_name="BoosterX"):
            return

        # Automatische Installation wenn nicht vorhanden
        if not boosterx_installed:
            log_event(app.log, "boosterx_auto_install_start")
            # Automatische Installation ohne Nachfrage
            try:
                boosterx_exe = os.path.join(app.download_dir, 'boosterx', 'BoosterX.exe')
                _attempt_repair_boosterx(app, boosterx_exe)
                log_event(app.log, "boosterx_auto_install_completed")
            except Exception as e:
                log_event(app.log, "boosterx_auto_install_failed", err=str(e))
                Messagebox.showerror("Error", f"BoosterX could not be automatically installed: {e}")
                return

        # Busy-Cursor kurz (1s) anzeigen
        try:
            app.root.configure(cursor="wait")
            app.root.update_idletasks()
        except Exception:
            pass

        boosterx_exe = os.path.join(app.download_dir, 'boosterx', 'BoosterX.exe')
        if not os.path.exists(boosterx_exe):
            _attempt_repair_boosterx(app, boosterx_exe)
            if not os.path.exists(boosterx_exe):
                raise FileNotFoundError(f"BoosterX-Executable nicht gefunden: {boosterx_exe}")
        
        # GEMINI PATCH START: Start BoosterX with PID tracking
        ps_cmd = f"$p = Start-Process -FilePath '{boosterx_exe}' -Verb RunAs -PassThru; $p.Id"
        result = subprocess.run(
            ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-NoProfile', '-Command', ps_cmd],
            capture_output=True, text=True, check=True
        )
        pid = int(result.stdout.strip())
        app._boosterx_pid = pid
        log_event(app.log, "boosterx_started", exe=boosterx_exe, pid=pid)

        # Set flag immediately when BoosterX starts
        app.boosterx_done_once = True
        app.save_status()
        print(f"DEBUG: BoosterX started - boosterx_done_once set to {app.boosterx_done_once}")
        app.root.after(0, app._update_tweaker_progress_display)

        # Warten bis Prozess wirklich sichtbar ist (kurzes Polling)
        # 1 Sekunde Busy-Cursor, dann zurück
        time.sleep(1.0)
        try:
            app.root.after(0, lambda: app.root.configure(cursor=""))
        except Exception:
            pass

        _set_ui_disabled(app, True)
        def _wait_and_enable_bx():
            try:
                wait_for_process_exit(app, pid, 'boosterx')
            finally:
                app.root.after(0, lambda: _set_ui_disabled(app, False))
        threading.Thread(target=_wait_and_enable_bx, daemon=True, name="boosterx-waiter").start()
        # GEMINI PATCH END: Start BoosterX with PID tracking
    except Exception as e:
        app.log.error(f"boosterx_start_failed={e}")
        Messagebox.showerror("Error", f"BoosterX could not be started: {e}")
        try:
            app.root.configure(cursor="")
        except Exception:
            pass

def wait_for_process_exit(app: Any, pid: int, tag: str) -> None:
    """Monitors process end (EXM/BoosterX) and updates flags/UI via main thread."""
    app.log.phase = "tweakerhub"
    log_event(app.log, "wait_for_process_exit_start", pid=pid, tag=tag)
    
    process_exited = False
    for _ in range(120):  # Wait up to 2 minutes
        try:
            # Check if process exists using PowerShell
            ps_cmd = f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).Id"
            result = subprocess.run(
                ['powershell.exe', '-NoProfile', '-Command', ps_cmd],
                capture_output=True, text=True, check=False, timeout=5
            )
            if not result.stdout.strip():
                # Zusatzprüfung für EXM: offenes cmd.exe-Fenster mit exm_tweaks in der CommandLine
                if tag == 'exm':
                    try:
                        ps_check_children = (
                            "($p=Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\") | "
                            "Where-Object { $_.CommandLine -match 'exm_tweaks' } | Measure-Object | Select-Object -ExpandProperty Count"
                        )
                        child_res = subprocess.run(
                            ['powershell.exe', '-NoProfile', '-Command', ps_check_children],
                            capture_output=True, text=True, check=False, timeout=5
                        )
                        still_open = False
                        try:
                            cnt = int((child_res.stdout or "0").strip() or 0)
                            still_open = cnt > 0
                        except Exception:
                            still_open = False
                        if still_open:
                            # EXM-CMD läuft noch; weiter warten
                            time.sleep(1)
                            continue
                    except subprocess.TimeoutExpired:
                        pass
                    except Exception:
                        pass
                process_exited = True
                break
        except subprocess.TimeoutExpired:
            log_event(app.log, "wait_for_process_exit_timeout_check", pid=pid, tag=tag)
        except Exception as e:
            log_event(app.log, "wait_for_process_exit_check_error", pid=pid, tag=tag, err=str(e))
            # Fallback to tasklist if Get-Process fails
            try:
                tasklist_cmd = f"tasklist /FI \"PID eq {pid}\""
                tasklist_result = subprocess.run(tasklist_cmd, capture_output=True, text=True, check=False, timeout=5)
                if "No tasks are running" in tasklist_result.stdout:
                    process_exited = True
                    break
            except subprocess.TimeoutExpired:
                log_event(app.log, "wait_for_process_exit_timeout_tasklist", pid=pid, tag=tag)
            except Exception as e_tasklist:
                log_event(app.log, "wait_for_process_exit_tasklist_error", pid=pid, tag=tag, err=str(e_tasklist))
        time.sleep(1)

    if process_exited:
        log_event(app.log, "process_exited", pid=pid, tag=tag)
        # Flags are already set when process starts, no need to set them again here
        
        # Update UI and check for auto-advance on the main thread
        app.root.after(0, lambda: app.ui_set(text=f"{tag.upper()} abgeschlossen!", token=app.phase_token))
        app.root.after(0, app._update_tweaker_progress_display) # Call new update method
        app.root.after(0, app._check_and_maybe_autoadvance_from_tweaker)

        # Automatische Deinstallation nach Prozessende
        def _auto_uninstall():
            try:
                if tag == 'exm':
                    # Entpackten Ordner entfernen
                    exm_dir = os.path.join(app.download_dir, 'exm_tweaks')
                    if os.path.isdir(exm_dir):
                        shutil.rmtree(exm_dir, ignore_errors=True)
                        log_event(app.log, 'exm_auto_removed', path=exm_dir)
                    
                    # ZIP-Datei entfernen
                    exm_zip = os.path.join(app.download_dir, 'exm_tweaks.zip')
                    if os.path.exists(exm_zip):
                        os.remove(exm_zip)
                        log_event(app.log, 'exm_zip_auto_removed', path=exm_zip)
                        
                elif tag == 'boosterx':
                    bx_dir = os.path.join(app.download_dir, 'boosterx')
                    if os.path.isdir(bx_dir):
                        shutil.rmtree(bx_dir, ignore_errors=True)
                        log_event(app.log, 'boosterx_auto_removed', path=bx_dir)
                app.save_status()
            except Exception as e_rm:
                app.log.warning(f"tweaker_auto_remove_failed tag={tag} err={e_rm}")

        try:
            app.root.after(0, _auto_uninstall)
        except Exception:
            pass
    else:
        log_event(app.log, "process_did_not_exit", pid=pid, tag=tag)
        app.root.after(0, lambda: Messagebox.showwarning("Note", f"{tag.upper()} was not terminated or could not be monitored."))

def _attempt_repair_exm(app, exm_dir: str):
    """Versucht EXM erneut bereitzustellen (Zip entpacken oder erneut laden)."""
    try:
        base = app.download_dir
        real_dir = os.path.join(base, 'exm_tweaks')
        utils.ensure_dir(real_dir)
        zip_fp = os.path.join(app.download_dir, 'exm_tweaks.zip')
        if os.path.exists(zip_fp):
            try:
                with zipfile.ZipFile(zip_fp, 'r') as z:
                    z.extractall(real_dir)
                log_event(app.log, "exm_repair_unzip_ok", zip=zip_fp, dest=exm_dir)
                return
            except Exception as e:
                log_event(app.log, "exm_repair_unzip_fail", zip=zip_fp, err=str(e))
        # Falls ZIP fehlt: neu laden (aus tweaker_urls, Fallback download_urls)
        url = (getattr(app, 'tweaker_urls', {}) or {}).get('exm_tweaks')
        if url:
            try:
                r = requests.get(url, stream=True, timeout=120)
                r.raise_for_status()
                with open(zip_fp, 'wb') as f:
                    for chunk in r.iter_content(8192):
                        if chunk:
                            f.write(chunk)
                with zipfile.ZipFile(zip_fp, 'r') as z:
                    z.extractall(real_dir)
                log_event(app.log, "exm_repair_redownload_ok", url=url)
            except Exception as e:
                log_event(app.log, "exm_repair_redownload_fail", url=url, err=str(e))
    except Exception as e:
        log_event(app.log, "exm_repair_error", err=str(e))

def _attempt_repair_boosterx(app, boosterx_exe: str):
    """Versucht BoosterX erneut bereitzustellen (Ordner anlegen und neu laden)."""
    try:
        base = app.download_dir
        bx_dir = os.path.join(base, 'boosterx')
        utils.ensure_dir(bx_dir)
        boosterx_exe = os.path.join(bx_dir, 'BoosterX.exe')
        # aus tweaker_urls, Fallback download_urls
        url = (getattr(app, 'tweaker_urls', {}) or {}).get('boosterx')
        if url:
            try:
                r = requests.get(url, stream=True, timeout=120)
                r.raise_for_status()
                with open(boosterx_exe, 'wb') as f:
                    for chunk in r.iter_content(8192):
                        if chunk:
                            f.write(chunk)
                log_event(app.log, "boosterx_repair_redownload_ok", url=url)
            except Exception as e:
                log_event(app.log, "boosterx_repair_redownload_fail", url=url, err=str(e))
    except Exception as e:
        log_event(app.log, "boosterx_repair_error", err=str(e))

def install_selected_apps_choco(app: Any) -> None:
    """Installs selected applications with Chocolatey in a worker thread."""
    if not ensure_chocolatey(app):
        return
    sel = [a for a in app.choco_apps if app.app_vars[a["key"]].get()]
    if not sel:
        Messagebox.showinfo("Info", "No apps selected.")
        return

    def _worker():
        app.log.phase = "apps"
        fail = []
        
        # UI-Status setzen - Installation läuft
        app.root.after(0, lambda: setattr(app, '_apps_installing', True))
        app.root.after(0, lambda: app._install_button.config(state="disabled", text="Installation running..."))
        app.root.after(0, lambda: app._continue_button.config(state="disabled", text="Installation running..."))
        app.root.after(0, lambda: app._back_button.config(state="disabled", text="← Back (Installation running...)"))
        app.root.after(0, app._choco_progress_show_start)
        
        try:
            for a in sel:
                if not choco_upgrade(app, a["pkg"], prerelease=a.get("prerelease", False)):
                    fail.append(a["name"])
        finally:
            # UI-Status zurücksetzen - Installation beendet
            app.root.after(0, lambda: setattr(app, '_apps_installing', False))
            app.root.after(0, lambda: app._install_button.config(state="normal", text="Install Selected with Chocolatey"))
            app.root.after(0, lambda: app._continue_button.config(state="normal", text="Continue to Guide (skip)"))
            app.root.after(0, lambda: app._back_button.config(state="normal", text="← Back (EXM Tweaks)"))
            app.root.after(0, app._choco_progress_stop_hide)
            
            if fail:
                app.root.after(0, lambda: Messagebox.showwarning("Done (with errors)", f"Failed for: {', '.join(fail)}"))
            else:
                app.root.after(0, lambda: Messagebox.showinfo("Done", "All selected apps have been installed/updated."))
            log_event(app.log, "apps_install_done", failed=len(fail))
    
    threading.Thread(target=_worker, daemon=True, name="choco-worker").start()

def _create_restore_point(app: Any) -> None:
    """Creates a system restore point (busy cursor during creation)."""
    app.log.phase = "restore"
    # Busy-Cursor aktivieren, bis der Restore-Punkt erstellt ist
    try:
        app.root.configure(cursor="wait")
        app.root.update_idletasks()
    except Exception:
        pass
    def _worker():
        try:
            log_event(app.log, "restore_create_start", drive="C:")
            ps = (
                "$drive='C:'; "
                "try { Enable-ComputerRestore -Drive $drive -ErrorAction SilentlyContinue } catch {} ; "
                "Checkpoint-Computer -Description 'Windows Optimizer – Start' -RestorePointType 'APPLICATION_INSTALL'"
            )
            subprocess.check_call(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps])
            log_event(app.log, "restore_create_ok")
            app.restore_last_action = "created"
            app.restore_last_point = "(neu erstellt)"
            app.save_status()
            app.root.after(0, lambda: Messagebox.showinfo("Wiederherstellungspunkt", "Wiederherstellungspunkt wurde erstellt."))
            app.root.after(0, app.determine_current_phase)
        except subprocess.CalledProcessError as e:
            log_event(app.log, "restore_create_fail", rc=e.returncode)
            app.root.after(0, lambda err=e: Messagebox.showerror("Fehler", f"Wiederherstellungspunkt konnte nicht erstellt werden (Code {err.returncode})."))
        except Exception as e:
            log_event(app.log, "restore_create_error", err=type(e).__name__)
            app.root.after(0, lambda err=e: Messagebox.showerror("Fehler", f"Wiederherstellungspunkt-Fehler: {err}"))
        finally:
            # Busy-Cursor zurücksetzen
            try:
                app.root.after(0, lambda: app.root.configure(cursor=""))
            except Exception:
                pass
    threading.Thread(target=_worker, daemon=True, name="restore-create").start()

def _choose_and_restore_point(app: Any) -> None:
    """Opens a selection to use a restore point (centered)."""
    app.log.phase = "restore"
    win = tb.Toplevel(app.root)
    win.title("Select Restore Point")
    win.geometry("680x420")
    # Dialog zentrieren
    try:
        app.center_window(win, 680, 420) if hasattr(app, 'center_window') else None
    except Exception:
        pass
    frm = ttk.Frame(win, padding=12)
    frm.pack(fill="both", expand=True)
    cols = ("seq", "created", "desc")
    tv = ttk.Treeview(frm, columns=cols, show="headings", height=12, selectmode="extended")
    for c, w in zip(cols, (100, 180, 360)):
        tv.heading(c, text={"seq":"ID","created":"Created","desc":"Description"}[c])
        tv.column(c, width=w, anchor="w")
    tv.pack(fill="both", expand=True)
    btns = ttk.Frame(frm)
    btns.pack(fill="x", pady=(8, 0))
    
    def _use_selected():
        sel = tv.selection()
        if not sel:
            Messagebox.showwarning("Note", "Please select a restore point.")
            return
        if len(sel) != 1:
            Messagebox.showwarning("Note", "Please select exactly one point to restore.")
            return
        seq = tv.item(sel[0], "values")[0]
        win.destroy()
        _restore_point_and_reboot(app, seq)
    
    def _load_points():
        try:
            ps = "Get-ComputerRestorePoint | Select-Object SequenceNumber, Description, CreationTime | Sort-Object CreationTime -Descending | ConvertTo-Json -Depth 3"
            out = subprocess.check_output(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps], text=True, errors='ignore')
            
            log_event(app.log, "restore_powershell_output", output_length=len(out), output_preview=out[:200])
            
            if not out.strip():
                app.root.after(0, lambda: tv.insert("", "end", values=("No restore points", "found", "on this system")))
                log_event(app.log, "restore_list_empty")
                return
                
            data = json.loads(out)
            if isinstance(data, dict):
                data = [data]
            
            if not data:
                app.root.after(0, lambda: tv.insert("", "end", values=("No restore points", "found", "on this system")))
                log_event(app.log, "restore_list_empty_after_parse")
                return
            
            # UI-Updates im Hauptthread
            def update_ui():
                for item in data:
                    if not item:  # Skip None items
                        continue
                    seq = item.get("SequenceNumber")
                    desc = item.get("Description", "Unknown")
                    created_raw = item.get("CreationTime")
                    
                    # Format CreationTime für bessere Lesbarkeit
                    try:
                        if created_raw and len(created_raw) >= 14:
                            # Format: YYYYMMDDHHMMSS.ffffff-fff
                            date_str = created_raw[:8]  # YYYYMMDD
                            time_str = created_raw[8:14]  # HHMMSS
                            formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"
                            created = formatted_date
                        else:
                            created = created_raw or "Unknown"
                    except Exception:
                        created = created_raw or "Unknown"
                    
                    tv.insert("", "end", values=(seq, created, desc))
            
            app.root.after(0, update_ui)
            
            ids = [str(item.get("SequenceNumber")) for item in data if item and item.get("SequenceNumber")]
            log_event(app.log, "restore_list_ok", count=len(ids))
            log_event(app.log, "restore_list_ids", ids=",".join(ids))
            
        except json.JSONDecodeError as e:
            log_event(app.log, "restore_json_decode_error", err=str(e), output_preview=out[:500] if 'out' in locals() else "No output")
            app.root.after(0, lambda: tv.insert("", "end", values=("JSON Error", "Failed to parse", "restore points data")))
            app.root.after(0, lambda err=e: Messagebox.showerror("Error", f"Failed to parse restore points data:\n{err}"))
        except Exception as e:
            log_event(app.log, "restore_list_fail", err=type(e).__name__, details=str(e))
            app.root.after(0, lambda: tv.insert("", "end", values=("Error", "Failed to load", "restore points")))
            app.root.after(0, lambda err=e: Messagebox.showerror("Error", f"List of restore points could not be loaded:\n{err}"))
    
    sel_btn = ttk.Button(btns, text="Restore Selected Point", bootstyle="danger", command=_use_selected)
    sel_btn.pack(side="left")
    ttk.Button(btns, text="Refresh", bootstyle="secondary", command=_load_points).pack(side="left", padx=(8, 0))
    ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")
    
    # Restore Points beim Öffnen des Dialogs in einem Thread laden
    threading.Thread(target=_load_points, daemon=True, name="restore-load").start()

def _restore_point_and_reboot(app: Any, seq: int) -> None:
    """Restores system to a specific restore point and restarts."""
    app.log.phase = "restore"
    def _worker():
        try:
            log_event(app.log, "restore_use_start", seq=seq)
            ps = f"Restore-Computer -RestorePoint {seq} -Confirm:$false"
            subprocess.check_call(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps])
            log_event(app.log, "restore_use_ok", seq=seq)
            app.restore_last_action = "restored"
            app.restore_last_point = str(seq)
            app.save_status()
            app.root.after(0, lambda: Messagebox.showinfo("Restore", "The restore has been started. The PC will restart."))
            subprocess.run(['shutdown', '/r', '/t', '5'])
            app.root.after(0, app.root.quit)
        except subprocess.CalledProcessError as e:
            log_event(app.log, "restore_use_fail", rc=e.returncode)
            app.root.after(0, lambda err=e: Messagebox.showerror("Error", f"Restore failed (Code {err.returncode})."))
        except Exception as e:
            log_event(app.log, "restore_use_error", err=type(e).__name__)
            app.root.after(0, lambda err=e: Messagebox.showerror("Error", f"Restore error: {err}"))
    threading.Thread(target=_worker, daemon=True, name="restore-use").start()

def finish_optimization(app: Any) -> None:
    """Asks for final restart, performs cleanup and exits the app."""
    ok = Messagebox.yesno("All optimizations are complete.\n" 
                             "Perform restart now and clean up temporary files?\n\n" 
                             "Restart in 5 seconds.",
                             title="Final Completion")
    if ok:
        cleanup_and_restart(app, force=True)

def cleanup_and_restart(app: Any, force: bool = False) -> None:
    """Cleans up temporary files/status and performs restart (force => /f)."""
    app.log.phase = "cleanup"
    try:
        remove_startup_batch(app)
        if app.antivirus_configured:
            subprocess.run(['powershell.exe', '-ExecutionPolicy', 'Bypass', '-Command',
                            'Remove-MpPreference -ExclusionPath "C:\\"'],
                           capture_output=True, timeout=15, text=True)
            log_event(app.log, "av_exclusion_removed", path="C:\\")
        # Talon-Ordner und ZIP-Datei immer entfernen
        try:
            # Entpackten Ordner entfernen
            talon_dir = os.path.join(app.download_dir, 'talon')
            if os.path.isdir(talon_dir):
                shutil.rmtree(talon_dir, ignore_errors=True)
                log_event(app.log, "talon_removed", path=talon_dir)
            
            # ZIP-Datei entfernen (Windows 10: TalonLite.zip, Windows 11: talon.zip)
            talon_zip_win10 = os.path.join(app.download_dir, 'TalonLite.zip')
            talon_zip_win11 = os.path.join(app.download_dir, 'talon.zip')
            
            if os.path.exists(talon_zip_win10):
                os.remove(talon_zip_win10)
                log_event(app.log, "talon_zip_removed", path=talon_zip_win10)
            elif os.path.exists(talon_zip_win11):
                os.remove(talon_zip_win11)
                log_event(app.log, "talon_zip_removed", path=talon_zip_win11)
                
        except Exception as e_rm_talon:
            app.log.warning(f"talon_remove_failed={e_rm_talon}")
        # Entfernt: EXM/BoosterX-Löschung basierend auf Final-Tab-Optionen (Abfrage erfolgt direkt nach Schließen)
        if os.path.exists(app.config_file):
            os.remove(app.config_file)
            log_event(app.log, "status_removed", file=app.config_file)
        shutdown_cmd = ['shutdown', '/r', '/f', '/t', '5'] if force else ['shutdown', '/r', '/t', '10']
        log_event(app.log, "reboot_invoke", force=force)
        subprocess.run(shutdown_cmd)
        app.root.quit()
    except Exception as e:
        app.log.error(f"cleanup_failed={e}")
        Messagebox.showinfo("Info", f"Cleanup partially failed: {e}\nSystem will still restart.")
        subprocess.run(['shutdown', '/r', '/f', '/t', '5'] if force else ['shutdown', '/r', '/t', '10'])
        app.root.quit()

def open_url(app: Any, url: str) -> None:
    """Opens a URL in the default browser (with logging/error dialog)."""
    try:
        webbrowser.open(url, new=2)
        log_event(app.log, "open_url", url=url)
    except Exception as e:
        app.log.warning(f"open_url_failed={e}")
        Messagebox.showerror("Error", f"Link could not be opened:\n{e}")

def open_logs_folder(app: Any) -> None:
    """Opens the log directory in Explorer; shows error dialog for problems."""
    try:
        os.startfile(app.LOG_DIR)
        log_event(app.log, "logs_opened", path=app.LOG_DIR)
    except Exception as e:
        Messagebox.showerror("Error", f"Logs could not be opened:\n{e}")

def run_diagnostics(app: Any) -> Optional[Any]:
    """Delegates diagnosis to the diagnostics module and returns its result."""
    try:
        from . import diagnostics as _diag
        return _diag.run_diagnostics(app)
    except Exception as e:
        app.log.error(f"diagnostics_delegate_failed={e}")
        Messagebox.showerror("Diagnose", f"Diagnose konnte nicht gestartet werden: {e}")
        return None

# Hash-Berechnung in utils.py ausgelagert