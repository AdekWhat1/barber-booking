from datetime import datetime, timedelta, time

from django.db import IntegrityError, transaction
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView
from rest_framework import generics, status
from rest_framework.throttling import ScopedRateThrottle
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
    """Динамічна генерація слотів:

    - На вільні проміжки дня пропонуються рівні години (10:00, 11:00, 12:00...).
    - Після існуючого запису слот генерується рівно встик (тривалість + 10 хв
    буфер, наприклад 10:50).
    - Блокуються проміжки від 10 до 29 хвилин (мертві вікна).
    """

    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "slots_check"

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

        try:
            working_day = WorkingDay.objects.get(date=booking_date)
            if working_day.is_day_off:
                return Response({"slots": []})
        except WorkingDay.DoesNotExist:
            return Response({"slots": []})

        tz = timezone.get_current_timezone()
        day_start_dt = timezone.make_aware(
            datetime.combine(booking_date, working_day.start_time), tz
        )
        day_end_dt = timezone.make_aware(
            datetime.combine(booking_date, working_day.end_time), tz
        )
        now = timezone.localtime()

        confirmed_bookings = (
            Booking.objects.filter(date=booking_date)
            .exclude(status=Booking.Status.CANCELLED)
            .select_related("service")
            .order_by("start_time")
        )

        busy_intervals = []
        for b in confirmed_bookings:
            b_start = timezone.make_aware(
                datetime.combine(booking_date, b.start_time), tz
            )
            b_buffer = (
                b.service.buffer_minutes
                if (b.service and b.service.buffer_minutes is not None)
                else 10
            )

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

        service_dur = timedelta(minutes=service.duration_minutes)
        service_buf = timedelta(minutes=service.buffer_minutes)
        service_total = service_dur + service_buf
        min_viable_gap = 30

        slots = set()

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
                cand_hour_dt = timezone.make_aware(
                    datetime.combine(booking_date, time(curr_hour, 0)), tz
                )
                if w_start < cand_hour_dt < w_end:
                    candidates.append(cand_hour_dt)
                curr_hour += 1

            for cand in candidates:
                if booking_date == timezone.localdate() and cand <= (
                    now + timedelta(minutes=15)
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

                slots.add(cand.time().strftime("%H:%M"))

        return Response(
            {
                "date": date_str,
                "service_id": service.id,
                "service_duration": service.duration_minutes,
                "buffer_minutes": service.buffer_minutes,
                "slots": sorted(list(slots)),
            }
        )


class BookingCreateView(generics.CreateAPIView):
    """Створення бронювання з атомарним захистом від Race Conditions (подвійних записів)."""

    serializer_class = BookingCreateSerializer
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "booking_create"

    def create(self, request, *args, **kwargs):
        lang = request.query_params.get("lang", "cs")
        date_str = request.data.get("date")

        try:
            with transaction.atomic():
                if date_str:
                    WorkingDay.objects.select_for_update().filter(date=date_str).first()

                serializer = self.get_serializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                booking = serializer.save()

                transaction.on_commit(lambda: send_booking_notification(booking))

        except IntegrityError:
            return Response(
                {"error": get_msg("slot_already_taken", lang)},
                status=status.HTTP_409_CONFLICT,
            )

        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )


class BookingCancelView(APIView):
    """Безпечне скасування запису за унікальним токеном (ідемпотентне)."""

    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "cancel_attempt"

    def post(self, request, cancel_token):
        lang = request.query_params.get("lang", "cs")

        with transaction.atomic():
            booking = (
                Booking.objects.select_for_update()
                .filter(cancel_token=cancel_token)
                .first()
            )

            if not booking:
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
            if booking_datetime - timezone.now() < timedelta(hours=24):
                return Response(
                    {"error": get_msg("cancel_too_late", lang)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            booking.status = Booking.Status.CANCELLED
            booking.save(update_fields=["status"])

            transaction.on_commit(lambda: send_cancellation_notification(booking))

        return Response(
            {"detail": get_msg("cancel_success", lang)},
            status=status.HTTP_200_OK,
        )


class BookingCancelPageView(View):
    """Веб-сторінка скасування: блокує скасування менше ніж за 24 години."""

    def get(self, request, cancel_token):
        booking = get_object_or_404(Booking, cancel_token=cancel_token)
        booking_datetime = timezone.make_aware(
            datetime.combine(booking.date, booking.start_time)
        )

        too_late = (booking_datetime - timezone.now()) < timedelta(hours=24)

        return render(
            request,
            "cancel_booking.html",
            {
                "booking": booking,
                "too_late": too_late,
            },
        )

    def post(self, request, cancel_token):
        booking = get_object_or_404(Booking, cancel_token=cancel_token)
        booking_datetime = timezone.make_aware(
            datetime.combine(booking.date, booking.start_time)
        )

        if (booking_datetime - timezone.now()) < timedelta(hours=24):
            return render(
                request,
                "cancel_booking.html",
                {
                    "booking": booking,
                    "too_late": True,
                },
            )

        if booking.status != Booking.Status.CANCELLED:
            booking.status = Booking.Status.CANCELLED
            booking.save(update_fields=["status"])
            try:
                send_cancellation_notification(booking)
            except Exception:
                pass

        return render(
            request,
            "cancel_booking.html",
            {"booking": booking, "success": True},
        )


class BookingPageView(TemplateView):
    """Головна сторінка онлайн-запису для клієнтів."""

    template_name = "booking.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["services"] = Service.objects.filter(is_active=True).order_by("price")
        return context
