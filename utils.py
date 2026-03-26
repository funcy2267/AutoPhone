import os
import shutil
from pathlib import Path
from datetime import datetime, date

args = None

def json_datetime_serializer(obj):
    """Serializes datetime objects into ISO 8601 format for JSON compatibility."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

def cleanup_calls(directory: str, keep_count: int):
    """Deletes old call directories, keeping only the newest 'keep_count'."""
    dir_path = Path(directory)
    if not dir_path.is_dir():
        return

    # Get all call subdirectories
    calls = [p for p in dir_path.iterdir() if p.is_dir()]
    if len(calls) <= keep_count:
        return

    # Sort calls by modification time (newest first)
    calls.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    # Delete older calls
    for call_dir in calls[keep_count:]:
        try:
            shutil.rmtree(call_dir)
            print(f"Cleaned up old call log: {call_dir.name}")
        except OSError as e:
            print(f"Failed to delete {call_dir.name}: {e}")
