import sys
import os
from dotenv import load_dotenv

from database import create_tables, list_tables, test_connection

load_dotenv()

print("=" * 50)
print("POSTGRESQL CONFIGURATION")
print("=" * 50)
print("DB_HOST =", os.getenv("DB_HOST"))
print("DB_PORT =", os.getenv("DB_PORT"))
print("DB_NAME =", os.getenv("DB_NAME"))
print("DB_USER =", os.getenv("DB_USER"))

password = os.getenv("DB_PASSWORD", "")
print("DB_PASSWORD Length =", len(password))

if password:
    print("DB_PASSWORD Preview =", password[:2] + "*" * (len(password) - 2))
else:
    print("DB_PASSWORD = NOT FOUND")

print("=" * 50)


def main():
    try:
        print("Testing PostgreSQL connection...")
        test_connection()

        print("Creating tables if they do not exist...")
        create_tables()

    except Exception as error:
        print(f"PostgreSQL connection failed: {error}")
        return 1

    print("\nConnected to PostgreSQL Successfully")
    print("\nDetected tables:")

    tables = list_tables()

    if not tables:
        print("No tables found.")
    else:
        for table_name in tables:
            print(f"- {table_name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())