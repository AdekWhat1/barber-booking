from django.urls import path
from .views import ServiceListView, AvailableSlotsView, BookingCreateView

app_name = "bookings"

urlpatterns = [
    path("services/", ServiceListView.as_view(), name="service-list"),
    path("available-slots/", AvailableSlotsView.as_view(), name="available-slots"),
    path("book/", BookingCreateView.as_view(), name="booking-create"),
]
