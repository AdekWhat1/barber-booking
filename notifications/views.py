import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.serializers import BookingCreateSerializer
from notifications.services import (
    send_booking_notification,
    get_day_schedule_text,
    get_week_schedule_text,
    send_telegram_message,
    get_admin_keyboard,
)

logger = logging.getLogger(__name__)


class BookingCreateView(generics.CreateAPIView):
    serializer_class = BookingCreateSerializer

    def perform_create(self, serializer):
        booking = serializer.save()
        send_booking_notification(booking)


class TelegramWebhookView(APIView):
    """
    Приймає вебхуки від Telegram.
    Обробляє натискання кнопок меню та повертає розклад майстрині.
    """

    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        message = request.data.get("message")
        if not message:
            return Response({"status": "ignored"}, status=status.HTTP_200_OK)

        chat_id = str(message.get("chat", {}).get("id"))
        admin_chat_id = str(getattr(settings, "TELEGRAM_BARBER_CHAT_ID", ""))

        # Захист: бот відповідає та показує розклад виключно майстрині
        if chat_id != admin_chat_id:
            logger.warning(
                f"Невідомий користувач (chat_id: {chat_id}) спробував викликати бота."
            )
            return Response({"status": "ignored"}, status=status.HTTP_200_OK)

        text = (message.get("text") or "").strip()
        today = timezone.localdate()

        if text in ["📅 Сьогодні", "/today"]:
            reply_text = get_day_schedule_text(today)
        elif text in ["🗓 Завтра", "/tomorrow"]:
            reply_text = get_day_schedule_text(today + timedelta(days=1))
        elif text in ["📊 Розклад на 7 днів", "/week"]:
            reply_text = get_week_schedule_text()
        elif text == "/start":
            reply_text = (
                "👋 <b>Привіт!</b>\n\n"
                "Я твій асистент з розкладу.\n"
                "Використовуй кнопки нижче для швидкого перегляду записів:"
            )
        else:
            reply_text = "🤔 Скористайся кнопками внизу для перегляду розкладу:"

        send_telegram_message(
            chat_id=chat_id,
            text=reply_text,
            reply_markup=get_admin_keyboard(),
        )

        return Response({"status": "ok"}, status=status.HTTP_200_OK)
