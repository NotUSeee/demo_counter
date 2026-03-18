"""
demo_counter — Advanced MMO Maid plugin demo.

Commands:
  !demo          — Count and greet (KV read/write + send message)
  !demo board    — Post a live counter board with +1 button
  !demo info     — Show server info (get_channel, get_member, list_roles)
  !demo edit     — Send a message, then edit it after 2 seconds
  !demo react    — Send a message and add reactions to it
  !demo embed    — Send a rich embed message
  !demo stats    — Show per-user command usage from KV (batch KV ops)
  !demo reset    — Reset the counter to zero (KV delete)
  !demo help     — Show available commands

Tests capabilities:
  storage:kv, discord:send_message, discord:edit_message,
  discord:delete_message, discord:add_reaction, discord:read,
  interaction:respond, events:message_content
"""
from __future__ import annotations

import time

from mmo_maid_sdk import Plugin, Context, Button, ActionRow

plugin = Plugin()


@plugin.on_ready
def ready(ctx: Context):
    ctx.log("demo_counter v3.0 started (SDK)")


@plugin.on_event("message_create")
def on_message(ctx: Context, event: dict):
    # Event payload uses flat fields: author_id, author_username (not nested author dict)
    author_id = str(event.get("author_id") or "")

    # Skip bot messages — check both flat and nested formats
    author = event.get("author") if isinstance(event.get("author"), dict) else {}
    if author.get("bot"):
        return

    content = str(event.get("content") or "").strip().lower()
    channel_id = str(event.get("channel_id") or "")
    user_id = author_id or str(author.get("id") or "")
    username = str(event.get("author_username") or "") or author.get("username") or "someone"

    if not content.startswith("!demo"):
        return

    if content == "!demo" or content == "!demo count":
        cmd_count(ctx, channel_id, user_id, username)
    elif content == "!demo board":
        cmd_board(ctx, channel_id, user_id, username)
    elif content == "!demo info":
        cmd_info(ctx, channel_id, user_id)
    elif content == "!demo edit":
        cmd_edit(ctx, channel_id)
    elif content == "!demo react":
        cmd_react(ctx, channel_id)
    elif content == "!demo embed":
        cmd_embed(ctx, channel_id, username)
    elif content == "!demo stats":
        cmd_stats(ctx, channel_id)
    elif content == "!demo reset":
        cmd_reset(ctx, channel_id)
    elif content == "!demo help":
        cmd_help(ctx, channel_id)


# ── Board: live-updating embed with buttons ──────────────────────────────────

def _build_board_embed(data: dict) -> dict:
    """Build the counter board embed from current data."""
    total = data.get("total", 0)
    users = data.get("users", {})
    goal = data.get("goal", 50)

    # Progress bar
    filled = min(int((total / max(goal, 1)) * 20), 20)
    bar = "\u2588" * filled + "\u2591" * (20 - filled)

    # Top contributors
    sorted_users = sorted(users.items(), key=lambda x: x[1], reverse=True)
    contrib_lines = []
    medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
    for i, (uid, count) in enumerate(sorted_users[:5]):
        medal = medals[i] if i < 3 else "\u2022"
        contrib_lines.append(f"{medal} <@{uid}> — **{count}** clicks")

    fields = [
        {
            "name": "Progress",
            "value": f"`{bar}` **{total}** / {goal}",
            "inline": False,
        },
    ]
    if contrib_lines:
        fields.append({
            "name": "Top Contributors",
            "value": "\n".join(contrib_lines),
            "inline": False,
        })
    fields.append({
        "name": "Total Participants",
        "value": str(len(users)),
        "inline": True,
    })
    fields.append({
        "name": "Clicks to Go",
        "value": str(max(0, goal - total)),
        "inline": True,
    })

    color = 0x2ECC71 if total >= goal else 0x58A6FF
    title = "\U0001f3c6 Goal Reached!" if total >= goal else "\U0001f4ca Counter Board"

    return {
        "title": title,
        "description": "Click the button below to add to the counter!",
        "color": color,
        "fields": fields,
        "footer": {"text": "MMO Maid Demo Counter \u2022 Live updating"},
    }


def _board_components() -> list:
    """Build the button row for the counter board."""
    return [
        ActionRow(
            Button("+1", custom_id="demo_increment", style="primary"),
            Button("+5", custom_id="demo_increment_5", style="secondary"),
            Button("Stats", custom_id="demo_show_stats", style="secondary"),
            Button("Reset", custom_id="demo_board_reset", style="danger"),
        ).to_dict(),
    ]


def cmd_board(ctx: Context, channel_id: str, user_id: str, username: str):
    """!demo board — Post a live counter board with interactive buttons."""
    data = ctx.kv.get("counter") or {"total": 0, "users": {}, "goal": 50}
    if not isinstance(data, dict):
        data = {"total": 0, "users": {}, "goal": 50}
    if "goal" not in data:
        data["goal"] = 50

    embed = _build_board_embed(data)
    result = ctx.discord.send_message(
        channel_id=channel_id,
        embeds=[embed],
        components=_board_components(),
    )
    msg_id = result.get("message_id")
    if msg_id:
        # Store the board message so we can edit it later
        ctx.kv.set("board", {
            "channel_id": channel_id,
            "message_id": str(msg_id),
        })
        ctx.log(f"Board posted: msg:{msg_id} in ch:{channel_id}")


def _update_board(ctx: Context):
    """Re-render and edit the board message with current data."""
    board = ctx.kv.get("board")
    if not board or not isinstance(board, dict):
        return
    channel_id = str(board.get("channel_id") or "")
    message_id = str(board.get("message_id") or "")
    if not channel_id or not message_id:
        return

    data = ctx.kv.get("counter") or {"total": 0, "users": {}, "goal": 50}
    embed = _build_board_embed(data)
    try:
        ctx.discord.edit_message(
            channel_id=channel_id,
            message_id=message_id,
            embeds=[embed],
        )
    except Exception as e:
        ctx.log(f"Board update failed: {e}", level="warning")


@plugin.on_component("demo_increment")
def on_increment(ctx: Context, event: dict):
    """Handle +1 button click."""
    user_id = str(event.get("user_id") or event.get("author_id") or "")
    data = ctx.kv.get("counter") or {"total": 0, "users": {}, "goal": 50}
    if not isinstance(data, dict):
        data = {"total": 0, "users": {}, "goal": 50}

    data["total"] = data.get("total", 0) + 1
    users = data.get("users", {})
    users[user_id] = users.get(user_id, 0) + 1
    data["users"] = users
    ctx.kv.set("counter", data)

    ctx.interaction.respond(
        content=f"**+1!** Counter is now at **{data['total']}**",
        ephemeral=True,
    )
    _update_board(ctx)


@plugin.on_component("demo_increment_5")
def on_increment_5(ctx: Context, event: dict):
    """Handle +5 button click."""
    user_id = str(event.get("user_id") or event.get("author_id") or "")
    data = ctx.kv.get("counter") or {"total": 0, "users": {}, "goal": 50}
    if not isinstance(data, dict):
        data = {"total": 0, "users": {}, "goal": 50}

    data["total"] = data.get("total", 0) + 5
    users = data.get("users", {})
    users[user_id] = users.get(user_id, 0) + 5
    data["users"] = users
    ctx.kv.set("counter", data)

    ctx.interaction.respond(
        content=f"**+5!** Counter is now at **{data['total']}**",
        ephemeral=True,
    )
    _update_board(ctx)


@plugin.on_component("demo_show_stats")
def on_show_stats(ctx: Context, event: dict):
    """Handle Stats button click — show stats as ephemeral message."""
    data = ctx.kv.get("counter") or {"total": 0, "users": {}}
    if not isinstance(data, dict):
        data = {"total": 0, "users": {}}

    total = data.get("total", 0)
    users = data.get("users", {})
    sorted_users = sorted(users.items(), key=lambda x: x[1], reverse=True)

    lines = [f"**Counter Stats** (total: **{total}**)\n"]
    for i, (uid, count) in enumerate(sorted_users[:10], 1):
        lines.append(f"{i}. <@{uid}> — {count} click(s)")
    if not sorted_users:
        lines.append("No clicks yet!")

    ctx.interaction.respond(content="\n".join(lines), ephemeral=True)


@plugin.on_component("demo_board_reset")
def on_board_reset(ctx: Context, event: dict):
    """Handle Reset button click."""
    data = {"total": 0, "users": {}, "goal": 50}
    ctx.kv.set("counter", data)
    ctx.interaction.respond(content="Counter has been reset to zero!", ephemeral=True)
    _update_board(ctx)


# ── Original command handlers ────────────────────────────────────────────────

def cmd_count(ctx: Context, channel_id: str, user_id: str, username: str):
    """!demo — Increment counter and greet."""
    data = ctx.kv.get("counter") or {"total": 0, "users": {}}
    if not isinstance(data, dict):
        data = {"total": 0, "users": {}}

    data["total"] = data.get("total", 0) + 1
    users = data.get("users", {})
    users[user_id] = users.get(user_id, 0) + 1
    data["users"] = users
    ctx.kv.set("counter", data)

    result = ctx.discord.send_message(
        channel_id=channel_id,
        content=(
            f"Hey **{username}**! Counter is now at **{data['total']}** "
            f"(you: **{users[user_id]}** times)."
        ),
    )
    msg_id = result.get("message_id")
    if msg_id:
        try:
            ctx.discord.add_reaction(channel_id=channel_id, message_id=str(msg_id), emoji="\U0001f44b")
        except Exception:
            pass

    # Also update the board if one exists
    _update_board(ctx)


def cmd_info(ctx: Context, channel_id: str, user_id: str):
    """!demo info — Show channel, member, and role info."""
    lines = ["**Server Info**\n"]

    ch = ctx.discord.get_channel(channel_id=channel_id)
    if ch:
        lines.append(f"\U0001f4dd Channel: **{ch.get('name', '?')}** (type: {ch.get('type', '?')})")
        if ch.get("topic"):
            lines.append(f"   Topic: {ch['topic']}")

    if user_id:
        member = ctx.discord.get_member(user_id=user_id)
        if member:
            display = member.get("display_name") or member.get("nick") or member.get("username") or "?"
            role_count = len(member.get("roles", []))
            joined = str(member.get("joined_at") or "?")[:10]
            lines.append(f"\U0001f464 You: **{display}** ({role_count} roles, joined {joined})")

    roles = ctx.discord.list_roles()
    if roles:
        named = [r for r in roles if r.get("name") != "@everyone"]
        named.sort(key=lambda r: r.get("position", 0), reverse=True)
        top_5 = named[:5]
        role_names = ", ".join(f"**{r.get('name', '?')}**" for r in top_5)
        lines.append(f"\U0001f3ad Top roles ({len(named)} total): {role_names}")

    ctx.discord.send_message(channel_id=channel_id, content="\n".join(lines))


def cmd_edit(ctx: Context, channel_id: str):
    """!demo edit — Send a message, wait, then edit it."""
    result = ctx.discord.send_message(
        channel_id=channel_id,
        content="\u231b This message will be edited in 2 seconds...",
    )
    msg_id = result.get("message_id")
    if not msg_id:
        return
    ctx.log("Sent message, waiting 2s before edit")
    time.sleep(2)
    ctx.discord.edit_message(
        channel_id=channel_id,
        message_id=str(msg_id),
        content="\u2705 Message edited! The edit_message capability works.",
    )
    try:
        ctx.discord.add_reaction(channel_id=channel_id, message_id=str(msg_id), emoji="\u270f\ufe0f")
    except Exception:
        pass


def cmd_react(ctx: Context, channel_id: str):
    """!demo react — Send a message and add reactions."""
    result = ctx.discord.send_message(
        channel_id=channel_id,
        content="React test \u2014 watch the reactions appear:",
    )
    msg_id = result.get("message_id")
    if not msg_id:
        return
    for emoji in ["\u2705", "\U0001f389"]:
        try:
            ctx.discord.add_reaction(channel_id=channel_id, message_id=str(msg_id), emoji=emoji)
        except Exception:
            break
        time.sleep(0.3)


def cmd_embed(ctx: Context, channel_id: str, username: str):
    """!demo embed — Send a rich embed."""
    data = ctx.kv.get("counter") or {"total": 0, "users": {}}
    total = data.get("total", 0) if isinstance(data, dict) else 0

    ctx.discord.send_message(
        channel_id=channel_id,
        embeds=[{
            "title": "Demo Counter Dashboard",
            "description": f"Plugin is running and has counted **{total}** total interactions.",
            "color": 0x58A6FF,
            "fields": [
                {"name": "Triggered by", "value": username, "inline": True},
                {"name": "Total count", "value": str(total), "inline": True},
                {"name": "Capabilities tested", "value": (
                    "\u2705 storage:kv\n"
                    "\u2705 discord:send_message\n"
                    "\u2705 discord:read\n"
                    "\u2705 interaction:respond\n"
                    "\u2705 events:message_content"
                ), "inline": False},
            ],
            "footer": {"text": "MMO Maid Plugin System"},
        }],
    )


def cmd_stats(ctx: Context, channel_id: str):
    """!demo stats — Show per-user stats from KV."""
    data = ctx.kv.get("counter") or {"total": 0, "users": {}}
    if not isinstance(data, dict):
        ctx.discord.send_message(channel_id=channel_id, content="No stats yet \u2014 use the counter first.")
        return

    total = data.get("total", 0)
    users = data.get("users", {})

    if not users:
        ctx.discord.send_message(channel_id=channel_id, content=f"Counter is at **{total}** but no per-user data yet.")
        return

    sorted_users = sorted(users.items(), key=lambda x: x[1], reverse=True)
    lines = [f"**Counter Stats** (total: **{total}**)\n"]
    for i, (uid, count) in enumerate(sorted_users[:10], 1):
        lines.append(f"{i}. <@{uid}> \u2014 {count} time(s)")

    ctx.discord.send_message(channel_id=channel_id, content="\n".join(lines))


def cmd_reset(ctx: Context, channel_id: str):
    """!demo reset — Reset the counter."""
    ctx.kv.delete("counter")
    result = ctx.discord.send_message(channel_id=channel_id, content="\U0001f504 Counter has been reset to zero.")
    msg_id = result.get("message_id")
    if msg_id:
        try:
            ctx.discord.add_reaction(channel_id=channel_id, message_id=str(msg_id), emoji="\U0001f504")
        except Exception:
            pass
    _update_board(ctx)


def cmd_help(ctx: Context, channel_id: str):
    """!demo help — Show all commands."""
    ctx.discord.send_message(channel_id=channel_id, content="\n".join([
        "**Demo Counter Commands**",
        "",
        "`!demo` \u2014 Increment counter and greet",
        "`!demo board` \u2014 Post a live counter board with buttons",
        "`!demo info` \u2014 Show channel, member, and role info",
        "`!demo edit` \u2014 Send a message then edit it",
        "`!demo react` \u2014 Send a message with multiple reactions",
        "`!demo embed` \u2014 Send a rich embed message",
        "`!demo stats` \u2014 Show per-user usage leaderboard",
        "`!demo reset` \u2014 Reset the counter to zero",
        "`!demo help` \u2014 This message",
    ]))


plugin.run()
