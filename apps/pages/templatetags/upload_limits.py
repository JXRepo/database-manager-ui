from decimal import Decimal

from django import template
from django.conf import settings


register = template.Library()


def _binary_size(size_bytes):
    """
    Format a configured byte allowance with explicit binary units

    Parameters
    ----------
    size_bytes : int
        Configured maximum number of bytes.

    Returns
    -------
    str
        Exact allowance expressed in GiB, MiB, KiB, or bytes.
    """
    for divisor, unit in ((1024 ** 3, "GiB"), (1024 ** 2, "MiB"), (1024, "KiB")):
        if size_bytes >= divisor:
            value = Decimal(size_bytes) / divisor
            return f"{value.normalize():f} {unit}"
    return f"{size_bytes} bytes"


@register.simple_tag
def upload_limits():
    """
    Read current upload allowances for the upload page

    Reading settings during rendering keeps the visible limits aligned with
    the validators when deployments change their allowances.

    Returns
    -------
    dict
        Counts and readable sizes and durations for the upload limits section.
    """
    rate = settings.PILOT_RATE_LIMITS["upload"]
    return {
        "max_files": settings.PILOT_MAX_UPLOAD_FILES,
        "file_size": _binary_size(settings.PILOT_MAX_UPLOAD_FILE_BYTES),
        "combined_size": _binary_size(settings.PILOT_MAX_UPLOAD_REQUEST_BYTES),
        "max_objects": f"{settings.PILOT_MAX_UPLOAD_OBJECTS:,}",
        "max_depth": settings.PILOT_MAX_JSON_DEPTH,
        "stored_size": _binary_size(settings.PILOT_MAX_USER_JSON_BYTES),
        "attempts": rate["limit"],
        "window": _duration(rate["window_seconds"]),
        "background_enabled": bool(settings.UPLOAD_INSTANCE_ID),
        "processing_window": _duration(settings.UPLOAD_JOB_MAX_SECONDS),
    }


def _duration(seconds):
    """
    Format a configured duration without rounding

    Parameters
    ----------
    seconds : int
        Duration in whole seconds.

    Returns
    -------
    str
        Duration expressed in whole hours, minutes, or seconds.
    """
    seconds = int(seconds)
    for divisor, unit in ((3600, "hour"), (60, "minute"), (1, "second")):
        if seconds % divisor == 0:
            count = seconds // divisor
            return f"{count} {unit}{'' if count == 1 else 's'}"
