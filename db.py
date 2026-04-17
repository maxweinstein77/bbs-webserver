from datetime import datetime

from sqlalchemy import create_engine, text

engine = create_engine("sqlite:///bbs.db")


def init_db():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                username   TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS posts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username   TEXT NOT NULL,
                message    TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (username) REFERENCES users(username)
            )
        """))
        conn.commit()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---- Users ----

def create_user(username: str) -> dict:
    ts = _now()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (username, created_at) VALUES (:u, :ts)"),
            {"u": username, "ts": ts},
        )
    return {"username": username, "created_at": ts}


def get_user(username: str) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT username, created_at FROM users WHERE username = :u"),
            {"u": username},
        ).mappings().first()
    return dict(row) if row else None


def list_users() -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT username, created_at FROM users ORDER BY created_at")
        ).mappings().all()
    return [dict(r) for r in rows]


# ---- Posts ----

def create_post(username: str, message: str) -> dict:
    ts = _now()
    with engine.begin() as conn:
        result = conn.execute(
            text("INSERT INTO posts (username, message, created_at) VALUES (:u, :m, :ts)"),
            {"u": username, "m": message, "ts": ts},
        )
        post_id = result.lastrowid
    return {"id": post_id, "username": username, "message": message, "created_at": ts}


def get_post(post_id: int) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, username, message, created_at FROM posts WHERE id = :id"),
            {"id": post_id},
        ).mappings().first()
    return dict(row) if row else None


def list_posts(q: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    sql = "SELECT id, username, message, created_at FROM posts"
    params: dict = {"limit": limit, "offset": offset}
    if q:
        sql += " WHERE message LIKE :q"
        params["q"] = f"%{q}%"
    sql += " ORDER BY id DESC LIMIT :limit OFFSET :offset"
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def get_posts_by_user(username: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, username, message, created_at FROM posts "
                "WHERE username = :u ORDER BY id DESC"
            ),
            {"u": username},
        ).mappings().all()
    return [dict(r) for r in rows]


def delete_post(post_id: int) -> bool:
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM posts WHERE id = :id"),
            {"id": post_id},
        )
    return result.rowcount > 0