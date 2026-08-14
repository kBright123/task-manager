#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('./instance/tasks.db')
c = conn.cursor()
c.execute('ALTER TABLE kb_document ADD COLUMN visibility TEXT DEFAULT "private"')

conn.commit()
conn.close()
