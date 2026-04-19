from fastapi import FastAPI, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field

import db

# This runs at startup and creates every table if they don't already exist.
db.init_db()

# The FastAPI app itself. Every route below gets registered on this object.
app = FastAPI()

# Pydantic models
# These are the shape checks for incoming request bodies. If a request
# doesn't fit the shape, FastAPI returns 422 automatically.

class UserCreate(BaseModel):
    # Shape for creating a new user. Username rules live here.
    username: str = Field(min_length=3, max_length=20, pattern=r"^[a-zA-Z0-9_]+$")

class PostCreate(BaseModel):
    # Shape for creating a new post. Message has to be non empty and under 500 chars.
    message: str = Field(min_length=1, max_length=500)

class UserPatch(BaseModel):
    # Shape for updating a bio. bio is optional, max 200 chars or else 422.
    bio: str | None = Field(default=None, max_length=200)

class PostPatch(BaseModel):
    # Shape for editing a post. Same rules as creating one.
    message: str = Field(min_length=1, max_length=500)

class ReactionCreate(BaseModel):
    # Shape for a new reaction. kind is kept short so we can swap in emoji later.
    username: str = Field(min_length=3, max_length=20, pattern=r"^[a-zA-Z0-9_]+$")
    kind: str = Field(min_length=1, max_length=10)

# User routes

@app.post("/users", status_code=201)
def create_user(body: UserCreate):
    # Creates a new user. Returns 409 if the name is already taken.
    if db.get_user(body.username):
        raise HTTPException(409, "username already exists")
    return db.create_user(body.username)

@app.get("/users")
def list_users():
    # Returns every user.
    return db.list_users()

@app.get("/users/{username}")
def get_user(username: str):
    # Gets one user by their username. 404 if they don't exist.
    user = db.get_user(username)
    if not user:
        raise HTTPException(404, "user not found")
    return user

@app.patch("/users/{username}")
def patch_user(username: str, body: UserPatch):
    # Updates a user's bio and returns the fresh user object.
    if not db.get_user(username):
        raise HTTPException(404, "user not found")
    return db.update_user_bio(username, body.bio)

@app.get("/users/{username}/posts")
def get_user_posts(username: str):
    # Returns every post written by a specific user.
    if not db.get_user(username):
        raise HTTPException(404, "user not found")
    return db.get_posts_by_user(username)

# Post routes

@app.post("/posts", status_code=201)
def create_post(
    body: PostCreate,
    x_username: str | None = Header(default=None),
):
    # Creates a new post. The X-Username header says who is posting.
    if x_username is None:
        raise HTTPException(400, "missing X-Username header")
    if not db.get_user(x_username):
        raise HTTPException(404, "user not found")
    return db.create_post(x_username, body.message)

@app.get("/posts")
def list_posts(
    q: str | None = None,
    username: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    # Lists posts. Supports ?q= search, ?username= filter, and pagination.
    return db.list_posts(q=q, username=username, limit=limit, offset=offset)

@app.get("/posts/{post_id}")
def get_post(post_id: int):
    # Gets one post by id. 404 if it doesn't exist.
    post = db.get_post(post_id)
    if not post:
        raise HTTPException(404, "post not found")
    return post

@app.patch("/posts/{post_id}")
def patch_post(
    post_id: int,
    body: PostPatch,
    x_username: str | None = Header(default=None),
):
    # Edits a post's message. Only the original author is allowed.
    if x_username is None:
        raise HTTPException(400, "missing X-Username header")
    if not db.get_user(x_username):
        raise HTTPException(404, "user not found")
    post = db.get_post(post_id)
    if not post:
        raise HTTPException(404, "post not found")
    if post["username"] != x_username:
        # Ownership rule: only the original author can edit their own post.
        raise HTTPException(403, "only the original author can edit this post")
    return db.update_post_message(post_id, body.message)

@app.delete("/posts/{post_id}", status_code=204)
def delete_post(post_id: int):
    # Deletes a post. Its reactions get removed in the same transaction.
    if not db.delete_post(post_id):
        raise HTTPException(404, "post not found")
    return Response(status_code=204)

# Reaction routes (Gold)

@app.post("/posts/{post_id}/reactions", status_code=201)
def create_reaction(post_id: int, body: ReactionCreate):
    # Creates a reaction on a post. 409 if this user already reacted here.
    if not db.get_post(post_id):
        raise HTTPException(404, "post not found")
    if not db.get_user(body.username):
        raise HTTPException(404, "user not found")
    if db.get_reaction(post_id, body.username):
        raise HTTPException(409, "reaction already exists")
    return db.create_reaction(post_id, body.username, body.kind)

@app.delete("/posts/{post_id}/reactions/{username}", status_code=204)
def delete_reaction(post_id: int, username: str):
    # Removes a user's reaction from a post.
    if not db.delete_reaction(post_id, username):
        raise HTTPException(404, "reaction not found")
    return Response(status_code=204)
