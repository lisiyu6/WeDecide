"""Small, bounded pieces of context shared by all decision AI calls."""
from datetime import datetime
from zoneinfo import ZoneInfo
from .config import TIMEZONE


def calendar_context(now=None):
    current=(now or datetime.now(ZoneInfo(TIMEZONE))).astimezone(ZoneInfo(TIMEZONE))
    return {"date":current.date().isoformat(), "time":current.strftime("%H:%M"),
            "weekday":["星期一","星期二","星期三","星期四","星期五","星期六","星期日"][current.weekday()],
            "timezone":TIMEZONE}


def visible_supplements(room, user_id=None):
    return [item for item in room.get("supplements", [])
            if item["visibility"]=="shared" or item["member_id"]==user_id][-100:]
