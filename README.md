# BBS Webserver 

At a high level, this project builds off a standard Bulletin Board System (BBS). 
This project wraps the original BBS in a web-facing layer. Specifically, this is a REST API built with FastAPI sitting atop the original bbs. Functionalities include user 
generation, posting with a username, searching and paginating posts, patching 
a user's biography and post messages, and the ability to react to posts. 

---

## 1. Run instructions

Dependencies (from `requirements.txt`):
- `fastapi` - the web framework
- `uvicorn` - the ASGI server
- `httpx` - HTTP client used by `verify_api.py`
- `sqlalchemy` - used by `db.py` for the engine + `text()` query helper

### First-time setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Run the server

```bash
source venv/bin/activate
uvicorn main:app --port 8000
```

`main.py` calls`db.init_db()` upon starting which results in the automatic creation of `bbs.db`and its respective tables on the first request. No additional migration step is required.

### Run the verifier

In a second terminal:

```bash
source venv/bin/activate
python verify_api.py
```

Uvicorn is constantly anticipating requests so the need for a second terminal becomes mandatory. The first terminal is thus responsible for running the server but the second one will run the verifier. According to our earlier logic, it would make sense that hardcoding the same username more than once ought to result in a 409 duplication error. The verifier works around this by generating a random suffix to attach to the username at the start of every run thus avoiding this obstacle, meaning each run is isolated from the other. If you want a fresh start, you would need to delete `bbs.db`.

---

## 2. Tier that I targeted

**Gold** (I chose to implement the reactions feature).

---

## 3. Design decisions

**1. Hard delete.** I found hard delete to be the wiser choice here. Soft delete would just add unnecessary complexity to the model because it'd require reading every single query to filter out deleted rows. On the other hand, hard delete ensures a clean removal of an object in its entirety from the database, which also pairs nicely with the reactions feature I implemented in the gold version. 

**2. Noun-focused URL design.** URLs name nouns, not verbs. `DELETE /posts/5` rather than say `/deletePost/5`. The HTTP method carries the action. We covered this style of approach in lecture 3.1 and it also proves to be suitable for the reactions feature I implemented in the gold version: `POST /posts/{id}/reactions` reads naturally as "add a reaction to this post" without inventing a verb like `/addReaction`. Because if we were to do that, things would get messy really fast. Having that noun separation makes things a whole lot cleaner and simpler. The URL should name a thing but the HTTP method should be responsible for telling us what to do with that thing. 

**3. All Pydantic models live in `main.py`.** In lecture 3.2, there was a chat app demonstration which utilized a separate `schemas.py` file. Here though, our goal is to make sure we don't scatter models across files. Pydantic models are tightly related to the HTTP layer because they define the shape of the request and response bodies so it makes sense to have them housed in `main.py`, not in a separate file like the chat app. 

**4. `post_count` is computed at read time.** Every user response includes `post_count`, computed via `LEFT JOIN posts + COUNT(p.id)`. The alternative would be storing a counter column on the users table, but that means every post create/delete would need to remember to update the counter. Forget one branch and you'll get a wrong count permanently. Computing on read avoids those accuracy issues entirely, and at SQLite scale the extra JOIN is fast enough such that the tradeoff worth it.

**5. Composite primary key on the reactions table.** Rather than giving each reaction its own id number, the reactions table uses `PRIMARY KEY (post_id, username)`. This disables anyone from reacting more than once to the same post and if someone were to, it routes to a 409 error. It also means the composite key acts as the identifier, which justifies why `DELETE /posts/{id}/reactions/{username}` has no separate reaction id in its URL. That is, because the pair is the identifier, we don't need an extra reaction id here. 

**6. Ownership policy regarding `PATCH /posts/{id}`.** Only the post's original author can edit the post. If there's a mismatch, a 403 error is expected. Now sure, the X-Username can be faked but establishing the match pattern right now makes the jump to real auth later easier, because the handler barely changes. You can just go straight from the header string to verified id. 

**7. Added `sqlalchemy` to `requirements.txt`.** We need SQLAlchemy because `db.py` uses it for the engine and query functions. Without it, `uvicorn main:app` will not start. 

---

## 4. Schema changes from A1

### Users table

```sql
-- A1 (inherited)
CREATE TABLE IF NOT EXISTS users (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL
);

-- A2 (current)
CREATE TABLE IF NOT EXISTS users (
    username   TEXT PRIMARY KEY,      -- dropped synthetic id; username is the natural key
    created_at TEXT NOT NULL,         -- added; required by A2 response shape
    bio        TEXT                   -- added (Silver); nullable, max 200 chars enforced by Pydantic
);
```

### Posts table

```sql
-- A1 (inherited)
CREATE TABLE IF NOT EXISTS posts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    message    TEXT NOT NULL,
    timestamp  TEXT NOT NULL,
    parent_id  INTEGER DEFAULT NULL,     -- A1 threading, unused in A2
    FOREIGN KEY (user_id) REFERENCES users (id),
    FOREIGN KEY (parent_id) REFERENCES posts (id)
);

-- A2 (current)
CREATE TABLE IF NOT EXISTS posts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT NOT NULL,            -- renamed from user_id; stores username directly
    message    TEXT NOT NULL,
    created_at TEXT NOT NULL,            -- renamed from timestamp for spec consistency
    updated_at TEXT,                     -- added (Silver); nullable, populated on PATCH
    FOREIGN KEY (username) REFERENCES users(username)
);
```

### New table (Gold)

```sql
CREATE TABLE IF NOT EXISTS reactions (
    post_id   INTEGER NOT NULL,
    username  TEXT NOT NULL,
    kind      TEXT NOT NULL,
    PRIMARY KEY (post_id, username)       -- composite key: one reaction per user per post
);
```

### Behavior alterations

In the original version of this bbs (the non-webserver one), if someone tried to post as a user that didn't already exist, we would just automatically create that user. But here, it's the opposite. If you try to post as a user that does not exist, you'll get a 404 error. Why? Because we're not dealing with just a one-person CLI interaction anymore. With the web server, we need stricter control over who exists in the database or you run the risk of anyone just messing with your system with fake users left and right. 

### Migration-safe `init_db()`

To avoid forcing a database wipe when advancing from Bronze to Silver, `init_db()` now also runs an `_add_column_if_missing()` helper (via `PRAGMA table_info`) for the two nullable columns (`users.bio`, `posts.updated_at`). This enables upgrades to happen to the table without having to start our `bbs.db` from scratch each time. 

---

## 5. How I supplemented `verify_api.py`

### Three TODO stubs (part of Bronze)

**`run_delete_checks`** 3 checks:
- DELETE on an existing post returns 204
- GET on that same id afterward returns 404 (verifies the delete actually happened)
- DELETE on a post id that doesn't exist (`99999999`) returns 404

I chose `99999999` over `0` or `-1` because negative or zero ids might fail Pydantic validation on the path parameter. This could in turn result in a 422 instead of hitting the database. It's virtually guaranteed that `99999999` does not already exist so we can actually use it to test the 404 branch because the request makes it through the validation process. 

**`run_pagination_checks`** 5 checks:
- `?limit=2` returns at most 2 items
- `?offset=1` skips the first item (verified by comparing `full_list[1].id` to `offset_list[0].id`)
- `?limit=0`: 422
- `?limit=500`: 422
- `?offset=-1`: 422

**`run_field_shape_checks`** 6 checks:
User objects (from POST /users, GET /users/{username}, items in GET /users) have exactly the expected keys. Same for post objects. Uses **set equality** (`set(body.keys()) == expected`) so extras like `email` or `user_id` are flagged as failures, and missing fields are identified too.

### Additional test sections for Silver and Gold

**`run_silver_checks`** - 15 checks spanning bio/post_count presence, post_count correctness (create 2 posts, verify count = 2), PATCH /users success/404/422, PATCH /posts success with `updated_at` populated, PATCH /posts 403 on non-author, PATCH /posts 400 without X-Username, PATCH /posts 404 on missing post, GET /posts?username= filtering, and composability of `?username=` with `?q=`.

**`run_gold_checks`** - 12 checks spanning reaction create (201), exact response shape, duplicate - 409, reaction on non-existent post - 404, reaction from non-existent user - 404, validation 422s (missing kind, missing username, oversized kind), reaction delete (204), delete-already-gone - 404, delete on non-existent post - 404, and cascade-delete (creating a post with a reaction, deleting the post, verifying the reaction is also deleted).

### Edge cases requiring consideration

- **Cascade delete** - it's important to make sure that the reactions with a deleted post are deleted as well because otherwise you just end up with orphaned rows. I implemented a check specifically for this. 
- **`?username=` + `?q=` composability** - the spec says filters should compose, so I added a query that tests in combination rather than testing each filter separately. 
- **`post_count` correctness under alteration** - verified it reflects posts that actually exist, not just that the field is present. 

### Existing shape checks updated for Silver

The Bronze verifier hard-coded the old user shape `{username, created_at}` and post shape `{id, username, message, created_at}`. With Silver both shapes are adjusted (adds `bio` + `post_count` to users, `updated_at` to posts), so it follows that the old assertions are going to fail. Rather than delete the whole thing, it makes more sense to update the expected keys to match the new form. 

---

## 6. X ≠ authentication: security gap reflection


The `X-Username` header does not act as real authentication. Anyone who is making a request can fill the header with whatever username they'd like and the server will just accept it. If you want actual authentication, you need systems in place to verify the person's identity. 
For this to become real authentication, the server would need to verify that the request is coming from someone who can prove they are the claimed user. Should one want to take this project further, there's a few ways to integrate real authentication:

1. Users register with both a username and a password and store the password as a hash. 
2. A `POST /sessions` or `POST /login` endpoint grabs the username and password, verifies the hash, and issues a token (like a JWT for instance).
3. Future requests include the token in an `Authorization: Bearer <token>` header as opposed to an X-Username.
4. The server verifies the token on every request and obtains the identity. 
5. Ownership checks use the verified identity. 

We'd also need a transport-layer security (HTTPS) so credentials and tokens aren't readable by anyone trying to hack the system. 

---

## 7. Silver and Gold Additions

### Silver 

- **Schema:** added `bio TEXT` to `users`, added `updated_at TEXT` to `posts` (both can be empty or null to prevent existing rows from breaking).
- **`bio` and `post_count` on every user response** - implemented by changing every user-returning SQL query to use a `LEFT JOIN posts + COUNT(p.id) GROUP BY u.username`. `post_count` is recomputed on every read. These changes allow us to see the bio and how many posts the user has made. 
- **`PATCH /users/{username}`** - updates bio. Returns 200 on success, 404 if user doesn't exist, 422 if bio exceeds 200 chars (enforced by Pydantic). Returns the full updated user object including the recomputed post_count.
- **`PATCH /posts/{id}`** - edits the message. Returns 200 with the post including a populated `updated_at` timestamp. Ownership policy (only the original author can edit): **requires X-Username header; only the original author can edit; 403 otherwise** (see design decision #6 for reasoning). 400 if header missing, 404 if post doesn't exist.
- **`GET /posts?username=alice`** - filters posts by author. Fully composable with `?q=`, `?limit=`, and `?offset=` - the query builder in `db.list_posts` AND-combines whichever filters are provided.

### Gold: Reactions

- **New `reactions` table** with composite primary key `(post_id, username)` (more on this in design decision #5 but essentially it's a new endpoint that allows people to react to a post).
- **`POST /posts/{post_id}/reactions`** - body `{"username": "...", "kind": "..."}`. Kind can be any non-empty string up to 10 characters (not hardcoded to `"+1"` so the UI can evolve toward emoji or custom reactions without a schema change). Returns 201 with `{post_id, username, kind}`. 404 if the post doesn't exist, 404 if the reacting user doesn't exist, 409 if this user already reacted to this post, 422 on validation failures.
- **`DELETE /posts/{post_id}/reactions/{username}`** - 204 on success, 404 if no such reaction exists.
- **Cascade delete** - `delete_post()` removes the post and its respective reactions so there's no orphaned reaction data hanging around

As should be obvious, reactions always exist in relation to the post and the user hence the development of a reaction table which enables those associations to occur.