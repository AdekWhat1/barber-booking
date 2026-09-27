import time
import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from notifications.services import (
    get_day_schedule_text,
    get_week_schedule_text,
    send_telegram_message,
    get_admin_keyboard,
)


class Command(BaseCommand):
    help = "Запуск фонового слухача Telegram бота для обробки кнопок майстрині"

    def handle(self, *args, **options):
        token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
        admin_chat_id = str(getattr(settings, "TELEGRAM_BARBER_CHAT_ID", ""))

        if not token:
            self.stderr.write(self.style.ERROR("TELEGRAM_BOT_TOKEN не вказано в settings.py"))
            return

        self.stdout.write(self.style.SUCCESS("🤖 Telegram-бот успішно запущений і слухає кнопки..."))

        offset = 0

        while True:
            try:
                # Опитуємо Telegram на наявність нових кліків/повідомлень
                url = f"https://api.telegram.org/bot{token}/getUpdates?offset={offset}&timeout=20"
                res = requests.get(url, timeout=25).json()

                if not res.get("ok"):
                    time.sleep(2)
                    continue

                for update in res.get("result", []):
                    offset = update["update_id"] + 1

                    message = update.get("message")
                    if not message:
                        continue

                    chat_id = str(message.get("chat", {}).get("id"))
                    text = (message.get("text") or "").strip()

                    # Безпека: відповідаємо лише на чат майстрині
                    if admin_chat_id and chat_id != admin_chat_id:
                        continue

                    today = timezone.localdate()

                    if text in ["/start", "Меню"]:
                        send_telegram_message(
                            chat_id=chat_id,
                            text="👋 Вітаю! Оберіть потрібний розклад:",
                            reply_markup=get_admin_keyboard(),
                        )

                    elif text == "📅 Сьогодні":
                        reply_text = get_day_schedule_text(today)
                        send_telegram_message(chat_id=chat_id, text=reply_text, reply_markup=get_admin_keyboard())

                    elif text == "🗓 Завтра":
                        tomorrow = today + timedelta(days=1)
                        reply_text = get_day_schedule_text(tomorrow)
                        send_telegram_message(chat_id=chat_id, text=reply_text, reply_markup=get_admin_keyboard())

                    elif text == "📊 Розклад на 7 днів":
                        reply_text = get_week_schedule_text()
                        send_telegram_message(chat_id=chat_id, text=reply_text, reply_markup=get_admin_keyboard())

            except requests.exceptions.RequestException:
                time.sleep(3)
            except Exception as e:
                self.stderr.write(f"Помилка: {e}")
                time.sleep(2)