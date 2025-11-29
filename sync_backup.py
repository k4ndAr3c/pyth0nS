import os
from time import sleep
import shutil
import sys

def get_dirs_from_file(file_path):
    """Reads a file and returns a set of directory paths."""
    try:
        with open(file_path, 'r') as f:
            # Strip whitespace and ignore empty lines
            return {line.strip() for line in f if line.strip()}
    except FileNotFoundError:
        print(f"Error: File not found at {file_path}")
        sys.exit(1)

def main(local_list_file, remote_list_file):
    """
    Compares two files listing directories, and copies directories that are
    in the remote list but not the local one from a backup source.
    """
    # --- Configuration ---
    # The source directory from which to copy the missing folders.
    # This location should be accessible, like a mounted drive.
    BACKUP_SOURCE_ROOT = "/mnt/RT-FILES/GITs"
    DESTINATION_ROOT = "." # Current directory
    if not os.path.isdir(BACKUP_SOURCE_ROOT):
        print("Mount p17 share pls !")
        os.system("mount p17:/Stockage /mnt/RT-FILES")
        for _ in range(10):
            sleep(1)
            print(".", end="", flush=True)
        print()
        print("Ooops i've done it !")
        if not os.path.isdir(BACKUP_SOURCE_ROOT):
            exit("Mount p17 share pls !")

    # 1. Read the directory lists from the input files
    local_dirs = get_dirs_from_file(local_list_file)
    remote_dirs = get_dirs_from_file(remote_list_file)

    # 2. Find which directories are in the remote list but not the local one
    dirs_to_copy = sorted(list(remote_dirs - local_dirs))
    print(dirs_to_copy)

    if not dirs_to_copy:
        print("All directories are in sync. No backup needed.")
        os.system("umount /mnt/RT-FILES")
        print('RT-FILES unmounted !')
        return

    print(f"Found {len(dirs_to_copy)} directories to copy from backup...")

    # 3. Copy each missing directory from the backup source
    for dir_name in dirs_to_copy:
        # Clean up the name to be a relative path
        relative_dir_path = dir_name.strip("./")

        source_path = os.path.join(BACKUP_SOURCE_ROOT, relative_dir_path)
        destination_path = os.path.join(DESTINATION_ROOT, relative_dir_path)

        # Check if the destination already exists to avoid errors
        if os.path.exists(destination_path):
            print(f"Skipping '{relative_dir_path}': already exists in destination.")
            continue

        # Check if the source directory actually exists before trying to copy
        if not os.path.exists(source_path):
            print(f"Skipping '{relative_dir_path}': not found in backup source '{BACKUP_SOURCE_ROOT}'.")
            continue

        print(f"Copying '{source_path}' to '{destination_path}'...")
        try:
            # Copy the entire directory tree
            shutil.copytree(source_path, destination_path)
        except Exception as e:
            print(f"Error copying directory '{relative_dir_path}': {e}")

    print("\nBackup process complete.")
    os.system("umount /mnt/RT-FILES")
    print('RT-FILES unmounted !')

def send_p17(a):
    if a == "start":
        os.system("ssh p17 'cd /Stockage/GITs ; find . -maxdepth 2 -type d 2>/dev/null > 000_LIST_ALL_GITS'")
        os.system("ssh p17 '/etc/init.d/nfs start'")
    elif a == "stop":
        os.system("ssh p17 '/etc/init.d/nfs stop'")

if __name__ == "__main__":
    send_p17("start")
    os.system("find . -maxdepth 2 -type d 2>/dev/null > 000_LIST_ALL_GITS")
    os.system("scp p17:/Stockage/GITs/000_LIST_ALL_GITS /tmp")
    local_file = "000_LIST_ALL_GITS"
    remote_file = "/tmp/000_LIST_ALL_GITS"
    main(local_file, remote_file)
    send_p17("stop")
