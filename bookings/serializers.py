from datetime import datetime, timedelta
from django.utils import timezone
from rest_framework import serializers

from .models import Service, WorkingDay, Booking
from .messages import get_msg


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = [
            "id",
            "name_cs",
            "name_uk",
            "description_cs",
            "description_uk",
            "price",
            "duration_minutes",
        ]


class BookingCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Booking
        fields = [
            "id",
            "cancel_token",
            "service",
            "client_name",
            "client_phone",
            "date",
            "start_time",
        ]
        read_only_fields = ["id", "cancel_token"]

    def _get_lang(self) -> str:
        request = self.context.get("request")
        if not request:
            return "cs"

        lang_param = request.query_params.get("lang")
        if lang_param in ["uk", "cs"]:
            return lang_param

        accept_lang = request.headers.get("Accept-Language", "")
        if "uk" in accept_lang.lower():
            return "uk"

        return "cs"

    def validate_date(self, value):
        lang = self._get_lang()
        today = timezone.localdate()
        if value < today:
            raise serializers.ValidationError(get_msg("past_date", lang))
        return value

    def validate(self, attrs):
        lang = self._get_lang()
        service = attrs.get("service")
        date = attrs.get("date")
        start_time = attrs.get("start_time")

        try:
            working_day = WorkingDay.objects.get(date=date)
        except WorkingDay.DoesNotExist:
            raise serializers.ValidationError({"date": get_msg("no_schedule", lang)})

        if working_day.is_day_off:
            raise serializers.ValidationError({"date": get_msg("day_off", lang)})

        dummy_date = datetime.today().date()
        start_dt = datetime.combine(dummy_date, start_time)
        end_dt = start_dt + timedelta(minutes=service.duration_minutes)
        calculated_end_time = end_dt.time()

        if (
            start_time < working_day.start_time
            or calculated_end_time > working_day.end_time
        ):
            raise serializers.ValidationError(
                {
                    "start_time": get_msg(
                        "outside_working_hours",
                        lang,
                        start=working_day.start_time.strftime("%H:%M"),
                        end=working_day.end_time.strftime("%H:%M"),
                    )
                }
            )

        overlapping_bookings = Booking.objects.filter(
            date=date,
            status=Booking.Status.CONFIRMED,
            start_time__lt=calculated_end_time,
            end_time__gt=start_time,
        )

        if overlapping_bookings.exists():
            raise serializers.ValidationError(
                {"start_time": get_msg("slot_occupied", lang)}
            )

        attrs["end_time"] = calculated_end_time
        return attrs
