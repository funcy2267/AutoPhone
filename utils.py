import os
import json
from pathlib import Path
from datetime import datetime, date
from typing import List, Tuple

args = None

def json_datetime_serializer(obj):
    """Serializes datetime objects into ISO 8601 format for JSON compatibility."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

def cleanup_calls(directory: str, keep_count: int):
    """
    Identifies and deletes call directories older than the 'keep_count' based on
    their modification time.
    """
    print(f"Starting cleanup in directory: '{directory}'...")
    
    dir_path = Path(directory)

    if not dir_path.is_dir():
        return

    # Find all subdirectories and sort them by modification time
    try:
        dir_times: List[Tuple[float, Path]] = []
        
        for item_path in dir_path.iterdir():
            if item_path.is_dir():
                mod_time = os.path.getmtime(item_path)
                dir_times.append((mod_time, item_path))

        # Check if we have enough directories to warrant deletion
        if len(dir_times) <= keep_count:
            print(f"Only {len(dir_times)} calls found. No cleanup needed (keeping {keep_count}).")
            return

        # Sort the directories by modification time in descending order (newest first)
        dir_times.sort(key=lambda x: x[0], reverse=True)

        # Identify directories to keep and directories to delete
        dirs_to_keep = [p for t, p in dir_times[:keep_count]]
        dirs_to_delete = [p for t, p in dir_times[keep_count:]]

        # Execute deletion
        print("-" * 40)
        print(f"Found {len(dir_times)} calls in total. Keeping {len(dirs_to_keep)}.")
        print("Calls to be kept (Newest):")
        for d in dirs_to_keep:
            print(f"  [KEEP] {d.name}")

        print("\nCalls to be deleted (Oldest):")
        deleted_count = 0
        
        import shutil
        for dir_to_delete in dirs_to_delete:
            try:
                # Delete the directory and its contents
                shutil.rmtree(dir_to_delete)
                print(f"  [DELETED] {dir_to_delete.name}")
                deleted_count += 1
            except OSError as e:
                print(f"  [ERROR] Failed to delete {dir_to_delete.name}: {e}")

        print("-" * 40)
        print(f"Cleanup finished. Total calls deleted: {deleted_count}")

    except Exception as e:
        print(f"An unexpected error occurred during file operation: {e}")
