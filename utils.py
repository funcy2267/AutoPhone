import os
from pathlib import Path
from datetime import datetime, date
from typing import List, Tuple

def json_datetime_serializer(obj):
    """Serializes datetime objects into ISO 8601 format for JSON compatibility."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

def cleanup_files(directory: str, pattern: str, keep_count: int):
    """
    Identifies and deletes files older than the 'keep_count' based on
    their modification time.
    """
    print(f"Starting cleanup in directory: '{directory}'...")
    
    dir_path = Path(directory)

    if not dir_path.is_dir():
        return

    # Find all files matching the pattern and sort them by modification time
    try:
        file_times: List[Tuple[float, Path]] = []
        
        for file_path in dir_path.glob(pattern):
            if file_path.is_file():
                mod_time = os.path.getmtime(file_path)
                file_times.append((mod_time, file_path))

        # Check if we have enough files to warrant deletion
        if len(file_times) <= keep_count:
            print(f"Only {len(file_times)} files found. No cleanup needed (keeping {keep_count}).")
            return

        # Sort the files by modification time in descending order (newest first)
        file_times.sort(key=lambda x: x[0], reverse=True)

        # Identify files to keep and files to delete
        files_to_keep = [p for t, p in file_times[:keep_count]]
        files_to_delete = [p for t, p in file_times[keep_count:]]

        # Execute deletion
        print("-" * 40)
        print(f"Found {len(file_times)} files in total. Keeping {len(files_to_keep)}.")
        print("Files to be kept (Newest):")
        for file in files_to_keep:
            print(f"  [KEEP] {file.name}")

        print("\nFiles to be deleted (Oldest):")
        deleted_count = 0
        
        for file_to_delete in files_to_delete:
            try:
                # Delete the file
                file_to_delete.unlink()
                print(f"  [DELETED] {file_to_delete.name}")
                deleted_count += 1
            except OSError as e:
                print(f"  [ERROR] Failed to delete {file_to_delete.name}: {e}")

        print("-" * 40)
        print(f"Cleanup finished. Total files deleted: {deleted_count}")

    except Exception as e:
        print(f"An unexpected error occurred during file operation: {e}")
