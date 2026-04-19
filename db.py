from datetime import datetime

from sqlalchemy import create_engine, text

# The one database connection used by every query in this file.
engine = create_engine("sqlite:///bbs.db")

def init_db():
    # Create all three tables if they don't exist, then migrate old DBs without dropping data.
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                username   TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                bio        TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS posts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username   TEXT NOT NULL,
                message    TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                FOREIGN KEY (username) REFERENCES users(username)
            )
        """))
        # Gold: reactions association table. Composite primary key
        # (post_id, username) means a user can only react once per post.
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS reactions (
                post_id   INTEGER NOT NULL,
                username  TEXT NOT NULL,
                kind      TEXT NOT NULL,
                PRIMARY KEY (post_id, username)
            )
        """))
        # Migration for databases created before Silver: add missing columns.
        _add_column_if_missing(conn, "users", "bio", "TEXT")
        _add_column_if_missing(conn, "posts", "updated_at", "TEXT")
        conn.commit()

def _add_column_if_missing(conn, table: str, column: str, coltype: str) -> None:
    # Add a column to an existing table only if it's not already there.
    rows = conn.execute(text(f"PRAGMA table_info({table})")).all()
    existing = {row[1] for row in rows}
    if column not in existing:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))

def _now() -> str:
    # Return the current time as an ISO formatted string, down to the second.
    return datetime.now().isoformat(timespec="seconds")

# Users

# Every user response includes bio and post_count. post_count is computed
# at read time via LEFT JOIN + COUNT so we never store a stale counter.
_USER_SELECT = """
    SELECT u.username,
           u.created_at,
           u.bio,
           COUNT(p.id) AS post_count
    FROM users u
    LEFT JOIN posts p ON p.username = u.username
"""

def create_user(username: str) -> dict:
    # Insert a new user row, then return the full user object.
    ts = _now()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (username, created_at) VALUES (:u, :ts)"),
            {"u": username, "ts": ts},
        )
    return get_user(username)

def get_user(username: str) -> dict | None:
    # Fetch one user by username (with bio + computed post_count), or None.
    sql = _USER_SELECT + " WHERE u.username = :u GROUP BY u.username"
    with engine.connect() as conn:
        row = conn.execute(text(sql), {"u": username}).mappings().first()
    return dict(row) if row else None

def list_users() -> list[dict]:
    # Fetch every user with bio + computed post_count, ordered by signup time.
    sql = _USER_SELECT + " GROUP BY u.username ORDER BY u.created_at"
    with engine.connect() as conn:
        rows = conn.execute(text(sql)).mappings().all()
    return [dict(r) for r in rows]

def update_user_bio(username: str, bio: str | None) -> dict:
    # Update a user's bio and return the fresh user object.
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET bio = :b WHERE username = :u"),
            {"u": username, "b": bio},
        )
    return get_user(username)

# Posts

_POST_SELECT = "SELECT id, username, message, created_at, updated_at FROM posts"

def create_post(username: str, message: str) -> dict:
    # Insert a new post and return the created post object.
    ts = _now()
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO posts (username, message, created_at, updated_at) "
                "VALUES (:u, :m, :ts, NULL)"
            ),
            {"u": username, "m": message, "ts": ts},
        )
        post_id = result.lastrowid
    return {
        "id": post_id,
        "username": username,
        "message": message,
        "created_at": ts,
        "updated_at": None,
    }

def get_post(post_id: int) -> dict | None:
    # Fetch one post by id, or None if it doesn't exist.
    with engine.connect() as conn:
        row = conn.execute(
            text(_POST_SELECT + " WHERE id = :id"),
            {"id": post_id},
        ).mappings().first()
    return dict(row) if row else None

def list_posts(
    q: str | None = None,
    username: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    # Fetch posts with optional q/username filters and pagination; newest first.
    sql = _POST_SELECT
    where: list[str] = []
    params: dict = {"limit": limit, "offset": offset}
    if q:
        where.append("message LIKE :q")
        params["q"] = f"%{q}%"
    if username:
        where.append("username = :username")
        params["username"] = username
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT :limit OFFSET :offset"
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]

def get_posts_by_user(username: str) -> list[dict]:
    # Fetch every post written by a specific user, newest first.
    with engine.connect() as conn:
        rows = conn.execute(
            text(_POST_SELECT + " WHERE username = :u ORDER BY id DESC"),
            {"u": username},
        ).mappings().all()
    return [dict(r) for r in rows]

def update_post_message(post_id: int, message: str) -> dict:
    # Update a post's message, stamp updated_at, and return the fresh post.
    ts = _now()
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE posts SET message = :m, updated_at = :ts WHERE id = :id"),
            {"id": post_id, "m": message, "ts": ts},
        )
    return get_post(post_id)

def delete_post(post_id: int) -> bool:
    # Permanently deletes a post AND its reactions in one transaction. True if deleted.
    with engine.begin() as conn:
        # Cascade: remove reactions in the same transaction so we don't
        # leave orphaned rows pointing at a post_id that no longer exists.
        conn.execute(
            text("DELETE FROM reactions WHERE post_id = :id"),
            {"id": post_id},
        )
        result = conn.execute(
            text("DELETE FROM posts WHERE id = :id"),
            {"id": post_id},
        )
    return result.rowcount > 0

# Reactions

def create_reaction(post_id: int, username: str, kind: str) -> dict:
    # Insert a new reaction row and return it.
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO reactions (post_id, username, kind) VALUES (:p, :u, :k)"),
            {"p": post_id, "u": username, "k": kind},
        )
    return {"post_id": post_id, "username": username, "kind": kind}

def get_reaction(post_id: int, username: str) -> dict | None:
    # Fetch one specific reaction (by post_id + username), or None.
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT post_id, username, kind FROM reactions "
                "WHERE post_id = :p AND username = :u"
            ),
            {"p": post_id, "u": username},
        ).mappings().first()
    return dict(row) if row else None

def delete_reaction(post_id: int, username: str) -> bool:
    # Permanently deletes a single reaction. True if it existed and was removed.
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM reactions WHERE post_id = :p AND username = :u"),
            {"p": post_id, "u": username},
        )
    return result.rowcount > 0