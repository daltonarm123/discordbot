from __future__ import annotations

import os
from pathlib import Path

import aiosqlite


class Database:
    def __init__(self, path: str) -> None:
        self.path = path

    async def initialize(self) -> None:
        Path(os.path.dirname(self.path) or ".").mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS guild_config (
                    guild_id INTEGER PRIMARY KEY,
                    welcome_channel_id INTEGER,
                    log_channel_id INTEGER,
                    suggestion_channel_id INTEGER,
                    application_channel_id INTEGER,
                    verified_role_id INTEGER
                );

                CREATE TABLE IF NOT EXISTS invite_joins (
                    guild_id INTEGER NOT NULL,
                    member_id INTEGER NOT NULL,
                    inviter_id INTEGER,
                    invite_code TEXT,
                    joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    left_at TEXT,
                    PRIMARY KEY (guild_id, member_id)
                );

                CREATE TABLE IF NOT EXISTS submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'under_review',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            await db.commit()

    async def set_config(self, guild_id: int, **values: int | None) -> None:
        allowed = {
            "welcome_channel_id",
            "log_channel_id",
            "suggestion_channel_id",
            "application_channel_id",
            "verified_role_id",
        }
        values = {key: value for key, value in values.items() if key in allowed}
        if not values:
            return
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        updates = ", ".join(f"{column}=excluded.{column}" for column in values)
        query = (
            f"INSERT INTO guild_config (guild_id, {columns}) VALUES (?, {placeholders}) "
            f"ON CONFLICT(guild_id) DO UPDATE SET {updates}"
        )
        async with aiosqlite.connect(self.path) as db:
            await db.execute(query, [guild_id, *values.values()])
            await db.commit()

    async def get_config(self, guild_id: int) -> dict[str, int | None]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,))
            row = await cursor.fetchone()
            return dict(row) if row else {}

    async def record_join(self, guild_id: int, member_id: int, inviter_id: int | None, invite_code: str | None) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO invite_joins (guild_id, member_id, inviter_id, invite_code, left_at)
                VALUES (?, ?, ?, ?, NULL)
                ON CONFLICT(guild_id, member_id) DO UPDATE SET
                    inviter_id=excluded.inviter_id,
                    invite_code=excluded.invite_code,
                    joined_at=CURRENT_TIMESTAMP,
                    left_at=NULL
                """,
                (guild_id, member_id, inviter_id, invite_code),
            )
            await db.commit()

    async def record_leave(self, guild_id: int, member_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE invite_joins SET left_at=CURRENT_TIMESTAMP WHERE guild_id=? AND member_id=?",
                (guild_id, member_id),
            )
            await db.commit()

    async def invite_leaderboard(self, guild_id: int, limit: int = 10) -> list[tuple[int, int]]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """
                SELECT inviter_id, COUNT(*) AS total
                FROM invite_joins
                WHERE guild_id=? AND inviter_id IS NOT NULL AND left_at IS NULL
                GROUP BY inviter_id
                ORDER BY total DESC
                LIMIT ?
                """,
                (guild_id, limit),
            )
            return [(int(row[0]), int(row[1])) for row in await cursor.fetchall()]

    async def create_submission(self, guild_id: int, user_id: int, kind: str, title: str, body: str) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "INSERT INTO submissions (guild_id, user_id, kind, title, body) VALUES (?, ?, ?, ?, ?)",
                (guild_id, user_id, kind, title, body),
            )
            await db.commit()
            return int(cursor.lastrowid)
