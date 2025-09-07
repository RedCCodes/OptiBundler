import json
import os
import logging

from .logging_setup import log_event, PhaseLoggerAdapter, SESSION_ID
from typing import Any

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
CONFIG_FILE = os.path.join(BASE_DIR, "optimizer_status.json")


def load_status(app: Any) -> None:
    """Lädt den gespeicherten Anwendungsstatus aus der JSON-Datei."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                st = json.load(f)
            app.downloads_completed = st.get('downloads_completed', False)
            app.antivirus_configured = st.get('antivirus_configured', False)
            app.talon_completed = st.get('talon_completed', False)
            app.exm_used = st.get('exm_used', False)
            app.boosterx_used = st.get('boosterx_used', False)
            app.current_theme = st.get(
                'current_theme', getattr(app, 'current_theme', 'vapor')
            )
            app.exm_done_once = st.get('exm_done_once', False)
            app.boosterx_done_once = st.get('boosterx_done_once', False)
            app.tweaker_autoadvance_locked = st.get(
                'tweaker_autoadvance_locked', False
            )
            app.last_tweaker_autoadvance_at = st.get(
                'last_tweaker_autoadvance_at', None
            )
            app.resume_after_restart = st.get('resume_after_restart', None)
            app.guide_completed = st.get('guide_completed', False)
            app.apps_phase_done = st.get('apps_phase_done', False)
            app.restore_last_action = st.get('restore_last_action', None)
            app.restore_last_point = st.get('restore_last_point', None)
            app.current_phase = st.get(
                'current_phase', getattr(app, 'current_phase', None)
            )
            log_event(
                PhaseLoggerAdapter(
                    logging.getLogger("optimizer"),
                    {"phase": "init", "sid": SESSION_ID}
                ),
                "status_loaded",
                resume=app.resume_after_restart,
                dl=app.downloads_completed,
                av=app.antivirus_configured,
                talon=app.talon_completed,
                restore_action=app.restore_last_action,
                restore_point=app.restore_last_point)
        except Exception as e:
            logging.getLogger().warning(
                f"status_load_failed={e}",
                extra={"phase": "init", "sid": SESSION_ID}
            )


def save_status(app: Any) -> None:
    """Persistiert den aktuellen Anwendungsstatus in die JSON-Datei."""
    st = {
        'downloads_completed': app.downloads_completed,
        'antivirus_configured': app.antivirus_configured,
        'talon_completed': app.talon_completed,
        'exm_used': app.exm_used,
        'boosterx_used': app.boosterx_used,
        'current_theme': getattr(app, 'current_theme', 'vapor'),
        'exm_done_once': app.exm_done_once,
        'boosterx_done_once': app.boosterx_done_once,
        'tweaker_autoadvance_locked': app.tweaker_autoadvance_locked,
        'last_tweaker_autoadvance_at': app.last_tweaker_autoadvance_at,
        'resume_after_restart': app.resume_after_restart,
        'guide_completed': app.guide_completed,
        'apps_phase_done': app.apps_phase_done,
        'restore_last_action': app.restore_last_action,
        'restore_last_point': app.restore_last_point,
        'current_phase': getattr(app, 'current_phase', None)
    }
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(st, f)
        log_event(app.log, "status_saved")
    except Exception as e:
        logging.getLogger().warning(
            f"status_save_failed={e}",
            extra={"phase": "persist", "sid": SESSION_ID}
        )
