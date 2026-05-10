"""
Database backup script.

Creates a backup of the SQLite database with timestamp.
"""

import sys
import os
import shutil
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.config import Config


def main():
    """Main function to backup database."""
    print("=" * 60)
    print("Database Backup Tool")
    print("=" * 60)
    print()

    try:
        # Get database path from config
        config = Config()
        db_path = Path(config.db_path)

        if not db_path.exists():
            print(f"❌ Database file not found: {db_path}")
            sys.exit(1)

        # Create backup directory
        backup_dir = Path("backups")
        backup_dir.mkdir(exist_ok=True)

        # Generate backup filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"crypto_data_backup_{timestamp}.db"
        backup_path = backup_dir / backup_filename

        # Get database size
        db_size_mb = db_path.stat().st_size / (1024 * 1024)

        print(f"Source: {db_path}")
        print(f"Size: {db_size_mb:.2f} MB")
        print(f"Backup: {backup_path}")
        print()
        print("Creating backup...")

        # Copy database file
        shutil.copy2(db_path, backup_path)

        # Verify backup
        if backup_path.exists():
            backup_size_mb = backup_path.stat().st_size / (1024 * 1024)
            print(f"✅ Backup created successfully!")
            print(f"   Size: {backup_size_mb:.2f} MB")
            print(f"   Location: {backup_path.absolute()}")
        else:
            print("❌ Backup verification failed")
            sys.exit(1)

        # List all backups
        print()
        print("Available backups:")
        backups = sorted(backup_dir.glob("crypto_data_backup_*.db"), reverse=True)

        if backups:
            for i, backup in enumerate(backups[:5], 1):  # Show last 5
                size_mb = backup.stat().st_size / (1024 * 1024)
                print(f"  {i}. {backup.name} ({size_mb:.2f} MB)")

            if len(backups) > 5:
                print(f"  ... and {len(backups) - 5} more")

        print()
        print("=" * 60)
        print("Backup complete")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
