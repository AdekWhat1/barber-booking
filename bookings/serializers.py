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
            "end_time",
        ]
        read_only_fields = ["id", "cancel_token", "end_time"]

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
        booking_date = attrs.get("date")
        start_time = attrs.get("start_time")
        service = attrs.get("service")

        try:
            working_day = WorkingDay.objects.get(date=booking_date)
            if working_day.is_day_off:
                raise serializers.ValidationError(
                    get_msg("day_off", lang) or "Цей день є вихідним у майстра."
                )
        except WorkingDay.DoesNotExist:
            raise serializers.ValidationError(
                get_msg("schedule_not_found", lang)
                or "Графік на цю дату ще не сформовано."
            )

        tz = timezone.get_current_timezone()
        candidate_start = timezone.make_aware(
            datetime.combine(booking_date, start_time), tz
        )
        candidate_service_end = candidate_start + timedelta(
            minutes=service.duration_minutes
        )
        candidate_busy_end = candidate_start + timedelta(
            minutes=service.duration_minutes + service.buffer_minutes
        )

        if (
            booking_date == timezone.localdate()
            and candidate_start <= timezone.localtime()
        ):
            raise serializers.ValidationError(
                get_msg("past_time", lang)
                or "Неможливо записатися на час, що вже минув."
            )

        end_work_dt = timezone.make_aware(
            datetime.combine(booking_date, working_day.end_time), tz
        )
        start_work_dt = timezone.make_aware(
            datetime.combine(booking_date, working_day.start_time), tz
        )

        if candidate_start < start_work_dt or candidate_service_end > end_work_dt:
            raise serializers.ValidationError(
                get_msg("outside_working_hours", lang)
                or "Обраний час виходить за межі робочого дня."
            )

        existing_bookings = Booking.objects.filter(
            date=booking_date,
            status=Booking.Status.CONFIRMED,
        ).select_related("service")

        for b in existing_bookings:
            b_start = timezone.make_aware(
                datetime.combine(booking_date, b.start_time), tz
            )
            b_buffer = b.service.buffer_minutes if b.service else 10
            b_busy_end = timezone.make_aware(
                datetime.combine(booking_date, b.end_time), tz
            ) + timedelta(minutes=b_buffer)

            if candidate_start < b_busy_end and b_start < candidate_busy_end:
                raise serializers.ValidationError(
                    get_msg("slot_occupied", lang)
                    or "Цей часовий слот (або перерва майстра) вже зайнятий іншим записом."
                )

        attrs["end_time"] = candidate_service_end.time()
        return attrs
