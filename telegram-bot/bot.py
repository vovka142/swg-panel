import base64
import io
import zipfile
import logging
import os
import re
import secrets
from typing import Any

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("swg-telegram")
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://management-api:8090").rstrip("/")
GATEWAY_KEY = os.environ["GATEWAY_API_KEY"]
ADMIN_IDS = {int(x.strip()) for x in os.environ["TELEGRAM_ADMIN_IDS"].split(",") if x.strip()}
HTTP = httpx.AsyncClient(base_url=GATEWAY_URL, timeout=float(os.getenv("HTTP_TIMEOUT", "30")),
                         headers={"Authorization": f"Bearer {GATEWAY_KEY}"})

def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")

def allowed(update: Update) -> bool:
    return bool(update.effective_user and update.effective_chat
                and update.effective_chat.type == ChatType.PRIVATE
                and update.effective_user.id in ADMIN_IDS)

async def api(method: str, path: str, *, params=None, payload=None) -> dict[str, Any]:
    r = await HTTP.request(method, path, params=params, json=payload)
    try:
        data = r.json()
    except ValueError:
        data = {"detail": r.text[:500]}
    if r.is_error:
        raise RuntimeError(f"Gateway HTTP {r.status_code}: {data.get('detail', data)}")
    if isinstance(data, dict) and data.get("ok") is False:
        raise RuntimeError(str(data.get("error") or data))
    return data

async def state_data():
    result = await api("GET", "/v1/state")
    return result.get("data") or {}

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Пользователи", callback_data="menu:users")],
        [InlineKeyboardButton("➕ Создать пользователя", callback_data="menu:newuser")],
        [InlineKeyboardButton("📱 Все устройства", callback_data="menu:peers")],
        [InlineKeyboardButton("ℹ️ Состояние панели", callback_data="menu:state")],
    ])

async def fail(message, exc):
    log.error("Bot operation failed: %s", exc)
    await message.reply_text("Ошибка: " + str(exc)[:700])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await update.effective_message.reply_text("Доступ запрещён.")
    context.user_data.clear()
    await update.effective_message.reply_text(
        f"SWG Panel · управление\nВаш Telegram ID: {update.effective_user.id}", reply_markup=menu())

async def users_list(message):
    data = await api("GET", "/v1/users")
    users = data.get("users") or []
    rows = []
    for u in users[:80]:
        uid = str(u.get("id") or "")
        if uid:
            rows.append([InlineKeyboardButton(
                ("⛔ " if u.get("disabled") else "🟢 ") + str(u.get("name") or uid)[:52],
                callback_data="user:" + uid)])
    rows.append([InlineKeyboardButton("➕ Создать пользователя", callback_data="menu:newuser")])
    rows.append([InlineKeyboardButton("⬅️ Меню", callback_data="menu:home")])
    await message.reply_text(f"Пользователи: {len(users)}", reply_markup=InlineKeyboardMarkup(rows))

async def user_view(message, uid):
    d = await state_data()
    roster = d.get("roster") or {}
    u = (roster.get("users") or {}).get(uid)
    if not u:
        return await message.reply_text("Пользователь не найден.")
    peers = [p for p in (roster.get("peers") or {}).values() if p.get("user_id") == uid]
    rows = [
        [InlineKeyboardButton("📱 Устройства", callback_data="u:peers:" + uid)],
        [InlineKeyboardButton("✏️ Изменить имя", callback_data="u:edit:" + uid)],
        [InlineKeyboardButton("➕ Добавить устройство", callback_data="u:addpeer:" + uid)],
        [InlineKeyboardButton("🔓 Разблокировать" if u.get("disabled") else "⛔ Заблокировать",
                              callback_data=("u:unblock:" if u.get("disabled") else "u:block:") + uid)],
        [InlineKeyboardButton("🗑 Удалить пользователя", callback_data="u:delconfirm:" + uid)],
        [InlineKeyboardButton("⬅️ К пользователям", callback_data="menu:users")],
    ]
    await message.reply_text(
        f"👤 {u.get('name') or uid}\nID: {uid}\nСтатус: {'ЗАБЛОКИРОВАН' if u.get('disabled') else 'активен'}"
        f"\nУстройств: {len(peers)}\nТег: {u.get('tag') or '—'}\nЗаметка: {u.get('note') or '—'}",
        reply_markup=InlineKeyboardMarkup(rows))

async def user_peers(message, uid):
    data = await api("GET", "/v1/peers", params={"user_id": uid})
    peers = data.get("peers") or []
    rows = []
    for p in peers[:80]:
        pid = str(p.get("id") or "")
        if pid:
            rows.append([InlineKeyboardButton(
                ("⛔ " if p.get("disabled") else "📱 ") + str(p.get("title") or pid[:12])[:48],
                callback_data="peer:" + pid)])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="user:" + uid)])
    await message.reply_text(f"Устройства: {len(peers)}", reply_markup=InlineKeyboardMarkup(rows))

async def peers_list(message):
    data = await api("GET", "/v1/peers")
    peers = data.get("peers") or []
    rows = []
    for p in peers[:80]:
        pid = str(p.get("id") or "")
        if pid:
            rows.append([InlineKeyboardButton(
                ("⛔ " if p.get("disabled") else "📱 ") + str(p.get("title") or pid[:12])[:48],
                callback_data="peer:" + pid)])
    rows.append([InlineKeyboardButton("⬅️ Меню", callback_data="menu:home")])
    await message.reply_text(f"Устройства: {len(peers)}", reply_markup=InlineKeyboardMarkup(rows))

async def peer_view(message, pid):
    d = await state_data()
    roster = d.get("roster") or {}
    p = (roster.get("peers") or {}).get(pid)
    if not p:
        return await message.reply_text("Устройство не найдено.")
    uid = p.get("user_id")
    u = (roster.get("users") or {}).get(uid, {}) if uid else {}
    targets = "\n".join(
        f"• {t.get('node')} / {t.get('iface')} · {t.get('ip') or 'IP при подключении'}"
        for t in (p.get("targets") or [])) or "—"
    rows = [
        [InlineKeyboardButton("🔓 Разблокировать" if p.get("disabled") else "⛔ Заблокировать",
                              callback_data=("p:unblock:" if p.get("disabled") else "p:block:") + pid)],
        [InlineKeyboardButton("♻️ Перевыпустить конфиг", callback_data="p:reissueconfirm:" + pid)],
        [InlineKeyboardButton("♻️ Перевыпустить конфиг", callback_data="p:reissueconfirm:" + pid)],
        [InlineKeyboardButton("🗑 Удалить устройство", callback_data="p:delconfirm:" + pid)],
        [InlineKeyboardButton("⬅️ Назад", callback_data=("user:" + uid) if uid else "menu:peers")],
    ]
    await message.reply_text(
        f"📱 {p.get('title') or pid}\nID: {pid}\nПользователь: {u.get('name') or 'не назначен'}"
        f"\nСтатус: {'ЗАБЛОКИРОВАНО' if p.get('disabled') else 'активно'}"
        f"\nПубличный ключ: {p.get('pubkey') or '—'}\nРазмещение:\n{targets}",
        reply_markup=InlineKeyboardMarkup(rows))

async def peer_wizard(message, context, uid):
    d = await state_data()
    nodes = d.get("nodes") or []
    describe = d.get("describe") or {}
    choices = []
    for n in nodes:
        nid = str(n.get("id") or "")
        for iface, meta in (describe.get(nid) or {}).items():
            if iface.startswith("swg_"):
                continue
            kind = "awg" if meta.get("awg_params") else str(meta.get("tool") or "wg")
            if kind in {"wg", "awg"}:
                choices.append({"node": nid, "iface": iface, "kind": kind, "meta": meta,
                                "node_name": n.get("name") or n.get("hostname") or nid})
    if not choices:
        return await message.reply_text("Не найдено WG/AWG интерфейсов. WDTT/CSQTT требуют отдельного сценария.")
    context.user_data["peer_user_id"] = uid
    context.user_data["iface_choices"] = choices
    rows = [[InlineKeyboardButton(
        f"{c['node_name']} · {c['iface']} ({c['kind'].upper()})"[:60], callback_data=f"if:{i}")]
        for i, c in enumerate(choices[:90])]
    rows.append([InlineKeyboardButton("Отмена", callback_data="menu:home")])
    await message.reply_text("Выберите узел и интерфейс:", reply_markup=InlineKeyboardMarkup(rows))

def build_conf(meta, priv, psk, ip, peer_overrides=None, target_overrides=None):
    awg = meta.get("awg_params") or {}
    overrides = {**(peer_overrides or {}), **(target_overrides or {})}
    lines = ["[Interface]", f"PrivateKey = {priv}", f"Address = {ip}/32"]
    dns = overrides.get("dns", meta.get("dns") or [])
    if dns:
        lines.append("DNS = " + ", ".join(map(str, dns)))
    lines.append(f"MTU = {overrides.get('mtu') or meta.get('mtu') or 1280}")
    order = ["Jc","Jmin","Jmax","S1","S2","S3","S4","H1","H2","H3","H4","I1","I2","I3","I4","I5",
             "HeaderProtectionKey","RandomTrailers","ContentPaddingAddition","RekeyAfterTime","RekeyTimeout",
             "RejectAfterTime","KeepaliveTimeout","MaxHandshakeAttempts","DisableCookies"]
    g31 = bool(str(awg.get("HeaderProtectionKey") or "").strip())
    for i, key in enumerate(order):
        value = awg.get(key)
        if value is None or (i >= 15 and (not g31 or key == "DisableCookies")):
            continue
        if key == "RandomTrailers":
            if str(value).strip().lower() not in {"0", "off"}:
                lines.append("RandomTrailers = 1")
        else:
            lines.append(f"{key} = {value}")
    lines += ["", "[Peer]", f"PublicKey = {meta.get('public_key') or ''}", f"PresharedKey = {psk}",
              "AllowedIPs = " + str(overrides.get("allowed") or "0.0.0.0/0, ::/0"), f"Endpoint = {meta.get('endpoint') or ''}"]
    keepalive = overrides.get("keepalive", meta.get("keepalive") if meta.get("keepalive") is not None else 25)
    if g31 and str(keepalive).isdigit() and int(keepalive) > 0:
        keepalive = f"{keepalive}-{int(keepalive)+10}"
    lines.append(f"PersistentKeepalive = {keepalive}")
    return "\n".join(lines) + "\n"

async def create_peer(message, context, index, title):
    choices = context.user_data.get("iface_choices") or []
    if index < 0 or index >= len(choices):
        return await message.reply_text("Выбор устарел. Начните добавление устройства заново.")
    c = choices[index]
    uid = context.user_data.get("peer_user_id")
    await message.reply_text("Получаю свободный IP и создаю устройство…")
    try:
        if not c["meta"].get("public_key") or not c["meta"].get("endpoint"):
            raise RuntimeError("У интерфейса нет публичного ключа сервера или endpoint")
        alloc = await api("GET", "/v1/next-ip", params={"nodes": c["node"], "iface": c["iface"]})
        ip = str((alloc.get("data") or {}).get("next_ip") or "").split("/")[0]
        if not ip:
            raise RuntimeError("Панель не вернула свободный IP")
        private = X25519PrivateKey.generate()
        priv_raw = private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        pub_raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        priv, pub = b64(priv_raw), b64(pub_raw)
        psk = b64(secrets.token_bytes(32))
        conf = build_conf(c["meta"], priv, psk, ip)
        payload = {"user_id": uid, "title": title or "Telegram device", "pubkey": pub, "psk": psk,
                   "targets": [{"node": c["node"], "iface": c["iface"], "ip": ip, "type": c["kind"]}]}
        result = await api("POST", "/v1/peers", payload=payload)
        pid = (result.get("data") or {}).get("id")
        if not pid:
            raise RuntimeError("Панель не вернула ID устройства")
        try:
            filename = f"swg-{re.sub(r'[^A-Za-z0-9_.-]+', '_', c['iface'])}-{ip.replace('.', '-')}.conf"
            await message.reply_document(document=conf.encode(), filename=filename,
                caption=f"Устройство создано.\nIP: {ip}\nИнтерфейс: {c['iface']}\nФайл содержит приватный ключ — не пересылайте его.")
        except Exception:
            await api("DELETE", f"/v1/peers/{pid}")
            raise
        await message.reply_text("Готово. Устройство добавлено в панель.", reply_markup=menu())
    except Exception as exc:
        await fail(message, exc)
    finally:
        context.user_data.pop("iface_choices", None)
        context.user_data.pop("peer_user_id", None)

async def reissue_peer(message, pid):
    d = await state_data()
    roster = d.get("roster") or {}
    old = (roster.get("peers") or {}).get(pid)
    if not old:
        return await message.reply_text("Устройство не найдено.")
    targets = old.get("targets") or []
    if not targets:
        raise RuntimeError("У устройства нет назначенных интерфейсов")
    private = X25519PrivateKey.generate()
    priv_raw = private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub_raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    priv, pub = b64(priv_raw), b64(pub_raw)
    psk = b64(secrets.token_bytes(32))
    describe = d.get("describe") or {}
    new_targets, configs = [], []
    for t in targets:
        node, iface = str(t.get("node") or ""), str(t.get("iface") or "")
        kind = str(t.get("type") or "wg")
        if kind in {"wdtt", "csqtt"}:
            raise RuntimeError("WDTT/CSQTT credentials are not WireGuard configs; this device cannot be reissued by this flow")
        meta = (describe.get(node) or {}).get(iface)
        if not meta or not meta.get("public_key") or not meta.get("endpoint"):
            raise RuntimeError(f"Нет актуальных параметров узла для {node}/{iface}")
        alloc = await api("GET", "/v1/next-ip", params={"nodes": node, "iface": iface})
        ip = str((alloc.get("data") or {}).get("next_ip") or "").split("/")[0]
        if not ip:
            raise RuntimeError(f"Не удалось получить свободный IP для {node}/{iface}")
        new_targets.append({
            "node": node, "iface": iface, "ip": ip, "type": kind,
            **({"overrides": t["overrides"]} if t.get("overrides") else {}),
        })
        configs.append((f"{iface}-{ip.replace('.', '-')}.conf",
                        build_conf(meta, priv, psk, ip, old.get("overrides"), t.get("overrides"))))
    payload = {
        "user_id": old.get("user_id"), "title": old.get("title") or "Reissued device",
        "pubkey": pub, "psk": psk, "targets": new_targets,
        **({"overrides": old["overrides"]} if old.get("overrides") else {}),
    }
    created = await api("POST", "/v1/peers", payload=payload)
    new_id = (created.get("data") or {}).get("id")
    if not new_id:
        raise RuntimeError("Панель не вернула ID нового устройства")
    try:
        if len(configs) == 1:
            filename, conf = configs[0]
            await message.reply_document(document=conf.encode(), filename=filename,
                caption="Новый конфиг готов. После получения старое устройство будет отключено.")
        else:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
                for filename, conf in configs:
                    archive.writestr(filename, conf)
            buf.seek(0)
            await message.reply_document(document=buf, filename="swg-configs.zip",
                caption="Новые конфиги для всех размещений устройства. После получения старое устройство будет отключено.")
    except Exception:
        await api("DELETE", f"/v1/peers/{new_id}")
        raise
    try:
        await api("DELETE", f"/v1/peers/{pid}")
        await message.reply_text("Конфиг перевыпущен. Старое устройство удалено; используйте новый файл.")
    except Exception as exc:
        await message.reply_text(f"Новый конфиг отправлен, но старое устройство не удалось удалить: {exc}. Удалите его вручную.")

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not allowed(update):
        return await q.answer("Доступ запрещён", show_alert=True)
    await q.answer()
    data = q.data or ""
    try:
        if data == "menu:home":
            return await q.message.reply_text("SWG Panel", reply_markup=menu())
        if data == "menu:users":
            return await users_list(q.message)
        if data == "menu:newuser":
            context.user_data["flow"] = "new_user"
            return await q.message.reply_text("Отправьте имя пользователя. Тег можно добавить через |\nНапример: Иван Петров | staff")
        if data == "menu:peers":
            return await peers_list(q.message)
        if data == "menu:state":
            d = await state_data()
            r = d.get("roster") or {}
            return await q.message.reply_text(
                f"Панель доступна.\nУзлов: {len(d.get('nodes') or [])}"
                f"\nПользователей: {len(r.get('users') or {})}\nУстройств: {len(r.get('peers') or {})}",
                reply_markup=menu())
        if data.startswith("user:"):
            return await user_view(q.message, data.split(":", 1)[1])
        if data.startswith("u:peers:"):
            return await user_peers(q.message, data.split(":", 2)[2])
        if data.startswith("u:edit:"):
            uid = data.split(":", 2)[2]
            context.user_data["flow"] = "edit_user"
            context.user_data["edit_user_id"] = uid
            return await q.message.reply_text("Отправьте новое имя пользователя.")
        if data.startswith("u:addpeer:"):
            return await peer_wizard(q.message, context, data.split(":", 2)[2])
        if data.startswith("u:block:") or data.startswith("u:unblock:"):
            action, uid = data.split(":", 2)[1:]
            await api("POST", f"/v1/users/{uid}/{action}")
            return await user_view(q.message, uid)
        if data.startswith("u:delconfirm:"):
            uid = data.split(":", 2)[2]
            return await q.message.reply_text("Удалить пользователя? Действие необратимо.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Да, удалить", callback_data="u:delete:" + uid),
                    InlineKeyboardButton("Отмена", callback_data="user:" + uid)]]))
        if data.startswith("u:delete:"):
            await api("DELETE", "/v1/users/" + data.split(":", 2)[2])
            return await q.message.reply_text("Пользователь удалён.", reply_markup=menu())
        if data.startswith("peer:"):
            return await peer_view(q.message, data.split(":", 1)[1])
        if data.startswith("p:block:") or data.startswith("p:unblock:"):
            action, pid = data.split(":", 2)[1:]
            await api("POST", f"/v1/peers/{pid}/{action}")
            return await peer_view(q.message, pid)
        if data.startswith("p:reissueconfirm:"):
            pid = data.split(":", 2)[2]
            return await q.message.reply_text("Выпустить новую пару ключей и новый конфиг? Старый конфиг перестанет работать после успешной доставки нового файла.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Да, перевыпустить", callback_data="p:reissue:" + pid),
                    InlineKeyboardButton("Отмена", callback_data="peer:" + pid)]]))
        if data.startswith("p:reissue:"):
            pid = data.split(":", 2)[2]
            return await reissue_peer(q.message, pid)
        if data.startswith("p:delconfirm:"):
            pid = data.split(":", 2)[2]
            return await q.message.reply_text("Удалить устройство со всех серверов?",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Да, удалить", callback_data="p:delete:" + pid),
                    InlineKeyboardButton("Отмена", callback_data="peer:" + pid)]]))
        if data.startswith("p:delete:"):
            await api("DELETE", "/v1/peers/" + data.split(":", 2)[2])
            return await q.message.reply_text("Устройство удалено.", reply_markup=menu())
        if data.startswith("if:"):
            context.user_data["peer_choice_index"] = int(data.split(":", 1)[1])
            context.user_data["flow"] = "peer_title"
            return await q.message.reply_text("Введите название устройства (например, iPhone или Laptop).")
    except Exception as exc:
        await fail(q.message, exc)

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await update.effective_message.reply_text("Доступ запрещён.")
    flow = context.user_data.get("flow")
    if flow == "peer_title":
        title = update.effective_message.text.strip()[:64]
        index = int(context.user_data.get("peer_choice_index", -1))
        context.user_data["flow"] = None
        return await create_peer(update.effective_message, context, index, title)
    if flow == "edit_user":
        uid = context.user_data.get("edit_user_id")
        name = update.effective_message.text.strip()[:64]
        if not name:
            return await update.effective_message.reply_text("Имя не может быть пустым.")
        await api("PATCH", f"/v1/users/{uid}", payload={"name": name})
        context.user_data["flow"] = None
        return await user_view(update.effective_message, uid)
    if flow != "new_user":
        return await update.effective_message.reply_text("Используйте кнопки меню или /start.", reply_markup=menu())
    parts = [x.strip() for x in update.effective_message.text.split("|", 1)]
    name = parts[0][:64]
    tag = parts[1][:32] if len(parts) > 1 else ""
    if not name:
        return await update.effective_message.reply_text("Имя не может быть пустым.")
    try:
        result = await api("POST", "/v1/users", payload={"name": name, "tag": tag, "note": ""})
        user = result.get("data") or {}
        context.user_data["flow"] = None
        await update.effective_message.reply_text(
            f"Пользователь создан: {user.get('name') or name}\nID: {user.get('id') or '—'}", reply_markup=menu())
    except Exception as exc:
        await fail(update.effective_message, exc)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await update.effective_message.reply_text("Доступ запрещён.")
    context.user_data.clear()
    await update.effective_message.reply_text("Отменено.", reply_markup=menu())

async def shutdown(app):
    await HTTP.aclose()

def main():
    if not ADMIN_IDS:
        raise RuntimeError("TELEGRAM_ADMIN_IDS must contain at least one numeric Telegram user ID")
    app = Application.builder().token(BOT_TOKEN).post_shutdown(shutdown).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
