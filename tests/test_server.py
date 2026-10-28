"""Offline tests: the Mattermost API is replaced by an in-memory fake behind httpx.MockTransport.

Run: uv run --with pytest --with 'mcp>=2.3,<3' --with 'httpx>=0.27' pytest -q
"""

import importlib.util
import json
import os
import re
import time
from pathlib import Path

import httpx
import pytest

os.environ.update(
    MATTERMOST_MCP_CONFIG="/nonexistent/.env",
    MATTERMOST_BASE_URL="https://mm.test",
    MATTERMOST_TOKEN="test-token",
)
_spec = importlib.util.spec_from_file_location("server", Path(__file__).resolve().parents[1] / "server.py")
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)


def _id(name: str) -> str:
    return (name + "0" * 26)[:26]


ME, BOB, CAROL = _id("me"), _id("bob"), _id("carol")
TEAM, OTHER_TEAM = _id("team"), _id("teamtwo")
DM_BOB, DM_CAROL, INFRA = _id("dmbob"), _id("dmcarol"), _id("infra")
NOW = int(time.time() * 1000)
HOUR = 3600 * 1000


def _user(uid: str, username: str) -> dict:
    return {"id": uid, "username": username, "first_name": username.title(), "last_name": ""}


def _post(pid: str, channel: str, user: str, message: str, at: int, root: str = "") -> dict:
    return {"id": pid, "channel_id": channel, "user_id": user, "message": message, "create_at": at, "root_id": root}


class FakeMattermost:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self.users = {u["id"]: u for u in (_user(ME, "me"), _user(BOB, "bob"), _user(CAROL, "carol"))}
        self.channels = {
            DM_BOB: {"id": DM_BOB, "type": "D", "name": f"{BOB}__{ME}", "team_id": "", "total_msg_count": 5, "last_post_at": NOW - HOUR},
            DM_CAROL: {"id": DM_CAROL, "type": "D", "name": f"{ME}__{CAROL}", "team_id": "", "total_msg_count": 1, "last_post_at": NOW - 120 * HOUR},
            INFRA: {"id": INFRA, "type": "O", "name": "infra", "display_name": "Infra", "team_id": TEAM, "total_msg_count": 10, "last_post_at": NOW - 2 * HOUR},
        }
        self.members = [
            {"channel_id": DM_BOB, "msg_count": 3, "mention_count": 2, "last_viewed_at": NOW - 3 * HOUR},
            {"channel_id": DM_CAROL, "msg_count": 0, "mention_count": 1, "last_viewed_at": 0},
            {"channel_id": INFRA, "msg_count": 8, "mention_count": 1, "last_viewed_at": NOW - 5 * HOUR},
        ]
        self.posts = {
            p["id"]: p
            for p in (
                _post(_id("p1"), DM_BOB, BOB, "can you look at the deploy?", NOW - HOUR),
                _post(_id("p2"), DM_CAROL, CAROL, "old question", NOW - 120 * HOUR),
                _post(_id("p3"), INFRA, BOB, "@me ping", NOW - 3 * HOUR),
                _post(_id("p4"), INFRA, ME, "done", NOW - 2 * HOUR),
                _post(_id("root"), INFRA, BOB, "thread root", NOW - 4 * HOUR),
                _post(_id("reply"), INFRA, ME, "my reply", NOW - 3 * HOUR, root=_id("root")),
            )
        }
        # file id -> (name, content, size reported by /info)
        self.files = {_id("file"): ("report.txt", b"hello world", 11)}

    def _posts_response(self, posts: list[dict]) -> dict:
        posts = sorted(posts, key=lambda p: p["create_at"], reverse=True)
        return {"order": [p["id"] for p in posts], "posts": {p["id"]: p for p in posts}}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v4")
        body = json.loads(request.content) if request.headers.get("content-type") == "application/json" else None
        self.calls.append((request.method, path, body))
        route = f"{request.method} {path}"

        if route == "GET /users/me":
            return httpx.Response(200, json=self.users[ME])
        if route == "GET /users/me/teams":
            return httpx.Response(200, json=[{"id": TEAM, "name": "team", "display_name": "Team"}, {"id": OTHER_TEAM, "name": "other", "display_name": "Other"}])
        if m := re.fullmatch(r"GET /users/me/teams/(\w+)/channels", route):
            # DMs show up under every team; the public channel only under its own.
            return httpx.Response(200, json=[c for c in self.channels.values() if c["team_id"] in ("", m[1])])
        if m := re.fullmatch(r"GET /users/me/teams/(\w+)/channels/members", route):
            return httpx.Response(200, json=[x for x in self.members if self.channels[x["channel_id"]]["team_id"] in ("", m[1])])
        if m := re.fullmatch(r"GET /channels/(\w+)/posts", route):
            since = int(request.url.params.get("since", 0))
            return httpx.Response(200, json=self._posts_response([p for p in self.posts.values() if p["channel_id"] == m[1] and p["create_at"] >= since]))
        if m := re.fullmatch(r"GET /channels/(\w+)", route):
            return httpx.Response(200, json=self.channels[m[1]]) if m[1] in self.channels else httpx.Response(404, json={"message": "not found"})
        if m := re.fullmatch(r"GET /posts/(\w+)", route):
            return httpx.Response(200, json=self.posts[m[1]])
        if m := re.fullmatch(r"GET /users/username/(.+)", route):
            user = next((u for u in self.users.values() if u["username"] == m[1]), None)
            return httpx.Response(200, json=user) if user else httpx.Response(404, json={"message": "not found"})
        if route == "POST /users/ids":
            return httpx.Response(200, json=[self.users[i] for i in body if i in self.users])
        if re.fullmatch(r"GET /users/\w+/teams/\w+/threads", route):
            return httpx.Response(200, json={"threads": []})
        if route == "POST /channels/direct":
            return httpx.Response(201, json=self.channels[DM_BOB])
        if route == "POST /posts":
            return httpx.Response(201, json={"id": _id("new"), "create_at": NOW, "user_id": ME, **body})
        if m := re.fullmatch(r"PUT /posts/(\w+)/patch", route):
            return httpx.Response(200, json={**self.posts[m[1]], **body, "edit_at": NOW})
        if route == "POST /reactions":
            return httpx.Response(201, json=body)
        if re.fullmatch(r"DELETE /users/\w+/posts/\w+/reactions/.+", route):
            return httpx.Response(200, json={"status": "OK"})
        if route == "POST /channels/members/me/view":
            return httpx.Response(200, json={"status": "OK"})
        if re.fullmatch(r"PUT /users/\w+/teams/\w+/threads/\w+/read/\d+", route):
            return httpx.Response(200, json={})
        if m := re.fullmatch(r"GET /files/(\w+)/info", route):
            name, _, size = self.files[m[1]]
            return httpx.Response(200, json={"id": m[1], "name": name, "size": size, "mime_type": "text/plain"})
        if m := re.fullmatch(r"GET /files/(\w+)", route):
            return httpx.Response(200, content=self.files[m[1]][1])
        return httpx.Response(404, json={"message": f"fake: no route for {route}"})


@pytest.fixture
def fake(monkeypatch):
    fake = FakeMattermost()
    client = server.Mattermost()
    client.http = httpx.Client(base_url="https://mm.test/api/v4", transport=httpx.MockTransport(fake))
    monkeypatch.setattr(server, "mm", client)
    return fake


def test_resolve_channel_by_name_dm_and_url(fake):
    assert server._resolve_channel("~infra")["id"] == INFRA
    assert server._resolve_channel("Infra")["id"] == INFRA
    assert server._resolve_channel("@bob")["id"] == DM_BOB
    assert server._resolve_channel("https://mm.test/team/channels/infra")["id"] == INFRA
    assert server._resolve_channel(f"https://mm.test/team/pl/{_id('p3')}")["id"] == INFRA
    with pytest.raises(ValueError, match="not found"):
        server._resolve_channel("nope")


def test_get_unread_statuses(fake):
    result = server.get_unread()
    dms = {c["title"]: c for c in result["direct_messages"]}
    assert dms["@bob"]["status"] == "awaiting_reply"
    assert dms["@carol"]["status"] == "awaiting_reply_stale"
    assert dms["@carol"]["collapsed"] is True and len(dms["@carol"]["posts"]) == 1
    [infra] = result["mentions"]
    assert infra["status"] == "you_replied_last"
    # DM "mentions" are not counted as channel mentions.
    assert result["summary"]["channel_mentions"] == 1
    assert result["summary"]["awaiting_reply"] == 1
    # DMs are listed under both teams but reported once.
    assert len(result["direct_messages"]) == 2


def test_send_message_reply_goes_to_thread_root(fake):
    result = server.send_message("ack", reply_to=f"https://mm.test/team/pl/{_id('reply')}")
    [(_, _, body)] = [c for c in fake.calls if c[:2] == ("POST", "/posts")]
    assert body == {"channel_id": INFRA, "message": "ack", "root_id": _id("root"), "file_ids": []}
    assert result["status"] == "sent" and result["channel"] == "Infra"


def test_send_message_to_dm(fake):
    server.send_message("hi", channel="@bob")
    [(_, _, body)] = [c for c in fake.calls if c[:2] == ("POST", "/posts")]
    assert body["channel_id"] == DM_BOB and body["root_id"] == ""


def test_edit_message_only_own(fake):
    with pytest.raises(server.ToolError, match="own messages"):
        server.edit_message(_id("p3"), "hacked")
    result = server.edit_message(_id("p4"), "done, deployed")
    assert result["previous_message"] == "done" and result["message"] == "done, deployed"


def test_react_and_unreact(fake):
    server.react(_id("p3"), ":+1:")
    assert ("POST", "/reactions", {"user_id": ME, "post_id": _id("p3"), "emoji_name": "+1"}) in fake.calls
    server.react(_id("p3"), "+1", remove=True)
    assert any(c[0] == "DELETE" and c[1].endswith(f"/posts/{_id('p3')}/reactions/+1") for c in fake.calls)


def test_mark_read_channel_and_thread(fake):
    result = server.mark_read(channel="infra", thread=_id("reply"))
    assert result == {"marked_read": {"channel": "Infra", "thread": _id("root")}}
    assert ("POST", "/channels/members/me/view", {"channel_id": INFRA}) in fake.calls
    assert any(c[0] == "PUT" and f"/teams/{TEAM}/threads/{_id('root')}/read/" in c[1] for c in fake.calls)


def test_tool_errors_reach_the_client(fake):
    with pytest.raises(server.ToolError, match="Pass channel or reply_to"):
        server.send_message("orphan")


def test_send_message_refuses_more_than_10_attachments(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "UPLOAD_DIRS", [tmp_path])
    paths = []
    for i in range(11):
        (tmp_path / f"f{i}.txt").write_text("x")
        paths.append(str(tmp_path / f"f{i}.txt"))
    with pytest.raises(server.ToolError, match="At most 10 files"):
        server.send_message("files", channel="infra", file_paths=paths)
    assert not any(c[:2] == ("POST", "/posts") for c in fake.calls)


@pytest.fixture
def downloads(tmp_path, monkeypatch):
    target = tmp_path / "downloads"
    target.mkdir()
    monkeypatch.setattr(server, "DOWNLOADS_DIR", target)
    return target


def test_download_never_overwrites_or_follows_symlinks(fake, downloads, tmp_path):
    (downloads / "report.txt").write_text("mine")
    # A dangling symlink at the next free name must not redirect the write outside the directory.
    (downloads / "report (1).txt").symlink_to(tmp_path / "escaped.txt")
    result = server.download_file(_id("file"))
    assert Path(result["path"]) == downloads / "report (2).txt"
    assert Path(result["path"]).read_bytes() == b"hello world"
    assert (downloads / "report.txt").read_text() == "mine"
    assert not (tmp_path / "escaped.txt").exists()


def test_download_over_the_size_limit_is_refused(fake, downloads, monkeypatch):
    monkeypatch.setattr(server, "MAX_DOWNLOAD_BYTES", 5)
    with pytest.raises(server.ToolError, match="download limit"):
        server.download_file(_id("file"))
    # Refused on the reported size, before the content is requested.
    assert not any(c[:2] == ("GET", f"/files/{_id('file')}") for c in fake.calls)
    assert not list(downloads.iterdir())


def test_download_limit_holds_when_the_reported_size_lies(fake, downloads, monkeypatch):
    monkeypatch.setattr(server, "MAX_DOWNLOAD_BYTES", 5)
    fake.files[_id("file")] = ("report.txt", b"hello world", 1)
    with pytest.raises(server.ToolError, match="download limit"):
        server.download_file(_id("file"))
    assert not list(downloads.iterdir())
