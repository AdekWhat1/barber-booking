from datetime import datetime, timedelta
import re
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

# Токен-запрошення для миттєвої авторизації майстрині
SECRET_INVITE_TOKEN = "barber2026"

# Множина ID авторизованих користувачів (ви + майстриня)
ALLOWED_CHAT_IDS = set()

# Стан очікування ручного вводу годин
USER_STATES = {}


class Command(BaseCommand):
    help = "Telegram бот: розклад, керування днями, авто-доступ та ручний ввід"

    def handle(self, *args, **options):
        token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
        admin_chat_id = str(getattr(settings, "TELEGRAM_BARBER_CHAT_ID", ""))

        if not token:
            self.stderr.write(
                self.style.ERROR("TELEGRAM_BOT_TOKEN не задано в settings.py")
            )
            return

        # Додаємо ваш ID одразу, щоб у вас доступ був завжди
        if admin_chat_id:
            ALLOWED_CHAT_IDS.add(admin_chat_id)

        self.stdout.write(
            self.style.SUCCESS(
                f"🤖 Telegram-бот запущено! Очікую авторизації (токен: {SECRET_INVITE_TOKEN})..."
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

                    # 1. ОБРОБКА ПОВІДОМЛЕНЬ
                    if "message" in update:
                        msg = update["message"]
                        chat_id = str(msg.get("chat", {}).get("id"))
                        text = (msg.get("text") or "").strip()

                        # Активація доступу через посилання або пароль
                        if (
                            text == f"/start {SECRET_INVITE_TOKEN}"
                            or text == SECRET_INVITE_TOKEN
                        ):
                            ALLOWED_CHAT_IDS.add(chat_id)
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"🎉 Майстриня авторизована! Chat ID: {chat_id}"
                                )
                            )
                            send_telegram_message(
                                chat_id=chat_id,
                                text=(
                                    "✅ <b>Доступ активовано!</b>\n\n"
                                    "Вітаю в робочому кабінеті. Тут ви можете"
                                    " переглядати записи, скасовувати їх та"
                                    " виставляти свій робочий графік:"
                                ),
                                reply_markup=get_admin_keyboard(),
                            )
                            continue

                        # Якщо користувач не авторизований
                        if chat_id not in ALLOWED_CHAT_IDS:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"⚠️ Спроба доступу від невідомого ID: {chat_id}"
                                )
                            )
                            send_telegram_message(
                                chat_id=chat_id,
                                text="🔒 <b>Доступ закрито.</b>\nЦей бот призначений виключно для майстрині студії.",
                            )
                            continue

                        # Ручний ввід годин (якщо бот очікує)
                        if (
                            chat_id in USER_STATES
                            and USER_STATES[chat_id]["action"] == "WAITING_MANUAL_HOURS"
                        ):
                            target_d = USER_STATES[chat_id]["date"]

                            if text.lower() in [
                                "відміна",
                                "скасувати",
                                "/cancel",
                            ]:
                                del USER_STATES[chat_id]
                                send_telegram_message(
                                    chat_id,
                                    "Ввід скасовано.",
                                    reply_markup=get_admin_keyboard(),
                                )
                                continue

                            times_found = re.findall(
                                r"\b([0-2]?[0-9]:[0-5][0-9])\b", text
                            )
                            if len(times_found) >= 2:
                                s_raw, e_raw = times_found[0], times_found[1]
                                try:
                                    s_time = datetime.strptime(
                                        s_raw,
                                        "%H:%M" if len(s_raw) == 5 else "%I:%M",
                                    ).time()
                                    e_time = datetime.strptime(
                                        e_raw,
                                        "%H:%M" if len(e_raw) == 5 else "%I:%M",
                                    ).time()

                                    if s_time >= e_time:
                                        send_telegram_message(
                                            chat_id,
                                            "⚠️ Час початку не може бути пізнішим за час завершення. Спробуйте ще раз:",
                                        )
                                        continue

                                    WorkingDay.objects.update_or_create(
                                        date=target_d,
                                        defaults={
                                            "start_time": s_time,
                                            "end_time": e_time,
                                            "is_day_off": False,
                                        },
                                    )
                                    del USER_STATES[chat_id]

                                    confirm_text = (
                                        f"✅ <b>Графік збережено!</b>\n\n"
                                        f"📅 Дата: <b>{target_d.strftime('%d.%m.%Y')}</b>\n"
                                        f"🕒 Години: <code>{s_time.strftime('%H:%M')} – {e_time.strftime('%H:%M')}</code>\n\n"
                                        f"<i>Слоти на сайті миттєво оновлені.</i>"
                                    )
                                    send_telegram_message(
                                        chat_id,
                                        confirm_text,
                                        reply_markup=get_admin_keyboard(),
                                    )
                                    continue
                                except ValueError:
                                    pass

                            send_telegram_message(
                                chat_id,
                                "⚠️ Формат не розпізнано. Введіть години, наприклад: <code>10:30 - 18:30</code>",
                            )
                            continue

                        # Стандартні кнопки меню
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

                        if chat_id not in ALLOWED_CHAT_IDS:
                            answer_callback_query(cb_id, text="Доступ заборонено.")
                            continue

                        # Ручний ввід
                        if data.startswith("manualhours_"):
                            date_str = data.replace("manualhours_", "")
                            target_d = datetime.strptime(date_str, "%Y-%m-%d").date()
                            USER_STATES[chat_id] = {
                                "action": "WAITING_MANUAL_HOURS",
                                "date": target_d,
                            }
                            cancel_kb = {
                                "inline_keyboard": [
                                    [
                                        {
                                            "text": "« Скасувати ввід",
                                            "callback_data": f"schedday_{date_str}",
                                        }
                                    ]
                                ]
                            }
                            send_telegram_message(
                                chat_id,
                                f"✍️ <b>Введіть години роботи на {target_d.strftime('%d.%m.%Y')}:</b>\n\n"
                                f"Напишіть повідомлення, наприклад:\n"
                                f"<code>10:30 - 18:30</code> або <code>10:30 19:00</code>",
                                reply_markup=cancel_kb,
                            )
                            answer_callback_query(cb_id)

                        # Навігація по записах
                        elif data.startswith("week_"):
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
                            if chat_id in USER_STATES:
                                del USER_STATES[chat_id]
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

                        # Конструктор годин
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

                        # Скасування клієнтів майстринею
                        elif data.startswith("master_cancel_"):
                            booking_id = data.replace("master_cancel_", "")
                            try:
                                b = Booking.objects.select_related("service").get(
                                    id=booking_id
                                )
                                confirm_kb = {
                                    "inline_keyboard": [
                                        [
                                            {
                                                "text": (
                                                    "⚠️ Підтвердити" " скасування"
                                                ),
                                                "callback_data": (
                                                    "confirm_cancel_" f"{booking_id}"
                                                ),
                                            }
                                        ],
                                        [
                                            {
                                                "text": "« Повернутися",
                                                "callback_data": (
                                                    f"day_{b.date.isoformat()}"
                                                ),
                                            }
                                        ],
                                    ]
                                }
                                edit_telegram_message(
                                    chat_id,
                                    message_id,
                                    f"❓ <b>Скасувати запис клієнта?</b>\n\n"
                                    f"👤 <b>{b.client_name}</b> ({b.client_phone})\n"
                                    f"📅 {b.date.strftime('%d.%m.%Y')} о {b.start_time.strftime('%H:%M')}\n"
                                    f"✂️ {b.service.name_uk if b.service else ''}\n\n"
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
