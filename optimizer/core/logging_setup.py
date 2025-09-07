import logging
import os
import sys
import uuid
import atexit
import traceback
import json
from logging.handlers import RotatingFileHandler
from ttkbootstrap.dialogs import Messagebox
from datetime import datetime

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "optimizer.log")

SESSION_ID = str(uuid.uuid4())


class JsonFormatter(logging.Formatter):
    """Formats log records as structured JSON."""

    def format(self, record):
        """Formats a log record as a JSON string."""
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "session_id": getattr(record, "sid", SESSION_ID),
            "thread": record.threadName,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "phase": getattr(record, "phase", "n/a"),
        }
        if isinstance(record.msg, dict):
            data = record.msg.copy()
            for key in ("action", "category", "severity", "error_code",
                        "duration_ms", "request_id", "parent_id",
                        "flags_snapshot"):
                if key in data:
                    log_record[key] = data.pop(key)
            log_record["message"] = log_record.get("action", "log_event")
            if data:
                log_record["details"] = data
        else:
            log_record["message"] = record.getMessage()
            log_record["severity"] = record.levelname

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_record)


class PhaseFilter(logging.Filter):
    """Adds phase and session ID to log records."""

    def filter(self, record):
        """Adds phase and session ID to a log record."""
        if not hasattr(record, "phase"):
            record.phase = "n/a"
        if not hasattr(record, "sid"):
            record.sid = SESSION_ID
        return True


class AutoRotatingFileHandler(logging.FileHandler):
    """Custom file handler that automatically rotates logs at 500 lines."""
    
    def __init__(self, filename, mode='a', encoding=None, delay=False):
        super().__init__(filename, mode, encoding, delay)
        self.line_count = 0
        self._count_lines()
    
    def _count_lines(self):
        """Counts current lines in the log file."""
        try:
            if os.path.exists(self.baseFilename):
                with open(self.baseFilename, 'r', encoding=self.encoding or 'utf-8') as f:
                    self.line_count = sum(1 for _ in f)
        except Exception:
            self.line_count = 0
    
    def emit(self, record):
        """Emits a log record and checks for rotation."""
        try:
            # Prüfe auf Rotation vor dem Schreiben
            if self.line_count >= 500:
                self._rotate_log()
            
            # Schreibe den Log-Eintrag
            super().emit(record)
            self.line_count += 1
            
        except Exception:
            self.handleError(record)
    
    def _rotate_log(self):
        """Rotates the log file, keeping the last 50 lines."""
        try:
            # Schließe den aktuellen File-Handler
            self.close()
            
            if os.path.exists(self.baseFilename):
                with open(self.baseFilename, 'r', encoding=self.encoding or 'utf-8') as f:
                    lines = f.readlines()
                
                # Behalte die letzten 50 Zeilen
                backup_lines = lines[-50:] if len(lines) > 50 else lines
                
                # Leere die Datei und schreibe Backup
                with open(self.baseFilename, 'w', encoding=self.encoding or 'utf-8') as f:
                    f.write("=== LOG ROTATION - Previous entries preserved ===\n")
                    f.writelines(backup_lines)
                    f.write("=== LOG ROTATION COMPLETED ===\n")
                
                # Setze den Zeilenzähler zurück
                self.line_count = len(backup_lines) + 2  # +2 für die Rotation-Markierungen
                
                # Logge die Rotation
                logger = logging.getLogger()
                logger.info("Log file rotated - kept last 50 lines")
            
            # Öffne den File-Handler wieder
            self.stream = self._open()
                
        except Exception as e:
            # Fallback: Einfach die Datei leeren
            try:
                self.close()
                with open(self.baseFilename, 'w', encoding=self.encoding or 'utf-8') as f:
                    f.write("=== LOG ROTATION - File cleared ===\n")
                self.line_count = 1
                self.stream = self._open()
            except Exception:
                pass


def clear_log_if_large():
    """Clears the log file if it exceeds 500 lines."""
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > 500:
                # Backup der letzten 50 Zeilen behalten
                backup_lines = lines[-50:] if len(lines) > 50 else lines
                
                with open(LOG_FILE, "w", encoding="utf-8") as f:
                    f.write("")
                
                # Backup-Zeilen wieder hinzufügen
                if backup_lines:
                    with open(LOG_FILE, "a", encoding="utf-8") as f:
                        f.writelines(backup_lines)
                
                # Log-Eintrag über das Clearing
                logger = logging.getLogger()
                if logger.handlers:
                    logger.info("Log file cleared as it exceeded 500 lines. Last 50 lines preserved.")
    except Exception as e:
        logger = logging.getLogger()
        if logger.handlers:
            logger.warning(f"Could not clear log file: {e}")


def check_and_rotate_log():
    """Checks log file size and rotates if necessary. Can be called during runtime."""
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > 500:
                clear_log_if_large()
                return True
    except Exception as e:
        logger = logging.getLogger()
        if logger.handlers:
            logger.warning(f"Could not check log file size: {e}")
    return False


def setup_logging(level=logging.INFO):
    """Sets up JSON file and console logging."""
    clear_log_if_large()
    logger = logging.getLogger()
    logger.setLevel(level)

    formatter = JsonFormatter(datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = AutoRotatingFileHandler(
        LOG_FILE, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    file_handler.addFilter(PhaseFilter())

    console_formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | sid=%(sid)s | %(threadName)s | "
            "%(funcName)s:%(lineno)d | phase=%(phase)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(level)
    console_handler.addFilter(PhaseFilter())

    if not logger.handlers:
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    def _global_excepthook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.getLogger("optimizer").critical(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_traceback),
            extra={"phase": "fatal", "sid": SESSION_ID}
        )
    sys.excepthook = _global_excepthook

    def _threading_excepthook(args):
        logging.getLogger("optimizer").critical(
            "Unhandled thread exception",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            extra={"phase": "fatal", "sid": SESSION_ID}
        )
    try:
        import threading as _t
        _t.excepthook = _threading_excepthook
    except Exception:
        pass

    @atexit.register
    def _on_exit():
        lg = logging.getLogger("optimizer")
        lg.info(
            "process_exit",
            extra={
                "phase": "exit",
                "sid": SESSION_ID,
                "details": {"reason": "atexit"}
            }
        )
        for h in list(lg.parent.handlers if lg.parent else []):
            try:
                h.flush()
            except Exception:
                pass

    return logger


class PhaseLoggerAdapter(logging.LoggerAdapter):
    """A logger adapter that adds phase and session ID to log records."""

    def process(self, msg, kwargs):
        """Processes the log message and adds extra context."""
        extra = kwargs.get("extra", {})
        extra.setdefault("phase", extra.get("phase", getattr(self, "phase", "n/a")))
        extra.setdefault("sid", SESSION_ID)
        kwargs["extra"] = extra
        return msg, kwargs


def log_event(adapter: PhaseLoggerAdapter, action: str, **fields):
    """Logs an event with a specific action and fields."""
    # Prüfe auf Log-Rotation vor dem Loggen
    check_and_rotate_log()
    
    log_data = {"action": action}
    log_data.update(fields)
    adapter.info(log_data)


def log_exceptions(adapter_attr: str = "log"):
    """A decorator that logs exceptions."""
    def _decorator(func):
        def _wrapper(self, *args, **kwargs):
            adapter: PhaseLoggerAdapter = getattr(self, adapter_attr,
                                                 logging.getLogger("noop"))
            try:
                return func(self, *args, **kwargs)
            except SystemExit:
                raise
            except Exception as e:
                adapter.error("Exception occurred", extra={
                    "exception": type(e).__name__,
                    "message": str(e),
                    "traceback": traceback.format_exc()
                })
                try:
                    Messagebox.showerror("Fehler", f"{type(e).__name__}: {e}")
                except Exception:
                    pass
        return _wrapper
    return _decorator


DIAGNOSTICS_LOG_DIR = os.path.join(LOG_DIR, "diagnostics")


def setup_diagnostics_logging():
    """Erstellt den Diagnose-Log-Ordner und gibt den Logger zurück."""
    os.makedirs(DIAGNOSTICS_LOG_DIR, exist_ok=True)

    diag_logger = logging.getLogger("diagnostics")
    diag_logger.setLevel(logging.INFO)

    for handler in diag_logger.handlers[:]:
        diag_logger.removeHandler(handler)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_filename = f"diagnostics_{timestamp}.txt"
    log_filepath = os.path.join(DIAGNOSTICS_LOG_DIR, log_filename)

    file_handler = logging.FileHandler(log_filepath, encoding='utf-8')
    file_handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    diag_logger.addHandler(file_handler)

    return diag_logger, log_filepath


def log_diagnostic(logger, message, level="INFO"):
    """Loggt eine Diagnose-Nachricht in die separate Datei."""
    if level.upper() == "INFO":
        logger.info(message)
    elif level.upper() == "WARNING":
        logger.warning(message)
    elif level.upper() == "ERROR":
        logger.error(message)
    elif level.upper() == "CRITICAL":
        logger.critical(message)
