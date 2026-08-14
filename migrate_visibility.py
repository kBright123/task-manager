#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('/workspace/task-manager/instance/tasks.db')
c = conn.cursor()
try:
    c.execute('ALTER TABLE kb_document ADD COLUMN visibility TEXT DEFAULT "private"')
    print('Column added successfully')
except Exception as e:
    print(f'Error (may already exist): {e}')
conn.commit()
conn.close()
