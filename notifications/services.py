import logging
from datetime import date, timedelta
import requests
from django.conf import settings
from django.utils import timezone

from bookings.models import Booking, WorkingDay

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


def get_admin_keyboard():
    """Повертає постійне меню швидких кнопок для майстрині."""
    return {
        "keyboard": [
            [{"text": "📅 Сьогодні"}, {"text": "🗓 Завтра"}],
            [{"text": "📊 Розклад на 7 днів"}],
        ],
        "resize_keyboard": True,
        "persistent": True,
    }


def send_telegram_message(chat_id: str, text: str, reply_markup: dict = None) -> bool:
    """Універсальна функція надсилання повідомлення в Telegram."""
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
    if not token or not chat_id:
        logger.warning("Telegram Bot Token або Chat ID не налаштовані.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Помилка надсилання в Telegram: {e}")
        return False


def get_day_schedule_text(target_date: date) -> str:
    """Формує детальний розклад записів на обрану дату з підрахунком доходу."""
    day_name = WEEKDAYS_UK[target_date.weekday()]
    formatted_date = target_date.strftime("%d.%m.%Y")

    try:
        working_day = WorkingDay.objects.get(date=target_date)
        if working_day.is_day_off:
            return (
                f"😴 <b>{day_name} ({formatted_date})</b> — Вихідний день за графіком.\n"
                f"Записів немає."
            )
        work_hours = (
            f"{working_day.start_time.strftime('%H:%M')} – "
            f"{working_day.end_time.strftime('%H:%M')}"
        )
    except WorkingDay.DoesNotExist:
        work_hours = "графік ще не встановлено"

    bookings = (
        Booking.objects.filter(
            date=target_date,
            status=Booking.Status.CONFIRMED,
        )
        .select_related("service")
        .order_by("start_time")
    )

    header = (
        f"📅 <b>Розклад на {day_name} ({formatted_date})</b>\n"
        f"🕒 Робочі години: <code>{work_hours}</code>\n"
    )

    if not bookings.exists():
        return f"{header}\n<i>На цей день немає жодного запису. Вільно!</i>"

    total_income = sum(b.service.price for b in bookings if b.service)
    lines = [
        header,
        f"👥 Записів: <b>{bookings.count()}</b> | Очікувана каса: <b>{total_income} Kč</b>\n",
    ]

    for b in bookings:
        service_title = (
            (b.service.name_uk or b.service.name_cs) if b.service else "Послуга"
        )
        service_price = f"{b.service.price} Kč" if b.service else ""
        lines.append(
            f"🟢 <b>{b.start_time.strftime('%H:%M')} – {b.end_time.strftime('%H:%M')}</b>\n"
            f"👤 {b.client_name} (<a href='tel:{b.client_phone}'>{b.client_phone}</a>)\n"
            f"✂️ {service_title} ({service_price})\n"
        )

    return "\n".join(lines)


def get_week_schedule_text() -> str:
    """Формує стислий звіт-дайджест на найближчі 7 днів."""
    today = timezone.localdate()
    lines = ["📊 <b>Завантаженість на 7 днів:</b>\n"]
    total_week_income = 0
    total_week_bookings = 0

    for i in range(7):
        current_date = today + timedelta(days=i)
        day_name = WEEKDAYS_UK[current_date.weekday()]
        date_str = current_date.strftime("%d.%m")

        is_day_off = False
        try:
            wd = WorkingDay.objects.get(date=current_date)
            if wd.is_day_off:
                is_day_off = True
        except WorkingDay.DoesNotExist:
            pass

        if is_day_off:
            lines.append(f"⚪ <b>{date_str} ({day_name}):</b> <i>Вихідний</i>")
            continue

        day_bookings = Booking.objects.filter(
            date=current_date,
            status=Booking.Status.CONFIRMED,
        ).select_related("service")

        count = day_bookings.count()
        income = sum(b.service.price for b in day_bookings if b.service)
        total_week_income += income
        total_week_bookings += count

        if count > 0:
            lines.append(
                f"🟢 <b>{date_str} ({day_name}):</b> <b>{count}</b> клієнтів (<b>{income} Kč</b>)"
            )
        else:
            lines.append(f"🟡 <b>{date_str} ({day_name}):</b> <i>вільно</i>")

    lines.append(
        f"\n📈 <b>Разом за тиждень:</b> {total_week_bookings} клієнтів на суму <b>{total_week_income} Kč</b>"
    )
    return "\n".join(lines)


def send_booking_notification(booking):
    """Сповіщення майстрині про новий запис + прикріплення клавіатури."""
    chat_id = getattr(settings, "TELEGRAM_BARBER_CHAT_ID", None)
    if not chat_id:
        return False

    service_name = (
        booking.service.name_uk if booking.service.name_uk else booking.service.name_cs
    )
    message_text = (
        "✂️ <b>Новий запис!</b>\n\n"
        f"👤 <b>Клієнт:</b> {booking.client_name}\n"
        f"📞 <b>Телефон:</b> <a href='tel:{booking.client_phone}'>{booking.client_phone}</a>\n"
        f"💇‍♀️ <b>Послуга:</b> {service_name} ({booking.service.duration_minutes} хв)\n"
        f"💰 <b>Вартість:</b> {booking.service.price} Kč\n"
        f"📅 <b>Дата:</b> {booking.date.strftime('%d.%m.%Y')}\n"
        f"⏰ <b>Час:</b> {booking.start_time.strftime('%H:%M')} – {booking.end_time.strftime('%H:%M')}"
    )

    return send_telegram_message(
        chat_id=chat_id,
        text=message_text,
        reply_markup=get_admin_keyboard(),
    )


def send_cancellation_notification(booking):
    """Сповіщення майстрині про скасування + прикріплення клавіатури."""
    chat_id = getattr(settings, "TELEGRAM_BARBER_CHAT_ID", None)
    if not chat_id:
        return False

    service_name = (
        booking.service.name_uk if booking.service.name_uk else booking.service.name_cs
    )
    message_text = (
        "❌ <b>Запис скасовано!</b>\n\n"
        f"👤 <b>Клієнт:</b> {booking.client_name}\n"
        f"📞 <b>Телефон:</b> {booking.client_phone}\n"
        f"💇‍♀️ <b>Послуга:</b> {service_name}\n"
        f"📅 <b>Дата:</b> {booking.date.strftime('%d.%m.%Y')}\n"
        f"⏰ <b>Було призначено на:</b> {booking.start_time.strftime('%H:%M')}\n\n"
        "<i>Цей часовий слот знову доступний для інших клієнтів.</i>"
    )

    return send_telegram_message(
        chat_id=chat_id,
        text=message_text,
        reply_markup=get_admin_keyboard(),
    )
