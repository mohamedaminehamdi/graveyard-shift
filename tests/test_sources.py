"""The readers only read: Gmail is examined and peeked at, chat databases open read-only, Slack only hears GETs."""
import io
import sqlite3
import ssl
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from graveyard_shift import sources

NOW = datetime(2026, 10, 29, 21, 0, tzinfo=timezone.utc)


def ago(**delta):
    return NOW - timedelta(**delta)


def test_gmail_only_examines_and_peeks(tmp_path, monkeypatch):
    letters = [b"From: Ana Ruiz <ana@example.com>\r\nSubject: Dinner Friday?\r\n\r\nAre we still on?\r\n",
               b"From: Hans Kessler <hans@example.com>\r\nSubject: Contract v3\r\n\r\nSigned copy attached.\r\n"]
    calls = []

    class FakeIMAP:
        def __init__(self, *args, **kwargs):
            calls.append(("connect", args, kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.logout()

        def __getattr__(self, name):   # records every call, including any it should never make
            def method(*args, **kwargs):
                calls.append((name, args, kwargs))
                if name == "search":
                    return "OK", [b"1 2"]
                if name == "fetch":
                    letter = letters[int(args[0]) - 1]
                    return "OK", [(b"%s (BODY[] {%d}" % (args[0], len(letter)), letter), b")"]
                return "OK", [b""]
            return method

    monkeypatch.setattr(sources.imaplib, "IMAP4_SSL", FakeIMAP)
    assert sources.gmail_letters("marisol@gmail.com", "app-password", tmp_path / "mail") == 2
    names = [name for name, _, _ in calls]
    context = calls[0][2]["ssl_context"]
    assert calls[0][1] == ("imap.gmail.com", 993) and context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert ("select", ("INBOX",), {"readonly": True}) in calls and names[-1] == "logout"
    assert names.count("fetch") == 2 and all("BODY.PEEK[]" in args[1] for name, args, _ in calls if name == "fetch")
    assert not {"store", "append", "copy", "move", "expunge", "uid"} & set(names)
    subjects = [sources.read_eml(p)["subject"] for p in sorted((tmp_path / "mail").glob("*.eml"))]
    assert subjects == ["Dinner Friday?", "Contract v3"]


def test_imessage_reads_texts_and_attributed_bodies_read_only(tmp_path):
    db = tmp_path / "chat.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT, attributedBody BLOB, handle_id INTEGER, date INTEGER,
                              is_from_me INTEGER, associated_message_type INTEGER, item_type INTEGER);
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT, display_name TEXT);
        CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
        INSERT INTO handle VALUES (1, '+34600111222');
        INSERT INTO chat VALUES (1, '+34600111222', '');
    """)
    late = "Running 10 minutes late, sorry!".encode()
    body = b"streamtyped...NSString" + b"\x01\x94\x84\x01+" + bytes([len(late)]) + late

    def at(**delta):   # nanoseconds since 2001
        return int((ago(**delta) - sources.APPLE_EPOCH).total_seconds() * 1e9)

    messages = [(1, "Are we still on for dinner?", None, 1, at(hours=3), 0, 0, 0),
                (2, None, body, 1, at(hours=1), 1, 0, 0),                                       # attributedBody only
                (3, "Loved “Are we still on for dinner?”", None, 1, at(hours=2), 0, 2000, 0),   # a tapback
                (4, "See you in March!", None, 1, at(days=3), 0, 0, 0)]                         # too old
    con.executemany("INSERT INTO message VALUES (?, ?, ?, ?, ?, ?, ?, ?)", messages)
    con.executemany("INSERT INTO chat_message_join VALUES (1, ?)", [(m[0],) for m in messages])
    con.commit()
    con.close()
    db.chmod(0o444)

    [thread] = sources.imessage_threads(db, now=NOW)
    assert (thread["app"], thread["with"], thread["link"]) == ("imessage", "+34600111222", "sms:+34600111222")
    assert [(m["from"], m["me"], m["text"]) for m in thread["messages"]] == [
        ("+34600111222", False, "Are we still on for dinner?"), ("me", True, "Running 10 minutes late, sorry!")]
    long = "ñ" * 100   # 200 bytes: past 127 the length is 0x81 and two little-endian bytes
    assert sources._typedstream_text(b"NSString\x01\x94\x84\x01+\x81\xc8\x00" + long.encode()) == long


def test_whatsapp_reads_one_to_one_and_group_chats(tmp_path):
    db = tmp_path / "ChatStorage.sqlite"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE ZWACHATSESSION (Z_PK INTEGER PRIMARY KEY, ZPARTNERNAME TEXT, ZCONTACTJID TEXT);
        CREATE TABLE ZWAMESSAGE (Z_PK INTEGER PRIMARY KEY, ZCHATSESSION INTEGER, ZISFROMME INTEGER, ZTEXT TEXT,
                                 ZMESSAGEDATE REAL);
        INSERT INTO ZWACHATSESSION VALUES (1, 'Ana Ruiz', '34600111222@s.whatsapp.net'), (2, 'Book club', '1203630@g.us');
    """)

    def at(**delta):   # seconds since 2001
        return (ago(**delta) - sources.APPLE_EPOCH).total_seconds()

    con.executemany("INSERT INTO ZWAMESSAGE VALUES (?, ?, ?, ?, ?)", [
        (1, 1, 0, "Can you call me after 6?", at(hours=5)), (2, 1, 1, "Sure, around 7", at(hours=4)),
        (3, 1, 0, None, at(hours=4)),                                                   # a photo: no text
        (4, 2, 0, "Chapter 7 by Sunday?", at(hours=2)), (5, 2, 1, "Last month's pick was great", at(days=30))])
    con.commit()
    con.close()
    db.chmod(0o444)

    club, ana = sources.whatsapp_threads(db, now=NOW)   # the newest conversation first
    assert ana == {"app": "whatsapp", "with": "Ana Ruiz", "link": "whatsapp://send?phone=34600111222", "messages": [
        {"from": "Ana Ruiz", "me": False, "text": "Can you call me after 6?", "at": "2026-10-29T16:00:00+00:00"},
        {"from": "me", "me": True, "text": "Sure, around 7", "at": "2026-10-29T17:00:00+00:00"}]}
    assert (club["with"], club["link"], [m["from"] for m in club["messages"]]) == ("Book club", "", ["a member"])


def test_slack_reads_dms_through_four_read_methods():
    def ts(**delta):
        return str(ago(**delta).timestamp())

    users = {"U0ANA": "Ana Ruiz", "U0BOB": "Bob Lee"}
    history = {"D01": [{"user": "U0ME", "text": "On my way", "ts": ts(hours=1)},
                       {"user": "U0ANA", "text": "Where are you?", "ts": ts(hours=2)}],
               "G01": [{"subtype": "channel_join", "user": "U0BOB", "text": "<@U0BOB> joined", "ts": ts(hours=3)},
                       {"subtype": "bot_message", "username": "deploybot", "text": "v2 is live", "ts": ts(hours=4)},
                       {"user": "U0BOB", "text": "Slides are up", "ts": ts(hours=5)}]}
    called = []

    def get(method, params):
        called.append(method)
        return {"ok": True, **{   # any other method is a KeyError
            "auth.test": lambda: {"user_id": "U0ME", "team_id": "T01"},
            "conversations.list": lambda: {"channels": [{"id": "D01", "is_im": True, "user": "U0ANA"},
                                                        {"id": "G01", "is_mpim": True}]},
            "conversations.history": lambda: {"messages": history[params["channel"]]},
            "users.info": lambda: {"user": {"real_name": users[params["user"]]}},
        }[method]()}

    dm, group = sources.slack_threads("xoxp-secret", now=NOW, get=get)
    assert set(called) == {"auth.test", "conversations.list", "conversations.history", "users.info"}
    assert called.count("users.info") == 2   # each name is asked for once
    assert (dm["app"], dm["with"], dm["link"]) == ("slack", "Ana Ruiz", "slack://channel?team=T01&id=D01")
    assert [(m["from"], m["me"], m["text"]) for m in dm["messages"]] == [
        ("Ana Ruiz", False, "Where are you?"), ("me", True, "On my way")]
    assert group["with"] == "group DM" and [m["from"] for m in group["messages"]] == ["Bob Lee", "deploybot"]


def test_slack_errors_never_carry_the_token(monkeypatch):
    sent = []

    def urlopen(req, timeout):
        sent.append(req)
        return io.BytesIO(b'{"ok": false, "error": "invalid_auth"}')

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(RuntimeError, match="invalid_auth") as refused:
        sources.slack_threads("xoxp-secret")
    assert "xoxp-secret" not in str(refused.value)
    assert [(r.get_method(), r.full_url) for r in sent] == [("GET", "https://slack.com/api/auth.test?")]
    assert sent[0].get_header("Authorization") == "Bearer xoxp-secret"


def test_one_time_codes_never_reach_a_ghost():
    codes = ["Your Lantern Bank code is 482913", "G-123456 is your verification code", "Use 4821 to sign in",
             "Reset your password: https://lantern.example/reset?t=8f2c", "Your OTP is 771204", "Tu código es 551234"]
    ordinary = ["lunch at 12:30?", "Can you bring the 2 files?", "Invoice 0042 is attached"]

    def thread(texts):
        return {"app": "imessage", "with": "Ana", "link": "", "messages": [
            {"from": "Ana", "me": False, "text": t, "at": NOW.isoformat()} for t in texts]}

    kept, skipped = sources.drop_codes([thread(codes + ordinary), thread(codes)])
    assert skipped == 2 * len(codes)
    assert [[m["text"] for m in t["messages"]] for t in kept] == [ordinary]
