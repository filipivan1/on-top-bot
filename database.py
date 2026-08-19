import os
import sqlite3
from pathlib import Path

class Database:
    def __init__(self, path="moderation.sqlite3"):
        self.path = Path(path)
        self.conn = None

    async def initialize(self):
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            moderator_id INTEGER, reason TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL, user_id INTEGER,
            moderator_id INTEGER, action TEXT NOT NULL,
            reason TEXT, duration INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS config (
            guild_id INTEGER PRIMARY KEY,
            banned_words TEXT NOT NULL DEFAULT '',
            spam_count INTEGER NOT NULL DEFAULT 6,
            spam_window INTEGER NOT NULL DEFAULT 8,
            spam_timeout INTEGER NOT NULL DEFAULT 10,
            raid_join_count INTEGER NOT NULL DEFAULT 8,
            raid_window INTEGER NOT NULL DEFAULT 20,
            raid_lockdown INTEGER NOT NULL DEFAULT 120,
            appeal_url TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS appeals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        self.conn.commit()

    async def close(self):
        if self.conn:
            self.conn.close()

    async def add_warning(self, guild_id, user_id, moderator_id, reason):
        cur = self.conn.execute(
            "INSERT INTO warnings (guild_id,user_id,moderator_id,reason) VALUES (?,?,?,?)",
            (guild_id, user_id, moderator_id, reason))
        self.conn.commit()
        return cur.lastrowid

    async def get_warnings(self, guild_id, user_id):
        cur = self.conn.execute(
            "SELECT * FROM warnings WHERE guild_id=? AND user_id=? AND active=1 ORDER BY id",
            (guild_id, user_id))
        return [dict(r) for r in cur.fetchall()]

    async def add_action(self, guild_id, user_id, moderator_id, action, reason="", duration=None):
        self.conn.execute(
            "INSERT INTO actions (guild_id,user_id,moderator_id,action,reason,duration) VALUES (?,?,?,?,?,?)",
            (guild_id, user_id, moderator_id, action, reason, duration))
        self.conn.commit()

    async def set_config(self, guild_id, **values):
        current = await self.get_config(guild_id)
        current.update(values)
        self.conn.execute("""
        INSERT INTO config
        (guild_id,banned_words,spam_count,spam_window,spam_timeout,raid_join_count,raid_window,raid_lockdown,appeal_url)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(guild_id) DO UPDATE SET
        banned_words=excluded.banned_words, spam_count=excluded.spam_count,
        spam_window=excluded.spam_window, spam_timeout=excluded.spam_timeout,
        raid_join_count=excluded.raid_join_count, raid_window=excluded.raid_window,
        raid_lockdown=excluded.raid_lockdown, appeal_url=excluded.appeal_url
        """, (guild_id,current["banned_words"],current["spam_count"],current["spam_window"],
               current["spam_timeout"],current["raid_join_count"],current["raid_window"],
               current["raid_lockdown"],current["appeal_url"]))
        self.conn.commit()

    async def get_config(self, guild_id):
        cur = self.conn.execute("SELECT * FROM config WHERE guild_id=?", (guild_id,))
        row = cur.fetchone()
        if row:
            return dict(row)
        defaults = {
            "guild_id": guild_id, "banned_words": os.getenv("BANNED_WORDS", ""),
            "spam_count": 6, "spam_window": 8, "spam_timeout": 10,
            "raid_join_count": 8, "raid_window": 20, "raid_lockdown": 120,
            "appeal_url": os.getenv("APPEAL_URL", "")
        }
        self.conn.execute("""
        INSERT INTO config
        (guild_id,banned_words,spam_count,spam_window,spam_timeout,raid_join_count,raid_window,raid_lockdown,appeal_url)
        VALUES (?,?,?,?,?,?,?,?,?)
        """, tuple(defaults.values()))
        self.conn.commit()
        return defaults

    async def add_appeal(self, guild_id, user_id, reason):
        cur = self.conn.execute(
            "INSERT INTO appeals (guild_id,user_id,reason) VALUES (?,?,?)",
            (guild_id,user_id,reason))
        self.conn.commit()
        return cur.lastrowid
