"""Format durations for display."""


def format_duration(seconds: int) -> str:
    """Return seconds formatted as H:MM:SS."""
    if seconds < 0:
        raise ValueError("seconds cannot be negative")
    hours = seconds // 3600
    minutes = seconds // 60
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:02d}"
