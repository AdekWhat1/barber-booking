from datetime import datetime, timedelta

from django.utils import timezone
from django.views.generic import TemplateView
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response

from notifications.services import (
    send_booking_notification,
    send_cancellation_notification,
)
from .models import Service, Booking, WorkingDay
from .serializers import ServiceSerializer, BookingCreateSerializer
from .services import get_available_slots
from .messages import get_msg


class ServiceListView(generics.ListAPIView):
    queryset = Service.objects.filter(is_active=True)
    serializer_class = ServiceSerializer


class AvailableSlotsView(APIView):
    """Генерація вільних віконець із 15-хвилинним кроком,

    урахуванням графіка майстрині (WorkingDay), буферного часу та захистом від
    «мертвих вікон» (розривів графіка від 10 до 30 хв).
    """

    authentication_classes = []

    def get(self, request):
        lang = request.query_params.get("lang", "cs")
        date_str = request.query_params.get("date")
        service_id = request.query_params.get("service_id")

        if not date_str or not service_id:
            return Response(
                {"error": get_msg("missing_params", lang)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            booking_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            service = Service.objects.get(id=service_id, is_active=True)
        except (ValueError, Service.DoesNotExist):
            return Response(
                {"error": get_msg("invalid_date_format", lang)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if booking_date < timezone.localdate():
            return Response({"slots": []})

        # 1. Перевірка робочого графіка майстрині з БД
        try:
            working_day = WorkingDay.objects.get(date=booking_date)
            if working_day.is_day_off:
                return Response({"slots": []})
        except WorkingDay.DoesNotExist:
            return Response({"slots": []})

        # 2. Отримання всіх активних записів на цей день
        confirmed_bookings = (
            Booking.objects.filter(
                date=booking_date,
            )
            .exclude(status=Booking.Status.CANCELLED)
            .select_related("service")
            .only(
                "start_time",
                "end_time",
                "service__duration_minutes",
                "service__buffer_minutes",
            )
            .order_by("start_time")
        )

        tz = timezone.get_current_timezone()

        # Формуємо зайняті проміжки з урахуванням буферного часу
        busy_intervals = []
        for b in confirmed_bookings:
            b_start = timezone.make_aware(
                datetime.combine(booking_date, b.start_time), tz
            )
            b_buffer = b.service.buffer_minutes if b.service else 10

            if b.end_time:
                b_end_clean = timezone.make_aware(
                    datetime.combine(booking_date, b.end_time), tz
                )
            else:
                dur = (
                    b.service.duration_minutes
                    if b.service
                    else service.duration_minutes
                )
                b_end_clean = b_start + timedelta(minutes=dur)

            b_end_with_buffer = b_end_clean + timedelta(minutes=b_buffer)
            busy_intervals.append((b_start, b_end_with_buffer))

        # 3. Генерація слотів
        slots = []
        current_dt = timezone.make_aware(
            datetime.combine(booking_date, working_day.start_time), tz
        )
        end_work_dt = timezone.make_aware(
            datetime.combine(booking_date, working_day.end_time), tz
        )
        now = timezone.localtime()

        service_duration = timedelta(minutes=service.duration_minutes)
        service_buffer = timedelta(minutes=service.buffer_minutes)
        min_viable_gap = 30  # Мінімальна послуга з буфером (дитяча 20 хв + 10 хв буфер)

        while current_dt < end_work_dt:
            candidate_start = current_dt
            candidate_service_end = candidate_start + service_duration
            candidate_busy_end = candidate_start + service_duration + service_buffer

            # Чи вміщується послуга до кінця зміни
            if candidate_service_end <= end_work_dt:
                # Перевірка на майбутній час для сьогоднішнього дня
                is_future = True
                if booking_date == timezone.localdate() and candidate_start <= (
                    now + timedelta(minutes=15)
                ):
                    is_future = False

                # Перевірка 1: Перетин із зайнятими слотами
                has_conflict = False
                for b_start, b_end in busy_intervals:
                    if candidate_start < b_end and b_start < candidate_busy_end:
                        has_conflict = True
                        break

                if is_future and not has_conflict:
                    # Перевірка 2: Захист від «мертвого вікна» ДО цього слота
                    prev_busy_end = None
                    for b_start, b_end in busy_intervals:
                        if b_end <= candidate_start:
                            if prev_busy_end is None or b_end > prev_busy_end:
                                prev_busy_end = b_end

                    is_gap_safe = True
                    if prev_busy_end:
                        gap_before = (
                            candidate_start - prev_busy_end
                        ).total_seconds() / 60
                        # Якщо проміжок не стиковий (>10 хв) і менший за мінімальну послугу (<30 хв)
                        if 10 < gap_before < min_viable_gap:
                            is_gap_safe = False

                    # Перевірка 3: Захист від «мертвого вікна» ПІСЛЯ цього слота
                    next_busy_start = None
                    for b_start, b_end in busy_intervals:
                        if b_start >= candidate_busy_end:
                            if next_busy_start is None or b_start < next_busy_start:
                                next_busy_start = b_start

                    if next_busy_start:
                        gap_after = (
                            next_busy_start - candidate_busy_end
                        ).total_seconds() / 60
                        if 10 < gap_after < min_viable_gap:
                            is_gap_safe = False

                    if is_gap_safe:
                        slots.append(candidate_start.time().strftime("%H:%M"))

            current_dt += timedelta(minutes=15)

        return Response(
            {
                "date": date_str,
                "service_id": service.id,
                "service_duration": service.duration_minutes,
                "buffer_minutes": service.buffer_minutes,
                "slots": slots,
            }
        )


class BookingCreateView(generics.CreateAPIView):
    serializer_class = BookingCreateSerializer
    authentication_classes = []

    def perform_create(self, serializer):
        booking = serializer.save()
        send_booking_notification(booking)


class BookingCancelView(APIView):
    """
    Скасування запису за унікальним токеном.
    POST /api/cancel/<uuid:cancel_token>/
    """

    def post(self, request, cancel_token):
        lang = request.query_params.get("lang", "cs")

        try:
            booking = Booking.objects.get(cancel_token=cancel_token)
        except Booking.DoesNotExist:
            return Response(
                {"error": get_msg("booking_not_found", lang)},
                status=status.HTTP_404_NOT_FOUND,
            )

        if booking.status == Booking.Status.CANCELLED:
            return Response(
                {"detail": get_msg("already_cancelled", lang)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        booking_datetime = timezone.make_aware(
            datetime.combine(booking.date, booking.start_time)
        )
        if booking_datetime - timezone.now() < timedelta(hours=2):
            return Response(
                {"error": get_msg("cancel_too_late", lang)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        booking.status = Booking.Status.CANCELLED
        booking.save(update_fields=["status"])

        send_cancellation_notification(booking)

        return Response(
            {"detail": get_msg("cancel_success", lang)}, status=status.HTTP_200_OK
        )


class BookingPageView(TemplateView):
    """Головна сторінка онлайн-запису для клієнтів."""

    template_name = "booking.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["services"] = Service.objects.filter(is_active=True).order_by("price")
        return context
