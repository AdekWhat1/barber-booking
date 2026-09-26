from datetime import datetime, timedelta

from django.utils import timezone
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
    """
    Генерація вільних віконець із 15-хвилинним кроком
    з урахуванням тривалості послуги та буферного часу (buffer_minutes).
    GET /api/available-slots/?date=YYYY-MM-DD&service_id=1&lang=uk
    """

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

        confirmed_bookings = (
            Booking.objects.filter(
                date=booking_date,
                status=Booking.Status.CONFIRMED,
            )
            .select_related("service")
            .only("start_time", "end_time", "service__buffer_minutes")
        )

        tz = timezone.get_current_timezone()

        busy_intervals = []
        for b in confirmed_bookings:
            b_start = timezone.make_aware(
                datetime.combine(booking_date, b.start_time), tz
            )
            b_buffer = b.service.buffer_minutes if b.service else 10
            b_end_with_buffer = timezone.make_aware(
                datetime.combine(booking_date, b.end_time), tz
            ) + timedelta(minutes=b_buffer)
            busy_intervals.append((b_start, b_end_with_buffer))

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

        while current_dt < end_work_dt:
            candidate_start = current_dt
            candidate_service_end = candidate_start + service_duration
            candidate_busy_end = candidate_start + service_duration + service_buffer

            if candidate_service_end <= end_work_dt:
                is_future = True
                if booking_date == timezone.localdate() and candidate_start <= (
                    now + timedelta(minutes=15)
                ):
                    is_future = False

                has_conflict = False
                for b_start, b_end in busy_intervals:
                    if candidate_start < b_end and b_start < candidate_busy_end:
                        has_conflict = True
                        break

                if is_future and not has_conflict:
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
