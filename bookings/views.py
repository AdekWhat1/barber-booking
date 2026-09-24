from datetime import datetime, timedelta

from django.utils import timezone
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response

from notifications.services import (
    send_booking_notification,
    send_cancellation_notification,
)
from .models import Service, Booking
from .serializers import ServiceSerializer, BookingCreateSerializer
from .services import get_available_slots
from .messages import get_msg


class ServiceListView(generics.ListAPIView):
    queryset = Service.objects.filter(is_active=True)
    serializer_class = ServiceSerializer


class AvailableSlotsView(APIView):
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
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"error": get_msg("invalid_date_format", lang)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        slots = get_available_slots(date_obj, service_id)
        return Response({"date": date_str, "available_slots": slots})


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
