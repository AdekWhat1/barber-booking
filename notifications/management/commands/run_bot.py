from datetime import datetime, timedelta
import html
import time
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
import requests

from bookings.models import Booking, WorkingDay
from notifications.services import (
    answer_callback_query,
    edit_telegram_message,
    get_admin_keyboard,
    get_day_manager_keyboard,
    get_day_manager_text,
    get_day_schedule_keyboard,
    get_day_schedule_text,
    get_end_hours_keyboard,
    get_schedule_manager_keyboard,
    get_schedule_manager_text,
    get_start_hours_keyboard,
    get_week_inline_keyboard,
    get_week_schedule_text,
    send_telegram_message,
)

SECRET_INVITE_TOKEN = getattr(settings, "TELEGRAM_INVITE_TOKEN", None)

ALLOWED_CHAT_IDS = set()


def is_user_authorized(chat_id: str | int) -> bool:
    """Перевіряє наявність Chat ID у списку дозволених."""
    return str(chat_id).strip() in ALLOWED_CHAT_IDS


class Command(BaseCommand):
    help = "Telegram бот: розклад, керування днями через кнопки та авто-доступ"

    def handle(self, *args, **options):
        token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
        admin_chat_ids_raw = str(getattr(settings, "TELEGRAM_BARBER_CHAT_ID", "") or "")

        if not token:
            self.stderr.write(
                self.style.ERROR("TELEGRAM_BOT_TOKEN не задано в settings.py")
            )
            return

        for cid in admin_chat_ids_raw.split(","):
            cid_clean = cid.strip()
            if cid_clean:
                ALLOWED_CHAT_IDS.add(cid_clean)

        self.stdout.write(
            self.style.SUCCESS(
                f"🤖 Telegram-бот запущено!\n"
                f"Авторизовані Chat ID: {list(ALLOWED_CHAT_IDS) or 'немає'}\n"
                f"Інвайт-токен: {SECRET_INVITE_TOKEN}"
            )
        )

        offset = 0

        while True:
            try:
                url = f"https://api.telegram.org/bot{token}/getUpdates?offset={offset}&timeout=20"
                res = requests.get(url, timeout=25).json()

                if not res.get("ok"):
                    time.sleep(2)
                    continue

                for update in res.get("result", []):
                    offset = update["update_id"] + 1

                    # 1. ОБРОБКА ТЕКСТОВИХ ПОВІДОМЛЕНЬ ТА МЕНЮ
                    if "message" in update:
                        msg = update["message"]
                        chat_id = str(msg.get("chat", {}).get("id"))
                        text = (msg.get("text") or "").strip()

                        if SECRET_INVITE_TOKEN and (
                            text == f"/start {SECRET_INVITE_TOKEN}"
                            or text == SECRET_INVITE_TOKEN
                        ):
                            ALLOWED_CHAT_IDS.add(chat_id)
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"🎉 Авторизація успішна! Chat ID: {chat_id}"
                                )
                            )
                            send_telegram_message(
                                chat_id=chat_id,
                                text=(
                                    "✅ <b>Доступ активовано!</b>\n\n"
                                    "Вітаю в робочому кабінеті. Тут ви можете"
                                    " переглядати записи, скасовувати їх та"
                                    " виставляти графік кнопками:"
                                ),
                                reply_markup=get_admin_keyboard(),
                            )
                            continue

                        # Перевірка прав доступу
                        if not is_user_authorized(chat_id):
                            self.stdout.write(
                                self.style.WARNING(
                                    f"⚠️ Спроба неавторизованого доступу від ID: {chat_id}"
                                )
                            )
                            send_telegram_message(
                                chat_id=chat_id,
                                text="🔒 <b>Доступ закрито.</b>\nЦей бот призначений виключно для майстрині студії.",
                            )
                            continue

                        today = timezone.localdate()

                        if text in ["/start", "Меню"]:
                            send_telegram_message(
                                chat_id=chat_id,
                                text="👋 Оберіть потрібний розділ:",
                                reply_markup=get_admin_keyboard(),
                            )

                        elif text == "📅 Сьогодні":
                            reply_text = get_day_schedule_text(today)
                            inline_kb = get_day_schedule_keyboard(
                                today, show_back=False
                            )
                            send_telegram_message(
                                chat_id=chat_id,
                                text=reply_text,
                                reply_markup=inline_kb,
                            )

                        elif text == "🗓 Завтра":
                            tomorrow = today + timedelta(days=1)
                            reply_text = get_day_schedule_text(tomorrow)
                            inline_kb = get_day_schedule_keyboard(
                                tomorrow, show_back=False
                            )
                            send_telegram_message(
                                chat_id=chat_id,
                                text=reply_text,
                                reply_markup=inline_kb,
                            )

                        elif text == "📊 Розклад на 7 днів":
                            reply_text = get_week_schedule_text(today)
                            inline_kb = get_week_inline_keyboard(today)
                            send_telegram_message(
                                chat_id=chat_id,
                                text=reply_text,
                                reply_markup=inline_kb,
                            )

                        elif text == "⚙️ Керування графіком":
                            reply_text = get_schedule_manager_text(today)
                            inline_kb = get_schedule_manager_keyboard(today)
                            send_telegram_message(
                                chat_id=chat_id,
                                text=reply_text,
                                reply_markup=inline_kb,
                            )

                    # 2. ОБРОБКА ІНЛАЙН-КНОПОК
                    elif "callback_query" in update:
                        cb = update["callback_query"]
                        cb_id = cb["id"]
                        data = cb.get("data", "")
                        msg = cb.get("message", {})
                        chat_id = str(msg.get("chat", {}).get("id"))
                        message_id = msg.get("message_id")

                        if not is_user_authorized(chat_id):
                            answer_callback_query(cb_id, text="Доступ заборонено.")
                            continue

                        if data.startswith("week_"):
                            week_val = data.replace("week_", "")
                            start_d = (
                                timezone.localdate()
                                if week_val == "today"
                                else datetime.strptime(week_val, "%Y-%m-%d").date()
                            )
                            reply_text = get_week_schedule_text(start_d)
                            inline_kb = get_week_inline_keyboard(start_d)
                            edit_telegram_message(
                                chat_id, message_id, reply_text, inline_kb
                            )
                            answer_callback_query(cb_id)

                        elif data.startswith("back_week_"):
                            d_str = data.replace("back_week_", "")
                            try:
                                d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
                                diff = d_obj - timezone.localdate()
                                start_d = timezone.localdate() + timedelta(
                                    weeks=(diff.days // 7)
                                )
                            except ValueError:
                                start_d = timezone.localdate()
                            reply_text = get_week_schedule_text(start_d)
                            inline_kb = get_week_inline_keyboard(start_d)
                            edit_telegram_message(
                                chat_id, message_id, reply_text, inline_kb
                            )
                            answer_callback_query(cb_id)

                        elif data.startswith("day_"):
                            date_str = data.replace("day_", "")
                            try:
                                target_d = datetime.strptime(
                                    date_str, "%Y-%m-%d"
                                ).date()
                                schedule_text = get_day_schedule_text(target_d)
                                inline_kb = get_day_schedule_keyboard(
                                    target_d, show_back=True
                                )
                                edit_telegram_message(
                                    chat_id,
                                    message_id,
                                    schedule_text,
                                    reply_markup=inline_kb,
                                )
                                answer_callback_query(cb_id)
                            except ValueError:
                                answer_callback_query(cb_id, text="Помилка дати")

                        elif data.startswith("mgrweek_"):
                            week_val = data.replace("mgrweek_", "")
                            start_d = (
                                timezone.localdate()
                                if week_val == "today"
                                else datetime.strptime(week_val, "%Y-%m-%d").date()
                            )
                            reply_text = get_schedule_manager_text(start_d)
                            inline_kb = get_schedule_manager_keyboard(start_d)
                            edit_telegram_message(
                                chat_id, message_id, reply_text, inline_kb
                            )
                            answer_callback_query(cb_id)

                        elif data.startswith("back_mgrweek_"):
                            d_str = data.replace("back_mgrweek_", "")
                            try:
                                d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
                                diff = d_obj - timezone.localdate()
                                start_d = timezone.localdate() + timedelta(
                                    weeks=(diff.days // 7)
                                )
                            except ValueError:
                                start_d = timezone.localdate()
                            reply_text = get_schedule_manager_text(start_d)
                            inline_kb = get_schedule_manager_keyboard(start_d)
                            edit_telegram_message(
                                chat_id, message_id, reply_text, inline_kb
                            )
                            answer_callback_query(cb_id)

                        elif data.startswith("schedday_"):
                            date_str = data.replace("schedday_", "")
                            try:
                                target_d = datetime.strptime(
                                    date_str, "%Y-%m-%d"
                                ).date()
                                text = get_day_manager_text(target_d)
                                kb = get_day_manager_keyboard(target_d)
                                edit_telegram_message(
                                    chat_id, message_id, text, reply_markup=kb
                                )
                                answer_callback_query(cb_id)
                            except ValueError:
                                answer_callback_query(cb_id, text="Помилка дати")

                        elif data.startswith("pickstart_"):
                            date_str = data.replace("pickstart_", "")
                            target_d = datetime.strptime(date_str, "%Y-%m-%d").date()
                            kb = get_start_hours_keyboard(target_d)
                            edit_telegram_message(
                                chat_id,
                                message_id,
                                f"🕒 <b>Оберіть час ПОЧАТКУ зміни на {target_d.strftime('%d.%m.%Y')}:</b>",
                                reply_markup=kb,
                            )
                            answer_callback_query(cb_id)

                        elif data.startswith("setstart_"):
                            _, date_str, start_str = data.split("_")
                            target_d = datetime.strptime(date_str, "%Y-%m-%d").date()
                            kb = get_end_hours_keyboard(target_d, start_str)
                            edit_telegram_message(
                                chat_id,
                                message_id,
                                f"🕒 Початок: <b>{start_str}</b>.\n"
                                f"Тепер оберіть час <b>ЗАВЕРШЕННЯ</b> зміни на {target_d.strftime('%d.%m.%Y')}:",
                                reply_markup=kb,
                            )
                            answer_callback_query(cb_id)

                        elif data.startswith("savehours_"):
                            _, date_str, start_str, end_str = data.split("_")
                            target_d = datetime.strptime(date_str, "%Y-%m-%d").date()
                            start_t = datetime.strptime(start_str, "%H:%M").time()
                            end_t = datetime.strptime(end_str, "%H:%M").time()

                            WorkingDay.objects.update_or_create(
                                date=target_d,
                                defaults={
                                    "start_time": start_t,
                                    "end_time": end_t,
                                    "is_day_off": False,
                                },
                            )
                            answer_callback_query(
                                cb_id,
                                text=f"Збережено: {start_str}–{end_str}!",
                            )

                            text = get_day_manager_text(target_d)
                            kb = get_day_manager_keyboard(target_d)
                            edit_telegram_message(
                                chat_id, message_id, text, reply_markup=kb
                            )

                        elif data.startswith("setoff_"):
                            date_str = data.replace("setoff_", "")
                            target_d = datetime.strptime(date_str, "%Y-%m-%d").date()

                            has_bookings = (
                                Booking.objects.filter(date=target_d)
                                .exclude(status=Booking.Status.CANCELLED)
                                .exists()
                            )
                            if has_bookings:
                                answer_callback_query(
                                    cb_id,
                                    text="⚠️ На цей день є клієнти! Скасуйте їх спочатку.",
                                )
                                continue

                            WorkingDay.objects.update_or_create(
                                date=target_d,
                                defaults={
                                    "is_day_off": True,
                                    "start_time": datetime.strptime(
                                        "10:00", "%H:%M"
                                    ).time(),
                                    "end_time": datetime.strptime(
                                        "18:00", "%H:%M"
                                    ).time(),
                                },
                            )
                            answer_callback_query(
                                cb_id, text="Встановлено як вихідний!"
                            )

                            text = get_day_manager_text(target_d)
                            kb = get_day_manager_keyboard(target_d)
                            edit_telegram_message(
                                chat_id, message_id, text, reply_markup=kb
                            )

                        elif data.startswith("master_cancel_"):
                            booking_id = data.replace("master_cancel_", "")
                            try:
                                b = Booking.objects.select_related("service").get(
                                    id=booking_id
                                )

                                safe_name = html.escape(b.client_name)
                                safe_phone = html.escape(b.client_phone)
                                safe_service = (
                                    html.escape(b.service.name_uk or b.service.name_cs)
                                    if b.service
                                    else ""
                                )

                                confirm_kb = {
                                    "inline_keyboard": [
                                        [
                                            {
                                                "text": "⚠️ Підтвердити скасування",
                                                "callback_data": f"confirm_cancel_{booking_id}",
                                            }
                                        ],
                                        [
                                            {
                                                "text": "« Повернутися",
                                                "callback_data": f"day_{b.date.isoformat()}",
                                            }
                                        ],
                                    ]
                                }
                                edit_telegram_message(
                                    chat_id,
                                    message_id,
                                    f"❓ <b>Скасувати запис клієнта?</b>\n\n"
                                    f"👤 <b>{safe_name}</b> ({safe_phone})\n"
                                    f"📅 {b.date.strftime('%d.%m.%Y')} о {b.start_time.strftime('%H:%M')}\n"
                                    f"✂️ {safe_service}\n\n"
                                    "<i>Слот миттєво звільниться на сайті для інших людей.</i>",
                                    reply_markup=confirm_kb,
                                )
                                answer_callback_query(cb_id)
                            except Booking.DoesNotExist:
                                answer_callback_query(cb_id, text="Запис вже не існує.")

                        elif data.startswith("confirm_cancel_"):
                            booking_id = data.replace("confirm_cancel_", "")
                            try:
                                b = Booking.objects.get(id=booking_id)
                                target_date = b.date
                                b.status = Booking.Status.CANCELLED
                                b.save(update_fields=["status"])
                                answer_callback_query(cb_id, text="Запис скасовано!")

                                schedule_text = get_day_schedule_text(target_date)
                                inline_kb = get_day_schedule_keyboard(
                                    target_date, show_back=True
                                )
                                edit_telegram_message(
                                    chat_id,
                                    message_id,
                                    schedule_text,
                                    reply_markup=inline_kb,
                                )
                            except Booking.DoesNotExist:
                                answer_callback_query(cb_id, text="Запис не знайдено.")

            except requests.exceptions.RequestException:
                time.sleep(3)
            except Exception as e:
                self.stderr.write(f"Помилка бота: {e}")
                time.sleep(2)
