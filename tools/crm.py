from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiosqlite

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps_safe(value: Any, *, default: Any = None) -> str:
    try:
        return json.dumps(value)
    except Exception:  # noqa: BLE001
        return json.dumps(default)


def _json_loads_safe(value: Any, *, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except Exception:  # noqa: BLE001
        return default


@dataclass(frozen=True)
class CRMResult:
    ok: bool
    data: Dict[str, Any]


class SQLiteCRM:
    """
    SQLite-backed CRM module (no ORM).

    Schema:
      users(
        user_id TEXT PRIMARY KEY,
        name TEXT,
        email TEXT,
        phone TEXT,
        preferences TEXT,              -- JSON string
        interaction_history TEXT,      -- JSON list of strings
        created_at TEXT,
        updated_at TEXT
      )
    """

    def __init__(self, db_path: str = "data/crm.db"):
        self.db_path = db_path
        self._initialized = False
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)

    async def _get_existing_columns(self, db: aiosqlite.Connection) -> List[str]:
        cur = await db.execute("PRAGMA table_info(users)")
        rows = await cur.fetchall()
        await cur.close()
        return [str(row[1]) for row in rows]

    async def _migrate_legacy_schema(self, db: aiosqlite.Connection) -> None:
        """
        Migrate older CRM schemas in place.

        Legacy shape observed in this repo:
          users(user_id TEXT PRIMARY KEY, data TEXT)
        New shape:
          users(user_id, name, email, phone, preferences, interaction_history, created_at, updated_at)
        """
        expected_columns = {
            "user_id": "TEXT PRIMARY KEY",
            "name": "TEXT",
            "email": "TEXT",
            "phone": "TEXT",
            "preferences": "TEXT",
            "interaction_history": "TEXT",
            "created_at": "TEXT",
            "updated_at": "TEXT",
        }

        existing_columns = await self._get_existing_columns(db)
        if not existing_columns:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    name TEXT,
                    email TEXT,
                    phone TEXT,
                    preferences TEXT,
                    interaction_history TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            return

        for column_name, column_sql in expected_columns.items():
            if column_name not in existing_columns:
                await db.execute(f"ALTER TABLE users ADD COLUMN {column_name} {column_sql}")

        if "data" in existing_columns:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT user_id, data, name, email, phone, preferences, interaction_history, created_at, updated_at
                FROM users
                """
            )
            rows = await cur.fetchall()
            await cur.close()

            for row in rows:
                legacy = _json_loads_safe(row["data"], default={})
                if not isinstance(legacy, dict):
                    legacy = {}

                merged_name = row["name"] or legacy.get("name")
                merged_email = row["email"] or legacy.get("email")
                merged_phone = row["phone"] or legacy.get("phone")

                merged_preferences = _json_loads_safe(row["preferences"], default={})
                if not isinstance(merged_preferences, dict) or not merged_preferences:
                    merged_preferences = legacy.get("preferences", {})
                if not isinstance(merged_preferences, dict):
                    merged_preferences = {}

                merged_history = _json_loads_safe(row["interaction_history"], default=[])
                if not isinstance(merged_history, list) or not merged_history:
                    merged_history = legacy.get("interaction_history", legacy.get("history", []))
                if not isinstance(merged_history, list):
                    merged_history = []

                created_at = row["created_at"] or legacy.get("created_at") or _utc_now_iso()
                updated_at = row["updated_at"] or legacy.get("updated_at") or created_at

                await db.execute(
                    """
                    UPDATE users
                    SET name = ?, email = ?, phone = ?, preferences = ?, interaction_history = ?, created_at = ?, updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        merged_name,
                        merged_email,
                        merged_phone,
                        _json_dumps_safe(merged_preferences, default={}),
                        _json_dumps_safe(merged_history, default=[]),
                        created_at,
                        updated_at,
                        row["user_id"],
                    ),
                )

    async def init_db(self) -> None:
        if self._initialized:
            return
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await self._migrate_legacy_schema(db)
                await db.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
                await db.commit()
            self._initialized = True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to initialize CRM database: %s", exc)

    async def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """
        Return full user record (dict) or a not-found message.
        Never creates records implicitly.
        """
        if not user_id or not str(user_id).strip():
            return {"ok": False, "error": "user_id is required"}

        await self.init_db()
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute(
                    """
                    SELECT user_id, name, email, phone, preferences, interaction_history, created_at, updated_at
                    FROM users
                    WHERE user_id = ?
                    """,
                    (user_id,),
                )
                row = await cur.fetchone()
                await cur.close()

            if not row:
                return {"ok": True, "message": "not found", "user_id": user_id}

            return {
                "ok": True,
                "user": {
                    "user_id": row["user_id"],
                    "name": row["name"],
                    "email": row["email"],
                    "phone": row["phone"],
                    "preferences": _json_loads_safe(row["preferences"], default={}),
                    "interaction_history": _json_loads_safe(row["interaction_history"], default=[]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                },
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("CRM get_user_info failed for %s: %s", user_id, exc)
            return {"ok": False, "error": "failed to fetch user info", "user_id": user_id}

    async def store_user_info(
        self,
        user_id: str,
        name: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        preferences: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new user; error if already exists."""
        if not user_id or not str(user_id).strip():
            return {"ok": False, "error": "user_id is required"}

        await self.init_db()
        now = _utc_now_iso()
        prefs_json = _json_dumps_safe(preferences or {}, default={})
        history_json = _json_dumps_safe([], default=[])

        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
                exists = await cur.fetchone()
                await cur.close()
                if exists:
                    return {"ok": False, "error": "user already exists", "user_id": user_id}

                # Check if legacy 'data' column exists
                existing_columns = await self._get_existing_columns(db)
                if "data" in existing_columns:
                    # Legacy schema with 'data' column
                    await db.execute(
                        """
                        INSERT INTO users (user_id, name, email, phone, preferences, interaction_history, created_at, updated_at, data)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (user_id, name, email, phone, prefs_json, history_json, now, now, "{}"),
                    )
                else:
                    # New schema without 'data' column
                    await db.execute(
                        """
                        INSERT INTO users (user_id, name, email, phone, preferences, interaction_history, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (user_id, name, email, phone, prefs_json, history_json, now, now),
                    )
                await db.commit()

            return await self.get_user_info(user_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("CRM store_user_info failed for %s: %s", user_id, exc)
            return {"ok": False, "error": "failed to store user info", "user_id": user_id}

    async def update_user_info(self, user_id: str, field: str, value: Any) -> Dict[str, Any]:
        """
        Update one field for an existing user.
        If field == 'interaction_history' then append a string value to the JSON list.
        """
        if not user_id or not str(user_id).strip():
            return {"ok": False, "error": "user_id is required"}
        if not field or not str(field).strip():
            return {"ok": False, "error": "field is required"}

        allowed_fields = {"name", "email", "phone", "preferences", "interaction_history"}
        if field not in allowed_fields:
            return {"ok": False, "error": f"field not allowed: {field}", "allowed_fields": sorted(allowed_fields)}

        await self.init_db()
        now = _utc_now_iso()

        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute(
                    "SELECT preferences, interaction_history FROM users WHERE user_id = ?",
                    (user_id,),
                )
                row = await cur.fetchone()
                await cur.close()

                if not row:
                    # Upsert behavior: create a placeholder profile so first-time
                    # "update_*" calls (e.g., email/phone capture) do not fail.
                    created = await self.store_user_info(
                        user_id=user_id,
                        name="",
                        email="",
                        phone="",
                        preferences={},
                    )
                    if not created.get("ok"):
                        return {
                            "ok": False,
                            "error": str(created.get("error") or "failed to create user before update"),
                            "user_id": user_id,
                        }
                    cur = await db.execute(
                        "SELECT preferences, interaction_history FROM users WHERE user_id = ?",
                        (user_id,),
                    )
                    row = await cur.fetchone()
                    await cur.close()
                    if not row:
                        return {"ok": False, "error": "not found after create", "user_id": user_id}

                if field == "preferences":
                    current = _json_loads_safe(row["preferences"], default={})
                    if isinstance(value, dict):
                        current.update(value)
                    else:
                        return {"ok": False, "error": "preferences value must be an object/dict"}
                    new_value = _json_dumps_safe(current, default={})
                    await db.execute(
                        "UPDATE users SET preferences = ?, updated_at = ? WHERE user_id = ?",
                        (new_value, now, user_id),
                    )

                elif field == "interaction_history":
                    current_hist = _json_loads_safe(row["interaction_history"], default=[])
                    if not isinstance(current_hist, list):
                        current_hist = []
                    current_hist.append("" if value is None else str(value))
                    new_value = _json_dumps_safe(current_hist, default=[])
                    await db.execute(
                        "UPDATE users SET interaction_history = ?, updated_at = ? WHERE user_id = ?",
                        (new_value, now, user_id),
                    )

                else:
                    await db.execute(
                        f"UPDATE users SET {field} = ?, updated_at = ? WHERE user_id = ?",
                        (None if value is None else str(value), now, user_id),
                    )

                await db.commit()

            return await self.get_user_info(user_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("CRM update_user_info failed for %s (%s): %s", user_id, field, exc)
            return {"ok": False, "error": "failed to update user info", "user_id": user_id, "field": field}

    async def append_interaction(self, user_id: str, message: str) -> None:
        """
        Convenience wrapper used by the websocket routes: append to interaction_history.
        This is intentionally fire-and-forget (best effort).
        """
        try:
            await self.update_user_info(user_id, "interaction_history", message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("CRM append_interaction failed (non-fatal): %s", exc)

    async def get_system_prompt_with_context(self, user_id: str, base_system_prompt: Optional[str] = None) -> str:
        """
        Return a personalized system prompt string.

        The returned string is safe to use as a full system prompt override:
        - If base_system_prompt is provided, it is preserved verbatim and the
          CRM context is appended.
        - If not provided, only the CRM context block is returned.
        """
        crm = await self.get_user_info(user_id)

        base = (base_system_prompt or "").strip()
        header = base + ("\n\n" if base else "")

        if not crm.get("ok"):
            # Fail open: do not block the assistant; just skip personalization.
            return (header + "CURRENT GUEST CONTEXT:\n- CRM: unavailable\n").strip()

        user = (crm.get("user") or {}) if isinstance(crm.get("user"), dict) else {}
        if crm.get("message") == "not found":
            return (header + f"CURRENT GUEST CONTEXT:\n- user_id: {user_id}\n- CRM: no stored profile\n").strip()

        name = user.get("name")
        email = user.get("email")
        phone = user.get("phone")
        prefs = user.get("preferences") if isinstance(user.get("preferences"), dict) else {}
        hist = user.get("interaction_history") if isinstance(user.get("interaction_history"), list) else []

        lines: List[str] = [
            "CURRENT GUEST CONTEXT:",
            "- The frontend provided a stable user_id on reconnect.",
            "- Use this profile to personalize responses and avoid asking the guest to re-introduce themselves.",
            "- If you greet, do it only once and you may use the guest's name if known.",
        ]
        lines.append(f"- user_id: {user_id}")
        if name:
            lines.append(f"- name: {name}")
        if email:
            lines.append(f"- email: {email}")
        if phone:
            lines.append(f"- phone: {phone}")
        if prefs:
            lines.append("- preferences:")
            for k, v in list(prefs.items())[:25]:
                lines.append(f"  - {k}: {v}")
        if hist:
            lines.append("- recent_interactions:")
            for item in hist[-10:]:
                lines.append(f"  - {item}")
        lines.append("")

        return (header + "\n".join(lines)).strip()


# ---- LLM function-calling tool schemas (strict JSON Schema) ----

CRM_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "get_user_info",
        "description": "Fetch a user's CRM profile by user_id. Returns the full record or a not-found message.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "user_id": {"type": "string", "description": "Unique user identifier."},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "store_user_info",
        "description": "Create a new user profile in CRM. Errors if user already exists.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "user_id": {"type": "string", "description": "Unique user identifier."},
                "name": {"type": "string", "description": "User's name."},
                "email": {"type": "string", "description": "User's email address."},
                "phone": {"type": "string", "description": "User's phone number."},
                "preferences": {
                    "type": "object",
                    "description": "User preferences as a JSON object (will be stored as JSON string).",
                },
            },
            "required": ["user_id", "name", "email", "phone", "preferences"],
        },
    },
    {
        "name": "update_user_info",
        "description": "Update one field of an existing user. If field is interaction_history, value is appended.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "user_id": {"type": "string", "description": "Unique user identifier."},
                "field": {
                    "type": "string",
                    "enum": ["name", "email", "phone", "preferences", "interaction_history"],
                    "description": "Field to update.",
                },
                "value": {
                    "description": "New value. For preferences must be an object; for interaction_history any value will be appended as string.",
                },
            },
            "required": ["user_id", "field", "value"],
        },
    },
]


# ---- Async tool function wrappers (for orchestrator) ----

async def get_user_info(user_id: str, *, crm: SQLiteCRM) -> Dict[str, Any]:
    return await crm.get_user_info(user_id)


async def store_user_info(
    user_id: str,
    name: str,
    email: str,
    phone: str,
    preferences: Dict[str, Any],
    *,
    crm: SQLiteCRM,
) -> Dict[str, Any]:
    return await crm.store_user_info(user_id, name=name, email=email, phone=phone, preferences=preferences)


async def update_user_info(user_id: str, field: str, value: Any, *, crm: SQLiteCRM) -> Dict[str, Any]:
    return await crm.update_user_info(user_id, field, value)


async def get_system_prompt_with_context(user_id: str, *, crm: SQLiteCRM, base_system_prompt: Optional[str] = None) -> str:
    return await crm.get_system_prompt_with_context(user_id, base_system_prompt=base_system_prompt)


# Backwards-compatible alias for existing imports.
CRMTool = SQLiteCRM
