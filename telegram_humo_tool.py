"""Telethon session initializer and @HUMOcardbot history inspector for TLG SmartPrint."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

SESSION_PATH = STORAGE_DIR / "telegram_humo"
STRING_SESSION_FILE = STORAGE_DIR / "telegram_session_string.txt"
AUTH_STATE_FILE = STORAGE_DIR / "telegram_auth_state.json"
ANALYSIS_OUTPUT_FILE = STORAGE_DIR / "humo_bot_analysis.json"

DEFAULT_API_ID = int(os.environ.get("TELEGRAM_API_ID", "2040"))
DEFAULT_API_HASH = os.environ.get(
    "TELEGRAM_API_HASH", "b18441a1ff607e10a989891a5462e627"
)

UZB_TZ = timezone(timedelta(hours=5))


def build_client() -> TelegramClient:
    """Create a configured Telethon client bound to the persistent SQLite session."""
    return TelegramClient(
        str(SESSION_PATH),
        DEFAULT_API_ID,
        DEFAULT_API_HASH,
        device_model="TLG SmartPrint Server",
        system_version="1.0",
        app_version="1.0.0",
        lang_code="uz",
        system_lang_code="uz",
    )


def save_string_session_backup(client: TelegramClient) -> str:
    """Persist an encrypted-portable StringSession copy next to the SQLite session."""
    try:
        sess_str = StringSession.save(client.session) or ""
        if sess_str:
            STRING_SESSION_FILE.write_text(sess_str, encoding="utf-8")
        return sess_str
    except Exception as exc:
        print(f"[WARN] StringSession zaxira nusxasini saqlab bo'lmadi: {exc}", flush=True)
        return ""


def _save_auth_state(phone: str, phone_code_hash: str) -> None:
    AUTH_STATE_FILE.write_text(
        json.dumps({"phone": phone, "phone_code_hash": phone_code_hash}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_auth_state() -> dict[str, str]:
    if not AUTH_STATE_FILE.exists():
        return {}
    try:
        data = json.loads(AUTH_STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _prompt_line(tag: str, message: str) -> str:
    print(f"[{tag}] {message}", flush=True)
    line = sys.stdin.readline()
    if not line:
        raise EOFError(f"Stdin yopildi ({tag} kutilayotgan edi).")
    return line.strip()


def _extract_buttons(msg: Any) -> list[list[dict[str, str]]]:
    rows: list[list[dict[str, str]]] = []
    if not getattr(msg, "buttons", None):
        return rows
    for row in msg.buttons:
        row_items: list[dict[str, str]] = []
        for btn in row:
            info: dict[str, str] = {"text": str(getattr(btn, "text", "") or "")}
            if getattr(btn, "url", None):
                info["url"] = str(btn.url)
            if getattr(btn, "data", None):
                try:
                    info["callback_data"] = btn.data.decode("utf-8", errors="replace")
                except Exception:
                    info["callback_data"] = repr(btn.data)
            row_items.append(info)
        if row_items:
            rows.append(row_items)
    return rows


def _analyze_messages(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize recurring keywords, currency formats, card masks, and timestamps in bot messages."""
    amount_samples: list[str] = []
    card_samples: list[str] = []
    emoji_prefixes: dict[str, int] = {}

    amount_re = re.compile(r"([+\-]?\s*\d[\d\s.,]{1,20})\s*(UZS|so['’`]?m|sum|сўм)", re.IGNORECASE)
    card_re = re.compile(r"(HUMO|UZCARD|9860|\*{2,}\d{4})", re.IGNORECASE)

    for item in messages:
        text = item.get("text") or ""
        if not text:
            continue
        first_line = text.splitlines()[0].strip()[:60]
        if first_line:
            emoji_prefixes[first_line] = emoji_prefixes.get(first_line, 0) + 1
        for m in amount_re.finditer(text):
            sample = m.group(0).strip()
            if sample not in amount_samples and len(amount_samples) < 25:
                amount_samples.append(sample)
        for m in card_re.finditer(text):
            c = m.group(0).strip()
            if c not in card_samples and len(card_samples) < 20:
                card_samples.append(c)

    return {
        "total_messages": len(messages),
        "incoming_count": sum(1 for m in messages if not m.get("out")),
        "outgoing_count": sum(1 for m in messages if m.get("out")),
        "amount_samples": amount_samples,
        "card_markers": card_samples,
        "top_first_lines": sorted(
            emoji_prefixes.items(), key=lambda kv: kv[1], reverse=True
        )[:15],
    }


async def inspect_humo_bot(
    client: TelegramClient,
    bot_username: str = "HUMOcardbot",
    limit: int = 100,
) -> dict[str, Any]:
    """Inspect @HUMOcardbot profile, keyboards, and recent message history."""
    me = await client.get_me()
    me_info = {
        "id": getattr(me, "id", None),
        "first_name": getattr(me, "first_name", ""),
        "last_name": getattr(me, "last_name", "") or "",
        "username": getattr(me, "username", "") or "",
        "phone": getattr(me, "phone", "") or "",
    }
    print(
        f"\n[ACCOUNT] Ulandi: {me_info['first_name']} (@{me_info['username'] or 'username_yoq'}, +{me_info['phone']})",
        flush=True,
    )

    entity = await client.get_entity(bot_username)
    bot_info = {
        "id": getattr(entity, "id", None),
        "title": getattr(entity, "first_name", "") or getattr(entity, "title", ""),
        "username": getattr(entity, "username", bot_username),
        "bot": bool(getattr(entity, "bot", False)),
    }
    print(
        f"[BOT] Topildi: {bot_info['title']} (@{bot_info['username']}, id={bot_info['id']})",
        flush=True,
    )

    raw_messages = await client.get_messages(entity, limit=limit)
    parsed_messages: list[dict[str, Any]] = []
    for msg in raw_messages:
        dt_utc = msg.date.astimezone(timezone.utc) if msg.date else None
        dt_uz = msg.date.astimezone(UZB_TZ) if msg.date else None
        parsed_messages.append(
            {
                "id": msg.id,
                "date_utc": dt_utc.isoformat() if dt_utc else "",
                "date_tashkent": dt_uz.strftime("%Y-%m-%d %H:%M:%S") if dt_uz else "",
                "out": bool(msg.out),
                "text": msg.raw_text or "",
                "buttons": _extract_buttons(msg),
                "media_type": type(msg.media).__name__ if msg.media else "",
            }
        )

    summary = _analyze_messages(parsed_messages)
    report = {
        "inspected_at": datetime.now(UZB_TZ).isoformat(),
        "account": me_info,
        "bot": bot_info,
        "summary": summary,
        "messages": parsed_messages,
    }
    ANALYSIS_OUTPUT_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        f"[ANALYSIS_SAVED] {ANALYSIS_OUTPUT_FILE} | Jami xabarlar: {summary['total_messages']} "
        f"(kiruvchi={summary['incoming_count']}, chiquvchi={summary['outgoing_count']})",
        flush=True,
    )
    print(f"[AMOUNT_SAMPLES] {summary['amount_samples'][:10]}", flush=True)
    print(f"[CARD_MARKERS] {summary['card_markers'][:10]}", flush=True)
    print("\n--- OXIRGI 30 TA XABAR (@HUMOcardbot) ---", flush=True)
    for item in parsed_messages[:30]:
        direction = "OUT ->" if item["out"] else "IN  <-"
        btn_str = f" | BUTTONS={item['buttons']}" if item["buttons"] else ""
        print(
            f"\n[{item['id']}] {item['date_tashkent']} | {direction}{btn_str}\n{item['text']}",
            flush=True,
        )
    print("\n--- TAHLIL TUGADI ---", flush=True)
    return report


async def run_interactive() -> int:
    client = build_client()
    await client.connect()
    try:
        if not await client.is_user_authorized():
            phone = _prompt_line("READY_FOR_PHONE", "Telefon raqamingizni kiriting (+998...):")
            if not phone.startswith("+"):
                phone = "+" + phone.lstrip()
            try:
                sent = await client.send_code_request(phone)
            except FloodWaitError as exc:
                print(f"[ERROR] Telegram cheklovi (FloodWait): {exc.seconds} soniya kuting.", flush=True)
                return 2
            _save_auth_state(phone, sent.phone_code_hash)
            print(f"[CODE_SENT] {phone} raqamiga Telegram tasdiqlash kodi yuborildi.", flush=True)

            for attempt in range(1, 4):
                code = _prompt_line("READY_FOR_CODE", "Telegramdan kelgan kodni kiriting:")
                code_clean = re.sub(r"\s+", "", code)
                try:
                    await client.sign_in(
                        phone=phone,
                        code=code_clean,
                        phone_code_hash=sent.phone_code_hash,
                    )
                    break
                except SessionPasswordNeededError:
                    for pwd_attempt in range(1, 4):
                        pwd = _prompt_line(
                            "READY_FOR_2FA",
                            "2-bosqichli parol (2FA) yoqilgan. Parolni kiriting:",
                        )
                        try:
                            await client.sign_in(password=pwd)
                            break
                        except PasswordHashInvalidError:
                            print(
                                f"[WARN] 2FA parol noto'g'ri ({pwd_attempt}/3). Qayta urinib ko'ring.",
                                flush=True,
                            )
                    else:
                        print("[ERROR] 2FA parol 3 marta noto'g'ri kiritildi.", flush=True)
                        return 3
                    break
                except PhoneCodeInvalidError:
                    print(
                        f"[WARN] Tasdiqlash kodi noto'g'ri ({attempt}/3). Qayta kiriting.",
                        flush=True,
                    )
                except PhoneCodeExpiredError:
                    print("[ERROR] Kod muddati tugadi. Jarayonni boshidan boshlang.", flush=True)
                    return 4
            else:
                print("[ERROR] Tasdiqlash kodi 3 marta noto'g'ri kiritildi.", flush=True)
                return 5

        if not await client.is_user_authorized():
            print("[ERROR] Avtorizatsiya yakunlanmadi.", flush=True)
            return 1

        save_string_session_backup(client)
        print(f"[SESSION_SAVED] Sessiya saqlandi: {SESSION_PATH}.session", flush=True)
        await inspect_humo_bot(client, limit=100)
        return 0
    finally:
        await client.disconnect()


async def run_send_code(phone: str) -> int:
    clean_phone = phone.strip()
    if not clean_phone.startswith("+"):
        clean_phone = "+" + clean_phone.lstrip()
    client = build_client()
    await client.connect()
    try:
        if await client.is_user_authorized():
            save_string_session_backup(client)
            print("[ALREADY_AUTHORIZED] Sessiya allaqachon faol.", flush=True)
            await inspect_humo_bot(client, limit=100)
            return 0
        sent = await client.send_code_request(clean_phone)
        _save_auth_state(clean_phone, sent.phone_code_hash)
        print(f"[CODE_SENT] Kod {clean_phone} raqamiga yuborildi.", flush=True)
        return 0
    finally:
        await client.disconnect()


async def run_sign_in(code: str, password: str = "") -> int:
    state = _load_auth_state()
    phone = state.get("phone", "")
    code_hash = state.get("phone_code_hash", "")
    if not phone or not code_hash:
        print("[ERROR] Avval send-code bilan telefon raqamiga kod yuboring.", flush=True)
        return 1

    client = build_client()
    await client.connect()
    try:
        try:
            await client.sign_in(
                phone=phone,
                code=re.sub(r"\s+", "", code),
                phone_code_hash=code_hash,
            )
        except SessionPasswordNeededError:
            if not password:
                print("[NEED_2FA] 2-bosqichli parol (2FA) talab qilinadi.", flush=True)
                return 10
            await client.sign_in(password=password)

        save_string_session_backup(client)
        print(f"[SESSION_SAVED] Sessiya saqlandi: {SESSION_PATH}.session", flush=True)
        await inspect_humo_bot(client, limit=100)
        return 0
    finally:
        await client.disconnect()


async def run_sign_in_2fa(password: str) -> int:
    client = build_client()
    await client.connect()
    try:
        if not await client.is_user_authorized():
            await client.sign_in(password=password)
        save_string_session_backup(client)
        print(f"[SESSION_SAVED] Sessiya saqlandi: {SESSION_PATH}.session", flush=True)
        await inspect_humo_bot(client, limit=100)
        return 0
    finally:
        await client.disconnect()


async def run_inspect(limit: int = 100) -> int:
    client = build_client()
    await client.connect()
    try:
        if not await client.is_user_authorized():
            print("[UNAUTHORIZED] Sessiya hali tasdiqlanmagan.", flush=True)
            return 1
        save_string_session_backup(client)
        await inspect_humo_bot(client, limit=limit)
        return 0
    finally:
        await client.disconnect()


def main() -> None:
    args = sys.argv[1:]
    cmd = args[0].lower() if args else "interactive"
    if cmd == "interactive":
        code = asyncio.run(run_interactive())
    elif cmd == "send-code" and len(args) >= 2:
        code = asyncio.run(run_send_code(args[1]))
    elif cmd == "sign-in" and len(args) >= 2:
        pwd = args[2] if len(args) >= 3 else ""
        code = asyncio.run(run_sign_in(args[1], password=pwd))
    elif cmd == "sign-in-2fa" and len(args) >= 2:
        code = asyncio.run(run_sign_in_2fa(args[1]))
    elif cmd == "inspect":
        lim = int(args[1]) if len(args) >= 2 else 100
        code = asyncio.run(run_inspect(limit=lim))
    else:
        print(
            "Foydalanish: python telegram_humo_tool.py [interactive | send-code <phone> | sign-in <code> [2fa] | sign-in-2fa <pwd> | inspect [limit]]"
        )
        code = 2
    sys.exit(code)


if __name__ == "__main__":
    main()
