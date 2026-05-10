"""
Manual data validation script.

Run this script to validate data quality in the database.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import DatabaseManager
from src.validator import DataValidator


def main():
    """Main function to run validation."""
    print("=" * 60)
    print("Data Validation Tool")
    print("=" * 60)
    print()

    try:
        # Initialize components
        db_manager = DatabaseManager()
        validator = DataValidator(db_manager)

        # Validate both tables
        for table_name in ['btc_15m', 'btc_1h']:
            print(f"\nValidating {table_name}...")
            print("-" * 60)

            # Get record count first
            count = db_manager.get_record_count(table_name)
            print(f"Total records: {count}")

            if count == 0:
                print(f"⚠️  No data in {table_name}")
                continue

            # Run validation
            results = validator.validate_all(table_name, limit=100)

            # Generate and print report
            report = validator.generate_report(results)
            print(report)

        print("\n" + "=" * 60)
        print("Validation complete")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
