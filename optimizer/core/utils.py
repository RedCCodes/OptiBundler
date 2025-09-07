import hashlib
import os
from typing import Optional


def compute_sha256(file_path: str) -> str:
    """Compute the SHA256 hash of a file.

    Params:
        file_path: Absolute or relative path to the file.

    Returns:
        Hex-encoded SHA256 string.

    Raises:
        FileNotFoundError: If the file does not exist.
        OSError: For other IO-related errors.
    """
    hasher = hashlib.sha256()
    with open(file_path, 'rb') as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def filename_from_url(url: Optional[str], default_name: str) -> str:
    """Derive a filename from a URL.

    Falls die URL leer/ungültig ist, wird default_name zurückgegeben.
    Query-Parameter werden entfernt.
    """
    try:
        if not url or not isinstance(url, str):
            return default_name
        name = url.split('/')[-1].split('?')[0]
        return name or default_name
    except Exception:
        return default_name


def ensure_dir(path: str) -> None:
    """Ensure directory existence (idempotent)."""
    os.makedirs(path, exist_ok=True)



