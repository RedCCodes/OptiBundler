import os
import sys
import platform
import getpass
import shutil
import subprocess
import requests
import threading
import re  # Added for Windows version detection

from tkinter import messagebox
import time
from datetime import datetime

from .logging_setup import log_event, setup_diagnostics_logging, log_diagnostic
from . import uac
from . import operations


def run_diagnostics(app):
    """Führt eine umfassende Diagnose durch.

    Thread-Sicherheit:
        UI-Updates erfolgen ausschließlich via app.root.after(...).
    Ergebnisse:
        Schreibt eine Textdatei in logs/diagnostics/ und erzeugt Events.
    """
    diag_logger, log_filepath = setup_diagnostics_logging()

    start_time = time.time()
    log_diagnostic(diag_logger, "=" * 80)
    log_diagnostic(diag_logger, "DIAGNOSE GESTARTET")
    log_diagnostic(
        diag_logger,
        f"Zeitstempel: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    log_diagnostic(diag_logger, "=" * 80)

    app.log.phase = "diagnostics"
    log_event(app.log, "diag_start",
              user=getpass.getuser(),
              cwd=os.getcwd(),
              py=sys.version.split()[0],
              os=f"{platform.system()} {platform.release()}")

    try:
        if hasattr(app, '_diagnostics_update_status'):
            app.root.after(
                0,
                lambda: app._diagnostics_update_status(
                    "System-Informationen werden gesammelt..."
                )
            )

        log_diagnostic(diag_logger, "\n--- SYSTEM-INFORMATIONEN ---")
        log_diagnostic(diag_logger, f"Benutzer: {getpass.getuser()}")
        log_diagnostic(diag_logger, f"Aktuelles Verzeichnis: {os.getcwd()}")
        log_diagnostic(diag_logger,
                       f"Python-Version: {sys.version.split()[0]}")

        try:
            output = subprocess.check_output("ver", shell=True, text=True)
            version_match = re.search(r'(\d+)\.(\d+)\.(\d+)', output)
            if version_match:
                major, minor, build = map(int, version_match.groups())

                if major == 10 and minor == 0:
                    if build < 22000:
                        windows_name = "Windows 10"
                    else:
                        windows_name = "Windows 11"
                else:
                    windows_name = f"Windows {major}.{minor} (nicht unterstützt)"

                log_diagnostic(
                    diag_logger,
                    f"Betriebssystem: {windows_name} (Build {build})"
                )
                log_diagnostic(
                    diag_logger,
                    f"Windows-Version: {major}.{minor}.{build}"
                )

                if not (major == 10 and minor == 0):
                    log_diagnostic(
                        diag_logger,
                        "WARNUNG: Nur Windows 10/11 werden unterstützt.",
                        "WARNING"
                    )
            else:
                log_diagnostic(
                    diag_logger,
                    f"Betriebssystem: {platform.system()} {platform.release()}"
                )
        except Exception as e:
            log_diagnostic(
                diag_logger,
                f"Betriebssystem: {platform.system()} {platform.release()}"
            )
            log_diagnostic(
                diag_logger,
                f"Windows-Versionserkennung fehlgeschlagen: {e}",
                "WARNING"
            )

        log_diagnostic(
            diag_logger, f"Architektur: {platform.architecture()[0]}")
        log_diagnostic(diag_logger, f"Maschine: {platform.machine()}")
        log_diagnostic(diag_logger, f"Prozessor: {platform.processor()}")

        if hasattr(app, '_diagnostics_update_status'):
            app.root.after(
                0,
                lambda: app._diagnostics_update_status(
                    "UAC/Admin-Status wird geprüft..."
                )
            )

        log_diagnostic(diag_logger, "\n--- UAC/ADMIN-STATUS ---")
        is_admin = False
        try:
            is_admin = uac.is_token_elevated()
            log_diagnostic(diag_logger, f"Token erhöht: {is_admin}")
        except Exception as e:
            log_diagnostic(diag_logger,
                           f"Token-Check fehlgeschlagen: {e}", "ERROR")

        pol = app.uac_policy or {}
        log_diagnostic(
            diag_logger, f"UAC-Policy: EnableLUA={pol.get('EnableLUA')}")
        log_diagnostic(
            diag_logger,
            f"UAC-Policy: ConsentAdmin={pol.get('ConsentPromptBehaviorAdmin')}"
        )
        log_diagnostic(
            diag_logger,
            f"UAC-Policy: SecureDesktop={pol.get('PromptOnSecureDesktop')}"
        )

        log_event(app.log, "diag_admin_token_elevated", is_admin=is_admin)
        log_event(app.log, "diag_uac_policy",
                  EnableLUA=pol.get("EnableLUA"),
                  ConsentAdmin=pol.get("ConsentPromptBehaviorAdmin"),
                  SecureDesktop=pol.get("PromptOnSecureDesktop"))

        if hasattr(app, '_diagnostics_update_status'):
            app.root.after(
                0,
                lambda: app._diagnostics_update_status(
                    "Umgebungsvariablen werden geprüft..."
                )
            )

        log_diagnostic(diag_logger, "\n--- UMGEBUNGSVARIABLEN ---")
        path_length = len(os.environ.get("PATH", ""))
        log_diagnostic(diag_logger, f"PATH-Länge: {path_length} Zeichen")
        if path_length > 2048:
            log_diagnostic(
                diag_logger,
                "WARNUNG: PATH ist sehr lang (>2048 Zeichen)",
                "WARNING"
            )

        log_event(app.log, "diag_path_len", length=path_length)

        if hasattr(app, '_diagnostics_update_status'):
            app.root.after(
                0,
                lambda: app._diagnostics_update_status(
                    "Festplatten-Informationen werden gesammelt..."
                )
            )

        log_diagnostic(diag_logger, "\n--- FESTPLATTEN-INFORMATIONEN ---")
        try:
            total, used, free = shutil.disk_usage(app.download_dir)
            free_mb = int(free / (1024 * 1024))
            total_mb = int(total / (1024 * 1024))
            used_mb = int(used / (1024 * 1024))

            log_diagnostic(
                diag_logger, f"Download-Verzeichnis: {app.download_dir}")
            log_diagnostic(diag_logger, f"Freier Speicher: {free_mb} MB")
            log_diagnostic(diag_logger, f"Verwendeter Speicher: {used_mb} MB")
            log_diagnostic(diag_logger, f"Gesamtspeicher: {total_mb} MB")

            if free_mb < 1000:
                log_diagnostic(
                    diag_logger,
                    "WARNUNG: Wenig freier Speicherplatz (<1GB)",
                    "WARNING"
                )

            log_event(app.log, "diag_disk",
                      path=app.download_dir, free_mb=free_mb)
        except Exception as e:
            log_diagnostic(
                diag_logger, f"Festplatten-Check fehlgeschlagen: {e}", "ERROR")
            log_event(app.log, "diag_disk_fail",
                      err=type(e).__name__, msg=str(e))

        if hasattr(app, '_diagnostics_update_status'):
            app.root.after(
                0,
                lambda: app._diagnostics_update_status(
                    "Chocolatey-Status wird geprüft..."
                )
            )

        log_diagnostic(diag_logger, "\n--- CHOCOLATEY-STATUS ---")
        choco_exe = operations.get_choco_exe()
        choco_version = "n/a"
        choco_present = False
        try:
            result = subprocess.run(
                [choco_exe, "-v"],
                capture_output=True, text=True, timeout=5, check=True
            )
            choco_version = result.stdout.strip()
            choco_present = True
            log_diagnostic(diag_logger, f"Chocolatey gefunden: {choco_exe}")
            log_diagnostic(diag_logger,
                           f"Chocolatey-Version: {choco_version}")
        except Exception as e:
            log_diagnostic(
                diag_logger, f"Chocolatey-Check fehlgeschlagen: {e}", "ERROR")
            log_event(app.log, "diag_choco_check_fail",
                      err=type(e).__name__, msg=str(e))

        log_event(app.log, "diag_choco", path=choco_exe,
                  present=choco_present, version=choco_version)

        if hasattr(app, '_diagnostics_update_status'):
            app.root.after(
                0,
                lambda: app._diagnostics_update_status(
                    "Download-URLs werden geprüft..."
                )
            )

        log_diagnostic(diag_logger, "\n--- DOWNLOAD-URL-CHECKS ---")
        if hasattr(app, 'download_urls'):
            for key, url in app.download_urls.items():
                try:
                    t0 = time.time()
                    r = requests.head(url, timeout=5, allow_redirects=True)
                    dt = round(time.time() - t0, 2)
                    log_diagnostic(
                        diag_logger,
                        f"URL {key}: Status {r.status_code}, Latenz {dt}s"
                    )
                    log_event(app.log, "diag_url", key=key,
                              status=r.status_code, ms=int(dt * 1000))
                except Exception as e:
                    log_diagnostic(
                        diag_logger, f"URL {key} fehlgeschlagen: {e}", "ERROR")
                    log_event(app.log, "diag_url_fail", key=key,
                              err=type(e).__name__, msg=str(e))
        else:
            log_diagnostic(
                diag_logger, "Download-URLs nicht verfügbar", "WARNING")

        if hasattr(app, '_diagnostics_update_status'):
            app.root.after(
                0,
                lambda: app._diagnostics_update_status(
                    "Windows Defender-Status wird geprüft..."
                )
            )

        log_diagnostic(diag_logger, "\n--- WINDOWS DEFENDER-STATUS ---")
        defender_exclusion_status = "n/a"
        try:
            cmd = ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-Command',
                   '(Get-MpPreference).ExclusionPath -contains "C:\"']
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
            defender_exclusion_status = "True" in (p.stdout or "")
            log_diagnostic(
                diag_logger,
                f"Defender-Ausschluss für C:\\: {defender_exclusion_status}"
            )
            log_event(
                app.log,
                "diag_defender_exclusion",
                has_exclusion=defender_exclusion_status
            )
        except Exception as e:
            log_diagnostic(
                diag_logger, f"Defender-Check fehlgeschlagen: {e}", "ERROR")
            log_event(app.log, "diag_defender_fail",
                      err=type(e).__name__, msg=str(e))

        if hasattr(app, '_diagnostics_update_status'):
            app.root.after(
                0,
                lambda: app._diagnostics_update_status(
                    "Anwendungs-Status wird geprüft..."
                )
            )

        log_diagnostic(diag_logger, "\n--- ANWENDUNGS-STATUS ---")
        log_diagnostic(
            diag_logger, f"Downloads abgeschlossen: {app.downloads_completed}")
        log_diagnostic(
            diag_logger, f"Antivirus konfiguriert: {app.antivirus_configured}")
        log_diagnostic(
            diag_logger, f"Talon abgeschlossen: {app.talon_completed}")
        log_diagnostic(
            diag_logger, f"Apps-Phase erledigt: {app.apps_phase_done}")
        log_diagnostic(
            diag_logger, f"Guide abgeschlossen: {app.guide_completed}")
        log_diagnostic(
            diag_logger,
            f"EXM abgeschlossen: {getattr(app, 'exm_done_once', False)}"
        )
        log_diagnostic(
            diag_logger,
            f"BoosterX abgeschlossen: {getattr(app, 'boosterx_done_once', False)}"
        )

        if hasattr(app, '_diagnostics_update_status'):
            app.root.after(
                0,
                lambda: app._diagnostics_update_status(
                    "Netzwerk-Status wird geprüft..."
                )
            )

        log_diagnostic(diag_logger, "\n--- NETZWERK-STATUS ---")
        try:
            result = subprocess.run(
                ['ping', '-n', '1', '8.8.8.8'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                log_diagnostic(
                    diag_logger, "Internetverbindung: OK (8.8.8.8 erreichbar)")
            else:
                log_diagnostic(
                    diag_logger,
                    "Internetverbindung: FEHLER (8.8.8.8 nicht erreichbar)",
                    "WARNING"
                )
        except Exception as e:
            log_diagnostic(
                diag_logger, f"Netzwerk-Check fehlgeschlagen: {e}", "ERROR")

        if hasattr(app, '_diagnostics_update_status'):
            app.root.after(
                0,
                lambda: app._diagnostics_update_status(
                    "Python-Pakete werden geprüft..."
                )
            )

        log_diagnostic(diag_logger, "\n--- PYTHON-PAKETE ---")
        required_packages = ["ttkbootstrap", "requests", "tkinter"]
        for pkg in required_packages:
            try:
                if pkg == "tkinter":
                    log_diagnostic(diag_logger, f"{pkg}: Verfügbar")
                else:
                    module = __import__(pkg)
                    version = getattr(module, '__version__', 'unbekannt')
                    log_diagnostic(
                        diag_logger, f"{pkg}: Verfügbar (Version: {version})")
            except ImportError:
                log_diagnostic(diag_logger, f"{pkg}: NICHT VERFÜGBAR", "ERROR")

        if hasattr(app, '_diagnostics_update_status'):
            app.root.after(
                0,
                lambda: app._diagnostics_update_status(
                    "Diagnose wird abgeschlossen..."
                )
            )

        end_time = time.time()
        duration = round(end_time - start_time, 2)
        log_diagnostic(diag_logger, "\n" + "=" * 80)
        log_diagnostic(
            diag_logger, f"DIAGNOSE ABGESCHLOSSEN - Dauer: {duration}s")
        log_diagnostic(
            diag_logger, f"Log-Datei: {os.path.basename(log_filepath)}")
        log_diagnostic(diag_logger, "=" * 80)

        app.root.after(
            0,
            lambda: messagebox.showinfo(
                "Diagnose abgeschlossen",
                "Diagnose erfolgreich abgeschlossen!"
            )
        )

        if hasattr(app, '_diag_button'):
            app.root.after(
                0,
                lambda: app._diag_button.config(
                    state="normal", text="🔍 Diagnose starten"
                )
            )
        if hasattr(app, '_diag_progress'):
            app.root.after(0, lambda: app._diag_progress.stop())
            app.root.after(0, lambda: app._diag_progress.grid_remove())
        if hasattr(app, '_diag_status'):
            app.root.after(
                0,
                lambda: app._diag_status.set(
                    "✅ Diagnose erfolgreich abgeschlossen"
                )
            )

    except Exception as e:
        log_diagnostic(
            diag_logger, f"KRITISCHER FEHLER bei der Diagnose: {e}", "CRITICAL")
        log_diagnostic(diag_logger, f"Traceback: {sys.exc_info()}")

        if hasattr(app, '_diag_button'):
            app.root.after(
                0,
                lambda: app._diag_button.config(
                    state="normal", text="🔍 Diagnose starten"
                )
            )
        if hasattr(app, '_diag_progress'):
            app.root.after(0, lambda: app._diag_progress.stop())
            app.root.after(0, lambda: app._diag_progress.grid_remove())
        if hasattr(app, '_diag_status'):
            app.root.after(
                0, lambda: app._diag_status.set("❌ Diagnose fehlgeschlagen"))

        app.root.after(
            0,
            lambda err=e: messagebox.showerror(
                "Diagnose-Fehler",
                f"Bei der Diagnose ist ein Fehler aufgetreten:\n{err}"
            )
        )


def _run_diagnostics_threaded(
    app,
    status_callback=None,
    progress_callback=None,
    completion_callback=None
):
    """Startet die Diagnose in einem eigenständigen Thread."""

    def _diagnostics_worker():
        try:
            if status_callback:
                app.root.after(0, lambda: status_callback("Diagnose läuft..."))

            if hasattr(app, '_diag_progress'):
                app.root.after(0, lambda: app._diag_progress.start())

            if status_callback:
                app.root.after(
                    0, lambda: status_callback("Test-Diagnose läuft..."))
                time.sleep(2)

            run_diagnostics(app)

            if completion_callback:
                app.root.after(0, lambda: completion_callback(True))

        except Exception as e:
            if status_callback:
                app.root.after(
                    0, lambda err=e: status_callback(f"Fehler: {str(err)}"))
            if completion_callback:
                app.root.after(0, lambda: completion_callback(False))
        finally:
            if hasattr(app, '_diag_progress'):
                app.root.after(0, lambda: app._diag_progress.stop())

    threading.Thread(
        target=_diagnostics_worker,
        daemon=True,
        name="diagnostics-worker"
    ).start()
