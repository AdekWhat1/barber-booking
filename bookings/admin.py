from django.contrib import admin
from .models import Service, WorkingDay, Booking


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name_cs", "name_uk", "price", "duration_minutes", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name_cs", "name_uk")
    list_editable = ("price", "is_active")


@admin.register(WorkingDay)
class WorkingDayAdmin(admin.ModelAdmin):
    list_display = ("date", "start_time", "end_time", "is_day_off")
    list_filter = ("is_day_off",)
    ordering = ("date",)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        "client_name",
        "client_phone",
        "service",
        "date",
        "start_time",
        "end_time",
        "status",
    )
    list_filter = ("status", "date")
    search_fields = ("client_name", "client_phone")
    date_hierarchy = "date"
    readonly_fields = ("created_at",)
