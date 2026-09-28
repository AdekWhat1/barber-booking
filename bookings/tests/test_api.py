from datetime import time, timedelta
from unittest.mock import patch
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from bookings.models import Booking, Service, WorkingDay


class BookingBusinessLogicTests(APITestCase):

    def setUp(self):
        cache.clear()

        self.service = Service.objects.create(
            name_uk="Чоловіча стрижка",
            name_cs="Pánský střih",
            duration_minutes=45,
            price=450,
            is_active=True,
        )

        self.target_date = timezone.localdate() + timedelta(days=3)
        self.working_day = WorkingDay.objects.create(
            date=self.target_date,
            start_time=time(10, 0),
            end_time=time(18, 0),
            is_day_off=False,
        )

        self.create_booking_url = reverse("bookings:booking-create")

    # 1. Створення запису та автоматичний розрахунок end_time
    @patch("notifications.services.send_telegram_message")
    def test_create_booking_success(self, mock_telegram):
        mock_telegram.return_value = True

        payload = {
            "service": self.service.id,
            "date": self.target_date.isoformat(),
            "start_time": "11:00",
            "client_name": "Іван Петренко",
            "client_phone": "+420777888999",
        }

        response = self.client.post(self.create_booking_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        booking = Booking.objects.get(client_phone="+420777888999")
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(booking.start_time, time(11, 0))
        self.assertEqual(booking.end_time, time(11, 45))
        self.assertTrue(bool(booking.cancel_token))

    # 2. Захист від повторного бронювання того самого слота (Double Booking)
    @patch("notifications.services.send_telegram_message")
    def test_prevent_double_booking_same_slot(self, mock_telegram):
        mock_telegram.return_value = True

        Booking.objects.create(
            service=self.service,
            date=self.target_date,
            start_time=time(12, 0),
            end_time=time(12, 45),
            client_name="Перший Клієнт",
            client_phone="+420111222333",
            status=Booking.Status.CONFIRMED,
        )

        payload = {
            "service": self.service.id,
            "date": self.target_date.isoformat(),
            "start_time": "12:00",
            "client_name": "Другий Клієнт",
            "client_phone": "+420444555666",
        }

        response = self.client.post(self.create_booking_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            Booking.objects.filter(
                date=self.target_date, start_time=time(12, 0)
            ).count(),
            1,
        )

    # 3. Онлайн-скасування запису клієнтом за токеном (> 24 годин)
    @patch("notifications.services.send_telegram_message")
    def test_cancel_booking_by_token(self, mock_telegram):
        mock_telegram.return_value = True

        booking = Booking.objects.create(
            service=self.service,
            date=self.target_date,
            start_time=time(14, 0),
            end_time=time(14, 45),
            client_name="Олексій",
            client_phone="+420999000111",
            status=Booking.Status.CONFIRMED,
        )

        cancel_url = reverse(
            "bookings:booking-cancel",
            kwargs={"cancel_token": booking.cancel_token},
        )
        response = self.client.post(cancel_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)

        payload = {
            "service": self.service.id,
            "date": self.target_date.isoformat(),
            "start_time": "14:00",
            "client_name": "Новий Клієнт",
            "client_phone": "+420333222111",
        }
        rebook_response = self.client.post(
            self.create_booking_url, payload, format="json"
        )
        self.assertEqual(rebook_response.status_code, status.HTTP_201_CREATED)

    # 4. Заборона онлайн-скасування менш ніж за 24 години
    @patch("notifications.services.send_telegram_message")
    def test_prevent_cancellation_under_24_hours(self, mock_telegram):
        mock_telegram.return_value = True

        short_notice_date = timezone.localdate() + timedelta(days=1)
        booking = Booking.objects.create(
            service=self.service,
            date=short_notice_date,
            start_time=time(9, 0),
            end_time=time(9, 45),
            client_name="Клієнт В останній момент",
            client_phone="+420555666777",
            status=Booking.Status.CONFIRMED,
        )

        cancel_url = reverse(
            "bookings:booking-cancel",
            kwargs={"cancel_token": booking.cancel_token},
        )
        response = self.client.post(cancel_url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)

    # 5. Захист від спам-запитів та ботів (Rate Limiting)
    @patch("notifications.services.send_telegram_message")
    def test_booking_creation_rate_limiting(self, mock_telegram):
        mock_telegram.return_value = True

        payload_template = {
            "service": self.service.id,
            "date": self.target_date.isoformat(),
            "client_phone": "+420000000000",
        }

        for i in range(5):
            payload = payload_template.copy()
            payload["start_time"] = f"{10 + i}:00"
            payload["client_name"] = f"Клієнт {i}"
            res = self.client.post(self.create_booking_url, payload, format="json")
            self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        payload = payload_template.copy()
        payload["start_time"] = "16:00"
        payload["client_name"] = "Спам Бот"
        blocked_res = self.client.post(self.create_booking_url, payload, format="json")

        self.assertEqual(blocked_res.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
