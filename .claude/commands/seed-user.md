---
description: Create a single dummy user in the database
allowed-tools: Read, Bash(python3:*)
---

Read `database/db.py` for the users table schema and the `get_db()` helper. It
already has `create_user(name, email, password)`, which hashes the password with
werkzeug and returns the new id — **reuse it** instead of writing raw INSERT SQL, and
instead of calling `generate_password_hash` yourself.

`create_user` raises `sqlite3.IntegrityError` on a duplicate email (the column is
UNIQUE), which is the cleanest way to implement the retry-until-unique step below.

Then write and run a Python script using Bash that:

1. Generates a realistic random Indian user using your 
   own knowledge of common Indian names across regions:
   - Name: a realistic Indian first + last name
   - Email: derived from the name with a random 2-3 digit 
     number suffix (e.g. rahul.sharma91@gmail.com)
   - Password: "password123" hashed with werkzeug's 
     generate_password_hash
   - created_at: current datetime

2. Checks if the generated email already exists in the 
   users table. If it does, regenerate until unique.

3. Inserts the user into the database using the same 
   get_db() pattern found in db.py.

4. Prints confirmation:
   - id
   - name
   - email
