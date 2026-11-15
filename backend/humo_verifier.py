import asyncio
from concurrent.futures import ThreadPoolExecutor
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

from .config import STORAGE_DIR
from .database import (
    claim_payment_transaction,
    get_settings,
    is_payment_tx_used,
    update_settings,
)

# Official Telegram Desktop public API credentials (same as telegram_humo_tool.py)
TELEGRAM_API_ID = 2040
TELEGRAM_API_HASH = "b18441a1ff607e10a989891a5462e627"

SESSION_STRING_FILE = STORAGE_DIR / "telegram_session_string.txt"

_TELETHON_LOCK = threading.Lock()
_PENDING_LOCK = threading.Lock()
_PENDING_LOGINS: dict[str, dict[str, Any]] = {}
_PENDING_TTL_SECONDS = 600


def _run_coro(coro):
    with _TELETHON_LOCK:
        try:
            asyncio.get_running_loop()
            in_running_loop = True
        except RuntimeError:
            in_running_loop = False
        if not in_running_loop:
            return asyncio.run(coro)
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()


def normalize_bot_username(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return "@HUMOcardbot"
    value = re.sub(r"^https?://t\.me/", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^t\.me/", "", value, flags=re.IGNORECASE)
    value = value.lstrip("@").split("?")[0].split("/")[0].strip()
    if not value:
        return "@HUMOcardbot"
    return f"@{value}"


def extract_card_last4(card_number: str) -> str:
    digits = re.sub(r"\D", "", card_number or "")
    if len(digits) >= 4:
        return digits[-4:]
    return ""


def get_saved_session_string() -> str:
    settings = get_settings()
    session_str = (settings.get("telegram_session_string") or "").strip()
    if session_str:
        return session_str
    if SESSION_STRING_FILE.exists():
        try:
            file_session = SESSION_STRING_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            file_session = ""
        if file_session:
            update_settings({"telegram_session_string": file_session})
            return file_session
    return ""


def save_session_string(
    session_str: str,
    account_name: Optional[str] = None,
    account_username: Optional[str] = None,
    account_phone: Optional[str] = None,
) -> None:
    cleaned = (session_str or "").strip()
    updates: dict[str, Any] = {"telegram_session_string": cleaned}
    if account_name is not None:
        updates["telegram_account_name"] = account_name
    if account_username is not None:
        updates["telegram_account_username"] = account_username
    if account_phone is not None:
        updates["telegram_account_phone"] = account_phone
    update_settings(updates)

    SESSION_STRING_FILE.parent.mkdir(parents=True, exist_ok=True)
    if cleaned:
        SESSION_STRING_FILE.write_text(cleaned, encoding="utf-8")
    elif SESSION_STRING_FILE.exists():
        try:
            SESSION_STRING_FILE.unlink()
        except OSError:
            SESSION_STRING_FILE.write_text("", encoding="utf-8")


def _parse_uzs_amount(raw_amount: str) -> int:
    compact = re.sub(r"\s+", "", raw_amount or "")
    if not compact:
        return 0
    if "," in compact:
        if re.match(r"^[\d.]+,\d{1,2}$", compact):
            int_part = compact.split(",")[0].replace(".", "")
        else:
            int_part = compact.replace(",", "").replace(".", "")
    elif re.match(r"^\d+\.\d{2}$", compact):
        int_part = compact.split(".")[0]
    else:
        int_part = compact.replace(".", "")

    digits = re.sub(r"\D", "", int_part)
    if not digits:
        return 0
    try:
        return int(digits)
    except ValueError:
        return 0


def _extract_callback_tx_id(buttons: Any) -> str:
    if not buttons:
        return ""
    for row in buttons:
        iterable = row if isinstance(row, (list, tuple)) else [row]
        for btn in iterable:
            raw_data = getattr(btn, "data", None)
            if raw_data is None and isinstance(btn, dict):
                raw_data = btn.get("data")
            if raw_data is None and isinstance(btn, str):
                raw_data = btn
            if isinstance(raw_data, bytes):
                raw_str = raw_data.decode("utf-8", errors="ignore")
            else:
                raw_str = str(raw_data or "")
            m = re.search(r"(?:^|[&?])id=([A-Za-z0-9_-]+)", raw_str)
            if m:
                return m.group(1)
    return ""


def parse_humo_topup_message(
    text: str,
    msg_id: int,
    msg_date: Any,
    buttons: Any = None,
) -> Optional[dict[str, Any]]:
    if not text or not text.strip():
        return None

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None

    header = lines[0]
    # Only accept incoming top-up notifications; never accept outgoing payments (➖, To'lov, Amaliyot, Списание)
    if "➖" in text:
        return None
    if any(word in header.lower() for word in ("to'lov", "amaliyot", "оплата", "списание")):
        return None
    if not (
        "to'ldirish" in header.lower()
        or "пополнение" in header.lower()
        or ("🎉" in header and "➕" in text)
    ):
        return None

    amt_match = re.search(r"➕\s*([0-9][0-9\s.,]*)\s*UZS", text, flags=re.IGNORECASE)
    if not amt_match:
        return None

    amount_uzs = _parse_uzs_amount(amt_match.group(1))
    if amount_uzs <= 0:
        return None

    card_match = re.search(r"\*([0-9]{4})", text)
    card_mask = f"*{card_match.group(1)}" if card_match else ""

    src_match = re.search(r"📍\s*(.+)", text)
    source = src_match.group(1).strip() if src_match else ""

    time_match = re.search(r"🕓\s*([0-9:\s.]+)", text)
    humo_time = time_match.group(1).strip() if time_match else ""

    cb_tx_id = _extract_callback_tx_id(buttons)
    tx_uid = f"humo_{cb_tx_id}" if cb_tx_id else f"tgmsg_{int(msg_id)}"

    msg_date_ts = 0
    msg_date_iso = ""
    if isinstance(msg_date, datetime):
        dt = msg_date if msg_date.tzinfo else msg_date.replace(tzinfo=timezone.utc)
        msg_date_ts = int(dt.timestamp())
        msg_date_iso = dt.astimezone(timezone.utc).isoformat()
    elif isinstance(msg_date, str) and msg_date.strip():
        try:
            dt = datetime.fromisoformat(msg_date.strip())
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            msg_date_ts = int(dt.timestamp())
            msg_date_iso = dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            msg_date_iso = msg_date.strip()
    elif isinstance(msg_date, (int, float)):
        msg_date_ts = int(msg_date)
        msg_date_iso = datetime.fromtimestamp(msg_date_ts, tz=timezone.utc).isoformat()

    return {
        "tx_uid": tx_uid,
        "msg_id": int(msg_id),
        "amount_uzs": amount_uzs,
        "card_mask": card_mask,
        "source": source,
        "humo_time": humo_time,
        "msg_date_ts": msg_date_ts,
        "msg_date_iso": msg_date_iso,
        "raw_text": text.strip(),
    }


def _format_user_display(me: Any) -> tuple[str, str, str]:
    first = (getattr(me, "first_name", None) or "").strip()
    last = (getattr(me, "last_name", None) or "").strip()
    full_name = f"{first} {last}".strip() or "Telegram User"
    username = (getattr(me, "username", None) or "").strip()
    phone = (getattr(me, "phone", None) or "").strip()
    if phone and not phone.startswith("+"):
        phone = f"+{phone}"
    return full_name, username, phone


def _prune_pending_logins() -> None:
    now = time.time()
    with _PENDING_LOCK:
        expired = [
            key
            for key, item in _PENDING_LOGINS.items()
            if now - float(item.get("created_at", 0)) > _PENDING_TTL_SECONDS
        ]
        for key in expired:
            _PENDING_LOGINS.pop(key, None)


def get_telegram_status(check_remote: bool = False) -> dict[str, Any]:
    settings = get_settings()
    bot_username = normalize_bot_username(settings.get("telegram_bot_username") or "@HUMOcardbot")
    session_str = get_saved_session_string()

    base = {
        "connected": bool(session_str),
        "bot_username": bot_username,
        "account_name": settings.get("telegram_account_name") or "",
        "account_username": settings.get("telegram_account_username") or "",
        "account_phone": settings.get("telegram_account_phone") or "",
        "error": "",
    }
    if not session_str or not check_remote:
        return base

    async def _check() -> dict[str, Any]:
        client = TelegramClient(
            StringSession(session_str),
            TELEGRAM_API_ID,
            TELEGRAM_API_HASH,
            connection_retries=2,
            timeout=10,
        )
        await client.connect()
        try:
            authorized = await client.is_user_authorized()
            if not authorized:
                return {**base, "connected": False, "error": "Telegram sessiyasi yaroqsiz yoki chiqib ketilgan."}
            me = await client.get_me()
            name, uname, phone = _format_user_display(me)
            refreshed = client.session.save()
            save_session_string(refreshed, name, uname, phone)
            return {
                "connected": True,
                "bot_username": bot_username,
                "account_name": name,
                "account_username": uname,
                "account_phone": phone,
                "error": "",
            }
        finally:
            await client.disconnect()

    try:
        return _run_coro(_check())
    except Exception as exc:
        return {**base, "connected": False, "error": str(exc)}


def _fetch_bot_messages_sync(bot_username: str, limit: int = 25) -> dict[str, Any]:
    session_str = get_saved_session_string()
    if not session_str:
        return {
            "connected": False,
            "error": "Telegram hisob ulanmagan.",
            "transactions": [],
            "bot_username": bot_username,
            "account": None,
        }

    async def _fetch() -> dict[str, Any]:
        client = TelegramClient(
            StringSession(session_str),
            TELEGRAM_API_ID,
            TELEGRAM_API_HASH,
            connection_retries=2,
            timeout=12,
        )
        await client.connect()
        try:
            if not await client.is_user_authorized():
                return {
                    "connected": False,
                    "error": "Telegram sessiyasi muddati tugagan. Qaytadan ulang.",
                    "transactions": [],
                    "bot_username": bot_username,
                    "account": None,
                }
            me = await client.get_me()
            name, uname, phone = _format_user_display(me)
            update_settings(
                {
                    "telegram_account_name": name,
                    "telegram_account_username": uname,
                    "telegram_account_phone": phone,
                }
            )
            entity = await client.get_entity(bot_username)
            messages = await client.get_messages(entity, limit=limit)
            parsed_items: list[dict[str, Any]] = []
            for msg in messages:
                parsed = parse_humo_topup_message(
                    getattr(msg, "raw_text", None) or getattr(msg, "message", "") or "",
                    msg_id=int(getattr(msg, "id", 0) or 0),
                    msg_date=getattr(msg, "date", None),
                    buttons=getattr(msg, "buttons", None),
                )
                if parsed:
                    parsed["used"] = is_payment_tx_used(parsed["tx_uid"])
                    parsed_items.append(parsed)

            return {
                "connected": True,
                "error": "",
                "bot_username": bot_username,
                "account": {
                    "name": name,
                    "username": uname,
                    "phone": phone,
                },
                "transactions": parsed_items,
            }
        finally:
            await client.disconnect()

    return _run_coro(_fetch())


def fetch_recent_humo_topups(limit: int = 20) -> dict[str, Any]:
    settings = get_settings()
    bot_username = normalize_bot_username(settings.get("telegram_bot_username") or "@HUMOcardbot")
    try:
        return _fetch_bot_messages_sync(bot_username, limit=limit)
    except Exception as exc:
        return {
            "connected": False,
            "error": f"Telegram botdan xabarlarni olishda xato: {exc}",
            "bot_username": bot_username,
            "account": None,
            "transactions": [],
        }


def verify_and_claim_humo_payment(
    job_id: str,
    expected_amount_uzs: int,
    payment_created_ts: int,
    attempts: int = 3,
    delay_seconds: float = 2.0,
) -> dict[str, Any]:
    settings = get_settings()
    bot_username = normalize_bot_username(settings.get("telegram_bot_username") or "@HUMOcardbot")
    card_last4 = extract_card_last4(settings.get("payment_card_number") or "")
    session_str = get_saved_session_string()
    if not session_str:
        return {
            "verified": False,
            "error_code": "TELEGRAM_NOT_CONNECTED",
            "message": "To'lovni tekshirish uchun admin Telegram hisobi ulanmagan.",
        }

    # Allow 30s grace before order creation for minor clock skew, but never claim stale txs older than 10 minutes
    now_ts = int(time.time())
    min_ts = max(0, int(payment_created_ts) - 30, now_ts - 600)
    max_ts = now_ts + 120
    last_error = ""

    for attempt in range(max(1, attempts)):
        try:
            fetched = _fetch_bot_messages_sync(bot_username, limit=25)
        except Exception as exc:
            last_error = str(exc)
            fetched = {"connected": False, "error": last_error, "transactions": []}

        if not fetched.get("connected"):
            if attempt + 1 < attempts:
                time.sleep(delay_seconds)
                continue
            return {
                "verified": False,
                "error_code": "TELEGRAM_ERROR",
                "message": fetched.get("error") or "Telegram bilan bog'lanishda xato yuz berdi.",
            }

        transactions: list[dict[str, Any]] = fetched.get("transactions") or []
        candidates = [
            tx
            for tx in transactions
            if min_ts <= int(tx.get("msg_date_ts") or 0) <= max_ts
            and int(tx.get("amount_uzs") or 0) == int(expected_amount_uzs)
        ]
        # Prefer card mask match when card_last4 is configured
        if card_last4:
            filtered = [
                tx
                for tx in candidates
                if not tx.get("card_mask") or tx["card_mask"].endswith(card_last4)
            ]
            candidates = filtered

        # Claim oldest unclaimed candidate inside the window (FIFO fairness)
        candidates.sort(key=lambda item: (int(item.get("msg_date_ts") or 0), int(item.get("msg_id") or 0)))

        for tx in candidates:
            claimed = claim_payment_transaction(
                tx_uid=tx["tx_uid"],
                job_id=job_id,
                amount_uzs=int(tx["amount_uzs"]),
                card_mask=str(tx.get("card_mask") or ""),
                msg_date=str(tx.get("msg_date_iso") or ""),
                raw_text=str(tx.get("raw_text") or ""),
            )
            if claimed:
                return {
                    "verified": True,
                    "transaction": tx,
                    "message": (
                        f"To'lov tasdiqlandi! {tx['amount_uzs']} UZS ({tx.get('card_mask') or 'HUMO'}) "
                        f"qabul qilindi."
                    ),
                }

        if attempt + 1 < attempts:
            time.sleep(delay_seconds)

    return {
        "verified": False,
        "error_code": "PAYMENT_NOT_FOUND",
        "message": (
            f"{bot_username} orqali {expected_amount_uzs} UZS miqdorida yangi to'lov topilmadi. "
            "Iltimos, to'lovni to'liq summada amalga oshiring va 5 soniyadan so'ng qayta tekshiring."
        ),
    }


def admin_send_telegram_code(phone: str, bot_username: str = "@HUMOcardbot") -> dict[str, Any]:
    _prune_pending_logins()
    normalized_phone = re.sub(r"[^\d+]", "", (phone or "").strip())
    if normalized_phone and not normalized_phone.startswith("+"):
        normalized_phone = f"+{normalized_phone}"
    if len(re.sub(r"\D", "", normalized_phone)) < 9:
        raise ValueError("Telefon raqam formati noto'g'ri. Masalan: +998901234567")

    cleaned_bot = normalize_bot_username(bot_username)

    async def _send() -> dict[str, Any]:
        client = TelegramClient(
            StringSession(),
            TELEGRAM_API_ID,
            TELEGRAM_API_HASH,
            connection_retries=2,
            timeout=15,
        )
        await client.connect()
        try:
            sent = await client.send_code_request(normalized_phone)
            pending_session = client.session.save()
            return {
                "phone_code_hash": sent.phone_code_hash,
                "pending_session": pending_session,
            }
        finally:
            await client.disconnect()

    try:
        res = _run_coro(_send())
    except PhoneNumberInvalidError:
        raise ValueError("Telegram ushbu telefon raqamini qabul qilmadi.")
    except FloodWaitError as exc:
        raise ValueError(f"Telegram cheklovi: {exc.seconds} soniyadan so'ng qayta urinib ko'ring.")

    auth_token = uuid.uuid4().hex
    with _PENDING_LOCK:
        _PENDING_LOGINS[auth_token] = {
            "phone": normalized_phone,
            "bot_username": cleaned_bot,
            "phone_code_hash": res["phone_code_hash"],
            "pending_session": res["pending_session"],
            "needs_password": False,
            "created_at": time.time(),
        }

    return {
        "auth_token": auth_token,
        "phone": normalized_phone,
        "bot_username": cleaned_bot,
        "message": f"Tasdiqlash kodi {normalized_phone} raqamiga Telegram orqali yuborildi.",
    }


def admin_verify_telegram_code(
    auth_token: str,
    code: str = "",
    password: str = "",
) -> dict[str, Any]:
    _prune_pending_logins()
    with _PENDING_LOCK:
        pending = _PENDING_LOGINS.get(auth_token)
    if not pending:
        raise ValueError("Tasdiqlash sessiyasi topilmadi yoki muddati tugagan. Kodni qaytadan yuboring.")

    phone = pending["phone"]
    phone_code_hash = pending["phone_code_hash"]
    pending_session = pending["pending_session"]
    needs_password_already = bool(pending.get("needs_password"))
    cleaned_code = (code or "").strip()
    cleaned_password = password or ""

    if not needs_password_already and not cleaned_code:
        raise ValueError("Telegramdan kelgan tasdiqlash kodini kiriting.")
    if needs_password_already and not cleaned_password:
        raise ValueError("Ikki bosqichli himoya (2FA) parolini kiriting.")

    async def _verify() -> dict[str, Any]:
        client = TelegramClient(
            StringSession(pending_session),
            TELEGRAM_API_ID,
            TELEGRAM_API_HASH,
            connection_retries=2,
            timeout=15,
        )
        await client.connect()
        try:
            if needs_password_already:
                await client.sign_in(password=cleaned_password)
            else:
                try:
                    await client.sign_in(
                        phone=phone,
                        code=cleaned_code,
                        phone_code_hash=phone_code_hash,
                    )
                except SessionPasswordNeededError:
                    if cleaned_password:
                        await client.sign_in(password=cleaned_password)
                    else:
                        return {
                            "status": "PASSWORD_REQUIRED",
                            "updated_session": client.session.save(),
                        }

            me = await client.get_me()
            final_session = client.session.save()
            name, uname, real_phone = _format_user_display(me)
            return {
                "status": "CONNECTED",
                "final_session": final_session,
                "name": name,
                "username": uname,
                "phone": real_phone or phone,
            }
        finally:
            await client.disconnect()

    try:
        res = _run_coro(_verify())
    except PhoneCodeInvalidError:
        raise ValueError("Kiritilgan tasdiqlash kodi noto'g'ri.")
    except PhoneCodeExpiredError:
        with _PENDING_LOCK:
            _PENDING_LOGINS.pop(auth_token, None)
        raise ValueError("Tasdiqlash kodi eskirgan. Kodni qaytadan so'rang.")
    except PasswordHashInvalidError:
        raise ValueError("Ikki bosqichli himoya (2FA) paroli noto'g'ri.")
    except FloodWaitError as exc:
        raise ValueError(f"Telegram cheklovi: {exc.seconds} soniyadan so'ng urinib ko'ring.")

    if res["status"] == "PASSWORD_REQUIRED":
        with _PENDING_LOCK:
            if auth_token in _PENDING_LOGINS:
                _PENDING_LOGINS[auth_token]["pending_session"] = res["updated_session"]
                _PENDING_LOGINS[auth_token]["needs_password"] = True
        return {
            "connected": False,
            "needs_password": True,
            "message": "Hisobda 2-bosqichli parol (2FA) o'rnatilgan. Iltimos, parolni kiriting.",
        }

    with _PENDING_LOCK:
        _PENDING_LOGINS.pop(auth_token, None)

    update_settings({"telegram_bot_username": pending["bot_username"]})
    save_session_string(
        res["final_session"],
        account_name=res["name"],
        account_username=res["username"],
        account_phone=res["phone"],
    )

    return {
        "connected": True,
        "needs_password": False,
        "bot_username": pending["bot_username"],
        "account_name": res["name"],
        "account_username": res["username"],
        "account_phone": res["phone"],
        "message": f"Telegram hisob ({res['name']}) muvaffaqiyatli ulandi!",
    }


def admin_disconnect_telegram() -> dict[str, Any]:
    save_session_string(
        "",
        account_name="",
        account_username="",
        account_phone="",
    )
    return {
        "connected": False,
        "message": "Telegram hisobi uzildi va sessiya tozalandi.",
    }
