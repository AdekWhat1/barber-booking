import html
from datetime import date, datetime, time, timedelta
import logging
import requests
from django.conf import settings
from django.utils import timezone

from bookings.models import Booking, Service, WorkingDay

logger = logging.getLogger(__name__)

WEEKDAYS_UK = [
    "Понеділок",
    "Вівторок",
    "Середа",
    "Четвер",
    "П'ятниця",
    "Субота",
    "Неділя",
]

WEEKDAYS_SHORT_UK = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]


def get_admin_keyboard():
    """Головне меню: чіткий поділ на записи та керування графіком."""
    return {
        "keyboard": [
            [{"text": "📅 Сьогодні"}, {"text": "🗓 Завтра"}],
            [
                {"text": "📊 Розклад на 7 днів"},
                {"text": "⚙️ Керування графіком"},
            ],
        ],
        "resize_keyboard": True,
        "persistent": True,
    }


def send_telegram_message(chat_id: str, text: str, reply_markup: dict = None) -> bool:
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        res = requests.post(url, json=payload, timeout=5)
        res.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Помилка відправки Telegram: {e}")
        return False


def edit_telegram_message(
    chat_id: str, message_id: int, text: str, reply_markup: dict = None
) -> bool:
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    try:
        res = requests.post(url, json=payload, timeout=5)
        res.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Помилка редагування Telegram: {e}")
        return False


def answer_callback_query(callback_query_id: str, text: str = None) -> bool:
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
    if not token or not callback_query_id:
        return False
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    try:
        requests.post(url, json=payload, timeout=4)
        return True
    except requests.exceptions.RequestException:
        return False


# ==========================================
# 1. РЕЖИМ «РОЗКЛАД ЗАПИСІВ»
# ==========================================


def get_week_schedule_text(start_date: date = None) -> str:
    """Огляд записів клієнтів на 7 днів."""
    if not start_date:
        start_date = timezone.localdate()

    end_date = start_date + timedelta(days=6)
    lines = [
        f"📊 <b>Записи клієнтів: {start_date.strftime('%d.%m')} —"
        f" {end_date.strftime('%d.%m.%Y')}</b>\n"
    ]

    for i in range(7):
        current_date = start_date + timedelta(days=i)
        day_short = WEEKDAYS_SHORT_UK[current_date.weekday()]
        date_str = current_date.strftime("%d.%m")

        try:
            wd = WorkingDay.objects.get(date=current_date)
            if wd.is_day_off:
                status_str = "<i>Вихідний</i> 😴"
            else:
                work_time = (
                    f"{wd.start_time.strftime('%H:%M')}–{wd.end_time.strftime('%H:%M')}"
                )
                count = (
                    Booking.objects.filter(date=current_date)
                    .exclude(status=Booking.Status.CANCELLED)
                    .count()
                )
                if count > 0:
                    status_str = f"🟢 <b>{count} кл.</b> ({work_time})"
                else:
                    status_str = f"🟡 <i>вільно</i> ({work_time})"
        except WorkingDay.DoesNotExist:
            status_str = "⚪ <i>Не налаштовано</i>"

        lines.append(f"<b>{date_str} ({day_short}):</b> {status_str}")

    lines.append("\n👇 <i>Натисніть на день, щоб переглянути клієнтів:</i>")
    return "\n".join(lines)


def get_week_inline_keyboard(start_date: date = None) -> dict:
    if not start_date:
        start_date = timezone.localdate()

    row1, row2 = [], []
    for i in range(7):
        target = start_date + timedelta(days=i)
        btn_text = f"{WEEKDAYS_SHORT_UK[target.weekday()]} {target.strftime('%d.%m')}"
        btn = {"text": btn_text, "callback_data": f"day_{target.isoformat()}"}
        if i < 4:
            row1.append(btn)
        else:
            row2.append(btn)

    prev_week = (start_date - timedelta(days=7)).isoformat()
    next_week = (start_date + timedelta(days=7)).isoformat()

    nav_row = [
        {"text": "⬅️ Попередній", "callback_data": f"week_{prev_week}"},
        {"text": "Сьогодні 🔄", "callback_data": "week_today"},
        {"text": "Наступний ➡️", "callback_data": f"week_{next_week}"},
    ]

    return {"inline_keyboard": [row1, row2, nav_row]}


def get_day_schedule_keyboard(target_date: date, show_back: bool = True) -> dict:
    """Клавіатура перегляду записів: скасування записів + перехід до графіка."""
    buttons = []
    bookings = (
        Booking.objects.filter(date=target_date)
        .exclude(status=Booking.Status.CANCELLED)
        .order_by("start_time")
    )
    for b in bookings:
        time_str = b.start_time.strftime("%H:%M")
        name_preview = (
            b.client_name[:12] + "…" if len(b.client_name) > 12 else b.client_name
        )
        buttons.append(
            [
                {
                    "text": f"❌ Скасувати {time_str} {name_preview}",
                    "callback_data": f"master_cancel_{b.id}",
                }
            ]
        )

    d_str = target_date.isoformat()
    buttons.append(
        [
            {
                "text": "⚙️ Налаштувати години цього дня",
                "callback_data": f"schedday_{d_str}",
            }
        ]
    )

    if show_back:
        buttons.append(
            [{"text": "« Назад до тижня", "callback_data": f"back_week_{d_str}"}]
        )

    return {"inline_keyboard": buttons}


# ==========================================
# 2. РЕЖИМ «КЕРУВАННЯ ГРАФІКОМ»
# ==========================================


def get_schedule_manager_text(start_date: date = None) -> str:
    """Текст панелі керування графіком."""
    if not start_date:
        start_date = timezone.localdate()

    end_date = start_date + timedelta(days=6)
    lines = [
        f"⚙️ <b>Керування графіком роботи</b>\n"
        f"Період: <code>{start_date.strftime('%d.%m')} — {end_date.strftime('%d.%m.%Y')}</code>\n\n"
        f"<i>Поточний стан робочих днів:</i>"
    ]

    for i in range(7):
        cur_d = start_date + timedelta(days=i)
        day_short = WEEKDAYS_SHORT_UK[cur_d.weekday()]
        d_str = cur_d.strftime("%d.%m")

        try:
            wd = WorkingDay.objects.get(date=cur_d)
            if wd.is_day_off:
                status = "😴 <b>Вихідний</b>"
            else:
                status = f"🟢 <b>{wd.start_time.strftime('%H:%M')} – {wd.end_time.strftime('%H:%M')}</b>"
        except WorkingDay.DoesNotExist:
            status = "⚪ <i>Не налаштовано</i>"

        lines.append(f"• <b>{d_str} ({day_short}):</b> {status}")

    lines.append(
        "\n👇 <i>Натисніть на день нижче, щоб встановити або змінити години:</i>"
    )
    return "\n".join(lines)


def get_schedule_manager_keyboard(start_date: date = None) -> dict:
    """Інлайн-кнопки вибору дня для налаштування годин."""
    if not start_date:
        start_date = timezone.localdate()

    row1, row2 = [], []
    for i in range(7):
        target = start_date + timedelta(days=i)
        btn_text = f"{WEEKDAYS_SHORT_UK[target.weekday()]} {target.strftime('%d.%m')}"
        btn = {
            "text": btn_text,
            "callback_data": f"schedday_{target.isoformat()}",
        }
        if i < 4:
            row1.append(btn)
        else:
            row2.append(btn)

    prev_week = (start_date - timedelta(days=7)).isoformat()
    next_week = (start_date + timedelta(days=7)).isoformat()

    nav_row = [
        {"text": "⬅️ Попередній", "callback_data": f"mgrweek_{prev_week}"},
        {"text": "Сьогодні 🔄", "callback_data": "mgrweek_today"},
        {"text": "Наступний ➡️", "callback_data": f"mgrweek_{next_week}"},
    ]

    return {"inline_keyboard": [row1, row2, nav_row]}


def get_day_manager_text(target_date: date) -> str:
    """Текст картки конкретного дня при редагуванні."""
    day_name = WEEKDAYS_UK[target_date.weekday()]
    formatted = target_date.strftime("%d.%m.%Y")

    try:
        wd = WorkingDay.objects.get(date=target_date)
        if wd.is_day_off:
            current_status = "😴 <b>Вихідний день</b> (запис на сайті закрито)"
        else:
            current_status = (
                f"🟢 <b>Робочий день: {wd.start_time.strftime('%H:%M')} –"
                f" {wd.end_time.strftime('%H:%M')}</b>"
            )
    except WorkingDay.DoesNotExist:
        current_status = "⚪ <b>Графік не задано</b> (клієнти не можуть записатися)"

    return (
        f"⚙️ <b>Налаштування дня: {day_name} ({formatted})</b>\n\n"
        f"Поточний статус: {current_status}\n\n"
        f"Оберіть дію нижче:"
    )


def get_day_manager_keyboard(target_date: date) -> dict:
    """Кнопки вибору дій для дня: зміна годин / вихідний."""
    d_str = target_date.isoformat()
    try:
        wd = WorkingDay.objects.get(date=target_date)
        is_off = wd.is_day_off
    except WorkingDay.DoesNotExist:
        is_off = True

    buttons = []
    if is_off:
        buttons.append(
            [
                {
                    "text": "🟢 Зробити день РОБОЧИМ (задати години)",
                    "callback_data": f"pickstart_{d_str}",
                }
            ]
        )
    else:
        buttons.append(
            [
                {
                    "text": "🕒 Змінити години роботи",
                    "callback_data": f"pickstart_{d_str}",
                }
            ]
        )
        buttons.append(
            [
                {
                    "text": "😴 Зробити день ВИХІДНИМ",
                    "callback_data": f"setoff_{d_str}",
                }
            ]
        )

    buttons.append(
        [
            {
                "text": "« Назад до календаря",
                "callback_data": f"back_mgrweek_{d_str}",
            }
        ]
    )
    return {"inline_keyboard": buttons}


# --- КОНСТРУКТОР ГОДИН ---


def get_start_hours_keyboard(target_date: date) -> dict:
    """Вибір початку зміни: з 09:00 до 13:00 (крок 30 хв)."""
    d_str = target_date.isoformat()

    start_options = [
        "09:00",
        "09:30",
        "10:00",
        "10:30",
        "11:00",
        "11:30",
        "12:00",
        "12:30",
        "13:00",
    ]

    keyboard = []
    row = []
    for h in start_options:
        row.append({"text": h, "callback_data": f"setstart_{d_str}_{h}"})
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([{"text": "« Скасувати", "callback_data": f"schedday_{d_str}"}])
    return {"inline_keyboard": keyboard}


def get_end_hours_keyboard(target_date: date, start_time_str: str) -> dict:
    """Вибір завершення зміни: з 13:30 до 22:00 (крок 30 хв)."""
    d_str = target_date.isoformat()
    start_dt = datetime.strptime(start_time_str, "%H:%M")

    end_options = [
        "13:00",
        "13:30",
        "14:00",
        "14:30",
        "15:00",
        "15:30",
        "16:00",
        "16:30",
        "17:00",
        "17:30",
        "18:00",
        "18:30",
        "19:00",
        "19:30",
        "20:00",
        "20:30",
        "21:00",
        "21:30",
        "22:00",
    ]

    keyboard = []
    row = []
    for h_str in end_options:
        curr_dt = datetime.strptime(h_str, "%H:%M")
        if curr_dt > start_dt:
            row.append(
                {
                    "text": h_str,
                    "callback_data": f"savehours_{d_str}_{start_time_str}_{h_str}",
                }
            )
            if len(row) == 3:
                keyboard.append(row)
                row = []
    if row:
        keyboard.append(row)

    keyboard.append([{"text": "« Назад", "callback_data": f"pickstart_{d_str}"}])
    return {"inline_keyboard": keyboard}


# --- РОЗРАХУНОК СЛОТІВ ТА ПОВІДОМЛЕННЯ ---


def get_available_slots_for_day(target_date: date) -> list[str]:
    try:
        working_day = WorkingDay.objects.get(date=target_date)
        if working_day.is_day_off:
            return []
    except WorkingDay.DoesNotExist:
        return []

    service = Service.objects.filter(is_active=True).first()
    dur_mins = service.duration_minutes if service else 40
    buf_mins = (
        service.buffer_minutes
        if (service and service.buffer_minutes is not None)
        else 10
    )

    day_start_dt = datetime.combine(target_date, working_day.start_time)
    day_end_dt = datetime.combine(target_date, working_day.end_time)

    confirmed_bookings = (
        Booking.objects.filter(date=target_date)
        .exclude(status=Booking.Status.CANCELLED)
        .select_related("service")
        .order_by("start_time")
    )

    busy_intervals = []
    for b in confirmed_bookings:
        b_start = datetime.combine(target_date, b.start_time)
        b_buffer = (
            b.service.buffer_minutes
            if (b.service and b.service.buffer_minutes is not None)
            else 10
        )
        if b.end_time:
            b_end_clean = datetime.combine(target_date, b.end_time)
        else:
            d = b.service.duration_minutes if b.service else dur_mins
            b_end_clean = b_start + timedelta(minutes=d)
        busy_intervals.append((b_start, b_end_clean + timedelta(minutes=b_buffer)))

    merged_busy = []
    for interval in sorted(busy_intervals, key=lambda x: x[0]):
        if not merged_busy:
            merged_busy.append(interval)
        else:
            last_start, last_end = merged_busy[-1]
            if interval[0] <= last_end:
                merged_busy[-1] = (last_start, max(last_end, interval[1]))
            else:
                merged_busy.append(interval)

    free_windows = []
    cursor = day_start_dt
    for b_start, b_end in merged_busy:
        if b_start > cursor:
            free_windows.append((cursor, min(b_start, day_end_dt)))
        cursor = max(cursor, b_end)
    if cursor < day_end_dt:
        free_windows.append((cursor, day_end_dt))

    service_dur = timedelta(minutes=dur_mins)
    service_buf = timedelta(minutes=buf_mins)
    service_total = service_dur + service_buf
    min_viable_gap = 30

    slots = set()
    now_dt = datetime.combine(timezone.localdate(), timezone.localtime().time())

    for w_start, w_end in free_windows:
        window_duration_mins = (w_end - w_start).total_seconds() / 60
        service_total_mins = service_total.total_seconds() / 60

        if w_end == day_end_dt:
            if w_start + service_dur > day_end_dt:
                continue
        else:
            if w_start + service_total > w_end:
                continue

        candidates = [w_start]
        curr_hour = w_start.hour
        if w_start.minute > 0:
            curr_hour += 1

        while curr_hour <= w_end.hour:
            cand_hour_dt = datetime.combine(target_date, time(curr_hour, 0))
            if w_start < cand_hour_dt < w_end:
                candidates.append(cand_hour_dt)
            curr_hour += 1

        for cand in candidates:
            if target_date == timezone.localdate() and cand <= (
                now_dt + timedelta(minutes=15)
            ):
                continue
            if w_end == day_end_dt:
                if cand + service_dur > day_end_dt:
                    continue
            else:
                if cand + service_total > w_end:
                    continue

            gap_before = (cand - w_start).total_seconds() / 60
            if 0 < gap_before < min_viable_gap:
                continue

            if w_end != day_end_dt:
                cand_busy_end = cand + service_total
                gap_after = (w_end - cand_busy_end).total_seconds() / 60
                if 0 < gap_after < min_viable_gap:
                    can_fit_another = window_duration_mins >= (
                        service_total_mins + min_viable_gap
                    )
                    if can_fit_another or cand != w_start:
                        continue

            slots.add(cand.strftime("%H:%M"))

    return sorted(list(slots))


def get_day_schedule_text(target_date: date) -> str:
    day_name = WEEKDAYS_UK[target_date.weekday()]
    formatted_date = target_date.strftime("%d.%m.%Y")

    try:
        working_day = WorkingDay.objects.get(date=target_date)
        if working_day.is_day_off:
            return (
                f"😴 <b>{day_name} ({formatted_date})</b> — <b>ВИХІДНИЙ ДЕНЬ</b>.\n\n"
                f"<i>Слоти на сайті для клієнтів закриті.</i>"
            )
        work_hours = f"{working_day.start_time.strftime('%H:%M')} – {working_day.end_time.strftime('%H:%M')}"
    except WorkingDay.DoesNotExist:
        return (
            f"📅 <b>{day_name} ({formatted_date})</b>\n\n"
            f"⚪ <b>Графік ще не встановлено!</b>\n"
            f"<i>Клієнти не можуть записатися, поки ви не вкажете години роботи.</i>"
        )

    bookings = (
        Booking.objects.filter(date=target_date)
        .exclude(status=Booking.Status.CANCELLED)
        .select_related("service")
        .order_by("start_time")
    )

    header = (
        f"📅 <b>Розклад на {day_name} ({formatted_date})</b>\n"
        f"🕒 Робочі години: <code>{work_hours}</code>\n"
    )

    lines = [header, f"👥 Кількість клієнтів: <b>{bookings.count()}</b>\n"]

    if bookings.exists():
        for b in bookings:
            service_title = (
                (b.service.name_uk or b.service.name_cs) if b.service else "Послуга"
            )
            price_str = f" ({b.service.price} Kč)" if b.service else ""
            lines.append(
                f"🟢 <b>{b.start_time.strftime('%H:%M')} – {b.end_time.strftime('%H:%M')}</b>\n"
                f"👤 {b.client_name} (<a href='tel:{b.client_phone}'>{b.client_phone}</a>)\n"
                f"✂️ {service_title}{price_str}\n"
            )
    else:
        lines.append("<i>Записів поки немає.</i>\n")

    available_slots = get_available_slots_for_day(target_date)
    if available_slots:
        lines.append("🕒 <b>Вільні слоти для запису (як бачить клієнт):</b>")
        badge_slots = [f"<code>{s}</code>" for s in available_slots]
        chunk_size = 4
        chunks = [
            badge_slots[i : i + chunk_size]
            for i in range(0, len(badge_slots), chunk_size)
        ]
        for row in chunks:
            lines.append("  ".join(row))
    else:
        lines.append("🔒 <i>Вільних вікон для запису більше немає.</i>")

    return "\n".join(lines)


def send_booking_notification(booking):
    raw_chat_ids = str(getattr(settings, "TELEGRAM_BARBER_CHAT_ID", "") or "")
    chat_ids = [cid.strip() for cid in raw_chat_ids.split(",") if cid.strip()]
    if not chat_ids:
        return False

    service_name = (
        booking.service.name_uk if booking.service.name_uk else booking.service.name_cs
    )
    safe_client_name = html.escape(booking.client_name)
    safe_phone = html.escape(booking.client_phone)
    message_text = (
        "✂️ <b>Новий запис!</b>\n\n"
        f"👤 <b>Клієнт:</b> {safe_client_name}\n"
        f"📞 <b>Телефон:</b> <a href='tel:{safe_phone}'>{safe_phone}</a>\n"
        f"💇‍♀️ <b>Послуга:</b> {service_name} ({booking.service.duration_minutes} хв)\n"
        f"💰 <b>Вартість:</b> {booking.service.price} Kč\n"
        f"📅 <b>Дата:</b> {booking.date.strftime('%d.%m.%Y')}\n"
        f"⏰ <b>Час:</b> {booking.start_time.strftime('%H:%M')} – {booking.end_time.strftime('%H:%M')}"
    )
    cancel_markup = {
        "inline_keyboard": [
            [
                {
                    "text": "❌ Скасувати цей запис",
                    "callback_data": f"master_cancel_{booking.id}",
                }
            ]
        ]
    }

    success = True
    for cid in chat_ids:
        res = send_telegram_message(
            chat_id=cid, text=message_text, reply_markup=cancel_markup
        )
        if not res:
            success = False
    return success


def send_cancellation_notification(booking):
    raw_chat_ids = str(getattr(settings, "TELEGRAM_BARBER_CHAT_ID", "") or "")
    chat_ids = [cid.strip() for cid in raw_chat_ids.split(",") if cid.strip()]
    if not chat_ids:
        return False

    service_name = (
        booking.service.name_uk if booking.service.name_uk else booking.service.name_cs
    )
    safe_client_name = html.escape(booking.client_name)
    safe_phone = html.escape(booking.client_phone)
    message_text = (
        "❌ <b>Клієнт скасував запис!</b>\n\n"
        f"👤 <b>Клієнт:</b> {safe_client_name}\n"
        f"📞 <b>Телефон:</b> {safe_phone}\n"
        f"💇‍♀️ <b>Послуга:</b> {service_name}\n"
        f"📅 <b>Дата:</b> {booking.date.strftime('%d.%m.%Y')}\n"
        f"⏰ <b>Було призначено на:</b> {booking.start_time.strftime('%H:%M')}\n\n"
        "<i>Цей час знову доступний на сайті для інших людей.</i>"
    )

    success = True
    for cid in chat_ids:
        res = send_telegram_message(chat_id=cid, text=message_text)
        if not res:
            success = False
    return success
