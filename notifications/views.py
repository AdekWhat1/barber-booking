from rest_framework import generics

from bookings.serializers import BookingCreateSerializer
from notifications.services import send_booking_notification


class BookingCreateView(generics.CreateAPIView):
    serializer_class = BookingCreateSerializer

    def perform_create(self, serializer):
        booking = serializer.save()
        send_booking_notification(booking)
