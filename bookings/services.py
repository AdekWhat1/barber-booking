from datetime import datetime, timedelta, time
from django.utils import timezone
from .models import WorkingDay, Booking, Service


def get_available_slots(date_obj, service_id, slot_step_minutes=30):
    """
    Генерує список доступних часів початку процедури (наприклад, ['10:00', '10:30', '11:00'])
    з урахуванням робочих годин, тривалості послуги та вже зайнятих слотів.
    """
    try:
        service = Service.objects.get(id=service_id, is_active=True)
    except Service.DoesNotExist:
        return []

    try:
        working_day = WorkingDay.objects.get(date=date_obj)
    except WorkingDay.DoesNotExist:
        return []

    if working_day.is_day_off:
        return []

    existing_bookings = list(
        Booking.objects.filter(date=date_obj, status=Booking.Status.CONFIRMED).values(
            "start_time", "end_time"
        )
    )

    duration = timedelta(minutes=service.duration_minutes)
    step = timedelta(minutes=slot_step_minutes)

    current_dt = datetime.combine(date_obj, working_day.start_time)
    end_dt = datetime.combine(date_obj, working_day.end_time)

    available_slots = []
    now = timezone.localtime()

    while current_dt + duration <= end_dt:
        slot_start_time = current_dt.time()
        slot_end_time = (current_dt + duration).time()

        if date_obj == timezone.localdate() and current_dt <= now:
            current_dt += step
            continue

        is_occupied = False
        for b in existing_bookings:
            if slot_start_time < b["end_time"] and slot_end_time > b["start_time"]:
                is_occupied = True
                break

        if not is_occupied:
            available_slots.append(slot_start_time.strftime("%H:%M"))

        current_dt += step

    return available_slots
