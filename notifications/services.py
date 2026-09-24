import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def send_booking_notification(booking):
    """
    Відправляє майстрині сповіщення про новий запис у Telegram українською мовою.
    """
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
    chat_id = getattr(settings, "TELEGRAM_BARBER_CHAT_ID", None)

    if not token or not chat_id:
        logger.warning("Telegram Bot Token або Chat ID не налаштовані.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    # Використовуємо українську назву послуги, якщо вона вказана, інакше чеську
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

    payload = {
        "chat_id": chat_id,
        "text": message_text,
        "parse_mode": "HTML",
    }

    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Помилка надсилання сповіщення в Telegram: {e}")
        return False


def send_cancellation_notification(booking):
    """
    Відправляє майстрині сповіщення про скасування запису.
    """
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
    chat_id = getattr(settings, "TELEGRAM_BARBER_CHAT_ID", None)

    if not token or not chat_id:
        logger.warning("Telegram Bot Token або Chat ID не налаштовані.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
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

    payload = {
        "chat_id": chat_id,
        "text": message_text,
        "parse_mode": "HTML",
    }

    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Помилка надсилання сповіщення про скасування: {e}")
        return False
