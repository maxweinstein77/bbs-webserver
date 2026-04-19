"""
verify_api.py runs a bunch of HTTP checks against my BBS webserver and
prints PASS or FAIL for each one. It's how I know the API actually
behaves the way the spec says.

HOW TO USE:
  1. Start your server:   uvicorn main:app --port 8000
  2. In another shell:    python verify_api.py
  3. Read the output. Fix any FAIL lines. Repeat.

This script uses random usernames on every run, so it does NOT require
a clean database. You can run it over and over against the same server.
If you want to start fresh, stop your server, delete bbs.db, and
restart.
"""

import os
import sys
import uuid

import httpx

BASE = os.environ.get("BBS_BASE", "http://localhost:8000")

# Random suffix keeps test data from colliding across runs.
RUN = uuid.uuid4().hex[:8]
ALICE = f"alice_{RUN}"
BOB = f"bob_{RUN}"
GHOST = f"ghost_{RUN}"  # never created

FAILED = 0
PASSED = 0

def check(name: str, cond: bool, detail: str = "") -> None:
    # Helper that prints PASS or FAIL and updates the running totals.
    global FAILED, PASSED
    if cond:
        PASSED += 1
        print(f"PASS  {name}")
    else:
        FAILED += 1
        msg = f"FAIL  {name}"
        if detail:
            msg += f"  ({detail})"
        print(msg)

def main() -> int:
    # Entry point. Confirms the server is reachable, then runs every check section.
    try:
        c = httpx.Client(base_url=BASE, timeout=5.0)
        c.get("/users")
    except httpx.ConnectError:
        print(f"ERROR: could not connect to {BASE}")
        print("Is your server running? Try: uvicorn main:app --port 8000")
        return 2

    print(f"Run id: {RUN} (usernames are suffixed with this)")
    print()

    state = {}
    run_user_checks(c, state)
    run_post_checks(c, state)
    run_search_checks(c, state)

    # ==================================================================
    # STUDENT TODO #1: DELETE /posts/{id}
    #
    # Implement run_delete_checks() below. It should verify:
    #   - DELETE on an existing post returns 204
    #   - After DELETE, GET on the same id returns 404
    #   - DELETE on a post id that doesn't exist returns 404
    #
    # state["alice_post_id"] holds a post id you created earlier.
    # Use it (or create a new one to delete). Also, pick a post id
    # that is very unlikely to exist when testing the 404 case.
    #
    # When you've implemented it, uncomment the call below.
    # ==================================================================
    run_delete_checks(c, state)

    # ==================================================================
    # STUDENT TODO #2: pagination on GET /posts
    #
    # Implement run_pagination_checks() below. It should verify:
    #   - GET /posts?limit=N returns at most N items
    #   - GET /posts?offset=K skips the first K items
    #   - GET /posts?limit=0 returns 422
    #   - GET /posts?limit=500 returns 422
    #   - GET /posts?offset=-1 returns 422
    #
    # When you've implemented it, uncomment the call below.
    # ==================================================================
    run_pagination_checks(c, state)

    # ==================================================================
    # STUDENT TODO #3: exact response field shapes
    #
    # Implement run_field_shape_checks() below. It should verify that
    # your response bodies contain EXACTLY the fields the spec lists.
    # No extras, nothing missing.
    #
    # A user object (from POST /users, GET /users/{username}, and items
    # in GET /users) has exactly {username, created_at, bio, post_count}.
    #
    # A post object (from POST /posts, GET /posts/{id}, and items in
    # GET /posts) has exactly {id, username, message, created_at, updated_at}.
    #
    # An extra field like `email`, `updated_at`, or `user_id` is a FAIL.
    # A missing field is a FAIL. You will need to compare
    # set(body.keys()) against the expected set for each shape.
    #
    # Create fresh users and posts inside this function if you want
    # isolation, or reuse state["alice_post_id"] and friends.
    #
    # When you've implemented it, uncomment the call below.
    # ==================================================================
    run_field_shape_checks(c, state)

    # Silver tier checks: bio, post_count, PATCH endpoints, ?username= filter.
    run_silver_checks(c, state)

    # Gold tier checks: reactions feature.
    run_gold_checks(c, state)

    print()
    print(f"{PASSED} passed, {FAILED} failed")
    return 0 if FAILED == 0 else 1

def run_user_checks(c: httpx.Client, state: dict) -> None:
    # Runs every Bronze check tied to the user endpoints.
    r = c.post("/users", json={"username": ALICE})
    check("POST /users creates a user (201)", r.status_code == 201, detail=f"got {r.status_code}")
    if r.status_code == 201:
        body = r.json()
        check(
            "POST /users response has exactly username, created_at, bio, post_count",
            set(body.keys()) == {"username", "created_at", "bio", "post_count"} and body["username"] == ALICE,
            detail=str(body),
        )

    r = c.post("/users", json={"username": ALICE})
    check("POST /users duplicate returns 409", r.status_code == 409, detail=f"got {r.status_code}")

    r = c.post("/users", json={"username": "ab"})
    check("POST /users too-short username returns 422", r.status_code == 422, detail=f"got {r.status_code}")

    r = c.post("/users", json={"username": "has spaces"})
    check("POST /users invalid chars returns 422", r.status_code == 422, detail=f"got {r.status_code}")

    r = c.post("/users", json={})
    check("POST /users missing username returns 422", r.status_code == 422, detail=f"got {r.status_code}")

    c.post("/users", json={"username": BOB})

    r = c.get("/users")
    check("GET /users returns 200", r.status_code == 200, detail=f"got {r.status_code}")
    if r.status_code == 200:
        usernames = [u["username"] for u in r.json()]
        check(
            "GET /users includes both created users",
            ALICE in usernames and BOB in usernames,
            detail=f"looking for {ALICE} and {BOB}",
        )

    r = c.get(f"/users/{ALICE}")
    check(f"GET /users/{ALICE} returns 200", r.status_code == 200, detail=f"got {r.status_code}")
    if r.status_code == 200:
        body = r.json()
        check(
            f"GET /users/{ALICE} body.username == {ALICE}",
            body.get("username") == ALICE,
            detail=str(body),
        )

    r = c.get(f"/users/{GHOST}")
    check(f"GET /users/{GHOST} returns 404", r.status_code == 404, detail=f"got {r.status_code}")

def run_post_checks(c: httpx.Client, state: dict) -> None:
    # Runs every Bronze check tied to the post endpoints.
    r = c.post("/posts", json={"message": "hello world"}, headers={"X-Username": ALICE})
    check("POST /posts with X-Username returns 201", r.status_code == 201, detail=f"got {r.status_code}")
    if r.status_code == 201:
        body = r.json()
        expected_keys = {"id", "username", "message", "created_at", "updated_at"}
        check(
            "POST /posts response has exactly id, username, message, created_at, updated_at",
            set(body.keys()) == expected_keys,
            detail=str(body),
        )
        check("POST /posts response username matches header", body.get("username") == ALICE)
        check("POST /posts response message matches body", body.get("message") == "hello world")
        state["alice_post_id"] = body.get("id")

    r = c.post("/posts", json={"message": "hi"})
    check("POST /posts without X-Username returns 400", r.status_code == 400, detail=f"got {r.status_code}")

    r = c.post("/posts", json={"message": "hi"}, headers={"X-Username": GHOST})
    check("POST /posts with unknown user returns 404", r.status_code == 404, detail=f"got {r.status_code}")

    r = c.post("/posts", json={"message": ""}, headers={"X-Username": ALICE})
    check("POST /posts with empty message returns 422", r.status_code == 422, detail=f"got {r.status_code}")

    r = c.post(
        "/posts",
        json={"message": "x" * 501},
        headers={"X-Username": ALICE},
    )
    check("POST /posts with 501-char message returns 422", r.status_code == 422, detail=f"got {r.status_code}")

    r = c.post("/posts", json={}, headers={"X-Username": ALICE})
    check("POST /posts missing message returns 422", r.status_code == 422, detail=f"got {r.status_code}")

    r = c.post("/posts", json={"message": "second post"}, headers={"X-Username": BOB})
    if r.status_code == 201:
        state["bob_post_id"] = r.json().get("id")

    r = c.get("/posts")
    check("GET /posts returns 200", r.status_code == 200, detail=f"got {r.status_code}")
    if r.status_code == 200:
        posts = r.json()
        check(
            "GET /posts returns a JSON array",
            isinstance(posts, list),
            detail=f"got {type(posts).__name__}",
        )

    if "alice_post_id" in state:
        pid = state["alice_post_id"]
        r = c.get(f"/posts/{pid}")
        check(f"GET /posts/{pid} (alice's post) returns 200", r.status_code == 200, detail=f"got {r.status_code}")

    r = c.get("/posts/99999999")
    check("GET /posts/99999999 returns 404", r.status_code == 404, detail=f"got {r.status_code}")

    r = c.get(f"/users/{ALICE}/posts")
    check(f"GET /users/{ALICE}/posts returns 200", r.status_code == 200, detail=f"got {r.status_code}")
    if r.status_code == 200:
        alice_posts = r.json()
        check(
            f"GET /users/{ALICE}/posts contains only {ALICE}'s posts",
            all(p.get("username") == ALICE for p in alice_posts) and len(alice_posts) >= 1,
            detail=str(alice_posts),
        )

    r = c.get(f"/users/{GHOST}/posts")
    check(f"GET /users/{GHOST}/posts returns 404", r.status_code == 404, detail=f"got {r.status_code}")

def run_search_checks(c: httpx.Client, state: dict) -> None:
    # Verifies the ?q= search filter returns only posts containing the keyword.
    needle = f"needle_{RUN}"
    c.post("/posts", json={"message": f"a post with {needle} in it"}, headers={"X-Username": ALICE})
    c.post("/posts", json={"message": "nothing to see"}, headers={"X-Username": ALICE})

    r = c.get("/posts", params={"q": needle})
    check(f"GET /posts?q={needle} returns 200", r.status_code == 200, detail=f"got {r.status_code}")
    if r.status_code == 200:
        matches = r.json()
        check(
            f"GET /posts?q={needle} returns only matching posts",
            all(needle in p.get("message", "") for p in matches) and len(matches) >= 1,
            detail=str(matches),
        )

def run_delete_checks(c: httpx.Client, state: dict) -> None:
    # TODO #1: verifies DELETE /posts/{id} behavior.
    # Creates a fresh post to delete so we don't disturb other checks,
    # then checks a successful delete, a follow up GET, and a bogus id.
    response = c.post("/posts", json={"message": "testing"}, headers={"X-Username": ALICE})
    post_id_to_delete = response.json()["id"]

    response = c.delete(f"/posts/{post_id_to_delete}")
    check("DELETE existing post returns 204", response.status_code == 204, detail=f"got {response.status_code}")

    response = c.get(f"/posts/{post_id_to_delete}")
    check("GET on deleted post returns 404", response.status_code == 404, detail=f"got {response.status_code}")

    response = c.delete("/posts/99999999")
    check("DELETE on non-existent post returns 404", response.status_code == 404, detail=f"got {response.status_code}")

def run_pagination_checks(c: httpx.Client, state: dict) -> None:
    # TODO #2: verifies limit and offset behave and reject bad values.
    # Creates 3 posts first so there's enough data to actually test paging.
    for _ in range(3):
        c.post("/posts", json={"message": "pagination test"}, headers={"X-Username": ALICE})

    response = c.get("/posts", params={"limit": 2})
    check(
        "GET /posts?limit=2 returns at most 2 items",
        len(response.json()) <= 2,
        detail=f"got {len(response.json())} items",
    )

    full_list = c.get("/posts", params={"limit": 10, "offset": 0}).json()
    offset_list = c.get("/posts", params={"limit": 10, "offset": 1}).json()
    check(
        "GET /posts?offset=1 skips the first item",
        len(full_list) >= 2 and len(offset_list) >= 1 and full_list[1]["id"] == offset_list[0]["id"],
        detail=f"full[1]={full_list[1] if len(full_list) >= 2 else None}, offset[0]={offset_list[0] if offset_list else None}",
    )

    response = c.get("/posts", params={"limit": 0})
    check(
        "GET /posts?limit=0 returns 422",
        response.status_code == 422,
        detail=f"got {response.status_code}",
    )

    response = c.get("/posts", params={"limit": 500})
    check(
        "GET /posts?limit=500 returns 422",
        response.status_code == 422,
        detail=f"got {response.status_code}",
    )

    response = c.get("/posts", params={"offset": -1})
    check(
        "GET /posts?offset=-1 returns 422",
        response.status_code == 422,
        detail=f"got {response.status_code}",
    )

def run_field_shape_checks(c: httpx.Client, state: dict) -> None:
    # TODO #3: verifies every response body has EXACTLY the spec fields.
    # Uses set equality so extra or missing keys both fail.
    expected_user_fields = {"username", "created_at", "bio", "post_count"}
    expected_post_fields = {"id", "username", "message", "created_at", "updated_at"}

    shape_user = f"shape_{RUN}"
    response = c.post("/users", json={"username": shape_user})
    check(
        "POST /users response has exactly {username, created_at, bio, post_count}",
        set(response.json().keys()) == expected_user_fields,
        detail=str(response.json()),
    )

    response = c.get(f"/users/{shape_user}")
    check(
        "GET /users/{username} response has exactly {username, created_at, bio, post_count}",
        set(response.json().keys()) == expected_user_fields,
        detail=str(response.json()),
    )

    response = c.get("/users")
    users_list = response.json()
    matching = [u for u in users_list if u.get("username") == shape_user]
    check(
        "GET /users items have exactly {username, created_at, bio, post_count}",
        len(matching) == 1 and set(matching[0].keys()) == expected_user_fields,
        detail=str(matching),
    )

    response = c.post(
        "/posts",
        json={"message": "shape check"},
        headers={"X-Username": shape_user},
    )
    shape_post_id = response.json()["id"]
    check(
        "POST /posts response has exactly {id, username, message, created_at, updated_at}",
        set(response.json().keys()) == expected_post_fields,
        detail=str(response.json()),
    )

    response = c.get(f"/posts/{shape_post_id}")
    check(
        "GET /posts/{id} response has exactly {id, username, message, created_at, updated_at}",
        set(response.json().keys()) == expected_post_fields,
        detail=str(response.json()),
    )

    response = c.get("/posts", params={"limit": 200})
    posts_list = response.json()
    matching = [p for p in posts_list if p.get("id") == shape_post_id]
    check(
        "GET /posts items have exactly {id, username, message, created_at, updated_at}",
        len(matching) == 1 and set(matching[0].keys()) == expected_post_fields,
        detail=str(matching),
    )

def run_silver_checks(c: httpx.Client, state: dict) -> None:
    # Covers every Silver feature: bio, post_count, PATCH endpoints, username filter.
    # Uses a fresh user so we own the posts we PATCH.
    silver_user = f"silver_{RUN}"
    other_user = f"other_{RUN}"
    c.post("/users", json={"username": silver_user})
    c.post("/users", json={"username": other_user})

    # bio and post_count fields on user responses
    response = c.get(f"/users/{silver_user}")
    body = response.json()
    check(
        "GET /users/{username} includes bio (nullable) and post_count",
        "bio" in body and "post_count" in body and body["post_count"] == 0,
        detail=str(body),
    )

    # Create 2 posts and verify post_count updates accordingly.
    c.post("/posts", json={"message": "p1"}, headers={"X-Username": silver_user})
    c.post("/posts", json={"message": "p2"}, headers={"X-Username": silver_user})
    response = c.get(f"/users/{silver_user}")
    check(
        "GET /users/{username} post_count reflects actual posts",
        response.json().get("post_count") == 2,
        detail=str(response.json()),
    )

    # PATCH /users/{username}
    response = c.patch(f"/users/{silver_user}", json={"bio": "hello from silver"})
    check(
        "PATCH /users/{username} returns 200",
        response.status_code == 200,
        detail=f"got {response.status_code}",
    )
    check(
        "PATCH /users/{username} updates bio",
        response.json().get("bio") == "hello from silver",
        detail=str(response.json()),
    )

    response = c.patch(f"/users/{GHOST}", json={"bio": "nope"})
    check(
        "PATCH /users on missing user returns 404",
        response.status_code == 404,
        detail=f"got {response.status_code}",
    )

    response = c.patch(f"/users/{silver_user}", json={"bio": "x" * 201})
    check(
        "PATCH /users with 201-char bio returns 422",
        response.status_code == 422,
        detail=f"got {response.status_code}",
    )

    # PATCH /posts/{id}
    response = c.post(
        "/posts",
        json={"message": "original message"},
        headers={"X-Username": silver_user},
    )
    silver_post_id = response.json()["id"]

    response = c.patch(
        f"/posts/{silver_post_id}",
        json={"message": "edited message"},
        headers={"X-Username": silver_user},
    )
    check(
        "PATCH /posts by original author returns 200",
        response.status_code == 200,
        detail=f"got {response.status_code}",
    )
    body = response.json()
    check(
        "PATCH /posts response has updated_at populated",
        body.get("updated_at") is not None,
        detail=str(body),
    )
    check(
        "PATCH /posts response message is updated",
        body.get("message") == "edited message",
        detail=str(body),
    )

    # Ownership rule: only the original author can edit.
    response = c.patch(
        f"/posts/{silver_post_id}",
        json={"message": "hijacked"},
        headers={"X-Username": other_user},
    )
    check(
        "PATCH /posts by non-author returns 403",
        response.status_code == 403,
        detail=f"got {response.status_code}",
    )

    response = c.patch(
        f"/posts/{silver_post_id}",
        json={"message": "no header"},
    )
    check(
        "PATCH /posts without X-Username returns 400",
        response.status_code == 400,
        detail=f"got {response.status_code}",
    )

    response = c.patch(
        "/posts/99999999",
        json={"message": "doesn't matter"},
        headers={"X-Username": silver_user},
    )
    check(
        "PATCH /posts on missing post returns 404",
        response.status_code == 404,
        detail=f"got {response.status_code}",
    )

    # GET /posts?username= filter
    response = c.get("/posts", params={"username": silver_user})
    check(
        "GET /posts?username={silver_user} returns 200",
        response.status_code == 200,
        detail=f"got {response.status_code}",
    )
    posts = response.json()
    check(
        "GET /posts?username=X returns only X's posts",
        all(p.get("username") == silver_user for p in posts) and len(posts) >= 1,
        detail=str(posts),
    )

    # Composable with ?q=
    needle = f"silvermark_{RUN}"
    c.post(
        "/posts",
        json={"message": f"marker {needle} post"},
        headers={"X-Username": silver_user},
    )
    c.post(
        "/posts",
        json={"message": f"marker {needle} post"},
        headers={"X-Username": other_user},
    )
    response = c.get("/posts", params={"username": silver_user, "q": needle})
    matches = response.json()
    check(
        "GET /posts?username=X&q=needle is composable",
        all(p.get("username") == silver_user and needle in p.get("message", "") for p in matches) and len(matches) >= 1,
        detail=str(matches),
    )

def run_gold_checks(c: httpx.Client, state: dict) -> None:
    # Covers every Gold feature: reaction create, delete, duplicates, and cascade.
    gold_user = f"gold_{RUN}"
    fan_user = f"fan_{RUN}"
    c.post("/users", json={"username": gold_user})
    c.post("/users", json={"username": fan_user})

    response = c.post(
        "/posts",
        json={"message": "react to me"},
        headers={"X-Username": gold_user},
    )
    gold_post_id = response.json()["id"]

    # POST /posts/{id}/reactions happy path
    response = c.post(
        f"/posts/{gold_post_id}/reactions",
        json={"username": fan_user, "kind": "+1"},
    )
    check(
        "POST reaction returns 201",
        response.status_code == 201,
        detail=f"got {response.status_code}",
    )
    check(
        "POST reaction response has exactly {post_id, username, kind}",
        set(response.json().keys()) == {"post_id", "username", "kind"},
        detail=str(response.json()),
    )

    # Duplicate reaction
    response = c.post(
        f"/posts/{gold_post_id}/reactions",
        json={"username": fan_user, "kind": "+1"},
    )
    check(
        "POST duplicate reaction (same user, same post) returns 409",
        response.status_code == 409,
        detail=f"got {response.status_code}",
    )

    # Reaction on non existent post
    response = c.post(
        "/posts/99999999/reactions",
        json={"username": fan_user, "kind": "+1"},
    )
    check(
        "POST reaction on non-existent post returns 404",
        response.status_code == 404,
        detail=f"got {response.status_code}",
    )

    # Reaction from non existent user
    response = c.post(
        f"/posts/{gold_post_id}/reactions",
        json={"username": GHOST, "kind": "+1"},
    )
    check(
        "POST reaction from non-existent user returns 404",
        response.status_code == 404,
        detail=f"got {response.status_code}",
    )

    # Validation failures
    response = c.post(
        f"/posts/{gold_post_id}/reactions",
        json={"username": fan_user},  # missing kind
    )
    check(
        "POST reaction missing kind returns 422",
        response.status_code == 422,
        detail=f"got {response.status_code}",
    )

    response = c.post(
        f"/posts/{gold_post_id}/reactions",
        json={"kind": "+1"},  # missing username
    )
    check(
        "POST reaction missing username returns 422",
        response.status_code == 422,
        detail=f"got {response.status_code}",
    )

    response = c.post(
        f"/posts/{gold_post_id}/reactions",
        json={"username": fan_user, "kind": "x" * 11},  # too long
    )
    check(
        "POST reaction with 11-char kind returns 422",
        response.status_code == 422,
        detail=f"got {response.status_code}",
    )

    # DELETE reaction happy path
    response = c.delete(f"/posts/{gold_post_id}/reactions/{fan_user}")
    check(
        "DELETE existing reaction returns 204",
        response.status_code == 204,
        detail=f"got {response.status_code}",
    )

    # DELETE reaction that was already removed
    response = c.delete(f"/posts/{gold_post_id}/reactions/{fan_user}")
    check(
        "DELETE reaction that no longer exists returns 404",
        response.status_code == 404,
        detail=f"got {response.status_code}",
    )

    # DELETE a reaction that never existed
    response = c.delete(f"/posts/99999999/reactions/{fan_user}")
    check(
        "DELETE reaction on non-existent post returns 404",
        response.status_code == 404,
        detail=f"got {response.status_code}",
    )

    # Cascade check: deleting a post wipes its reactions too.
    response = c.post(
        "/posts",
        json={"message": "doomed post"},
        headers={"X-Username": gold_user},
    )
    doomed_post_id = response.json()["id"]
    c.post(
        f"/posts/{doomed_post_id}/reactions",
        json={"username": fan_user, "kind": "+1"},
    )
    c.delete(f"/posts/{doomed_post_id}")
    # If the cascade worked, the reaction is already gone, so 404.
    response = c.delete(f"/posts/{doomed_post_id}/reactions/{fan_user}")
    check(
        "Deleting a post cascades to its reactions",
        response.status_code == 404,
        detail=f"got {response.status_code}",
    )

if __name__ == "__main__":
    sys.exit(main())