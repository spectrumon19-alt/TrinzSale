#!/usr/bin/env python3
"""
Create or promote a Super Admin user.
Run once from the project root:  python create_superadmin.py
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

def main():
    username  = input("Username       : ").strip()
    password  = input("Password       : ").strip()
    full_name = input("Full name      : ").strip()
    email     = input("Email          : ").strip()

    if not username or not password:
        print("[ERROR] Username and password are required.")
        sys.exit(1)

    # Hash password using the same algorithm as the app
    from passlib.hash import pbkdf2_sha256
    password_hash = pbkdf2_sha256.hash(password)

    # Connect to DB
    try:
        import psycopg2
    except ImportError:
        print("[ERROR] psycopg2 not installed. Run: pip install psycopg2-binary")
        sys.exit(1)

    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        import urllib.parse
        p = urllib.parse.urlparse(db_url)
        conn = psycopg2.connect(
            host=p.hostname, port=p.port or 5432,
            dbname=p.path.lstrip('/'), user=p.username, password=p.password,
        )
    else:
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", 5432)),
            dbname=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
        )

    cur = conn.cursor()

    # Check if username already exists
    cur.execute("SELECT user_id, role FROM users WHERE username = %s", (username,))
    existing = cur.fetchone()

    if existing:
        user_id, current_role = existing
        confirm = input(f"User '{username}' exists (role: {current_role}). Promote to Super Admin? [y/N]: ")
        if confirm.strip().lower() != 'y':
            print("Aborted.")
            cur.close(); conn.close()
            sys.exit(0)
        cur.execute("UPDATE users SET role = 'Super Admin' WHERE user_id = %s", (user_id,))
        conn.commit()
        print(f"[OK] '{username}' promoted to Super Admin.")
    else:
        cur.execute(
            "INSERT INTO users (username, password_hash, role, full_name, email) "
            "VALUES (%s, %s, 'Super Admin', %s, %s)",
            (username, password_hash, full_name, email)
        )
        conn.commit()
        print(f"[OK] Super Admin '{username}' created successfully.")

    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
