import uuid
from datetime import datetime, timedelta
from django.db import models


class Service(models.Model):
    name_cs = models.CharField(max_length=150, verbose_name="Назва (CS)")
    description_cs = models.TextField(blank=True, verbose_name="Опис (CS)")

    name_uk = models.CharField(max_length=150, blank=True, verbose_name="Назва (UK)")
    description_uk = models.TextField(blank=True, verbose_name="Опис (UK)")

    price = models.DecimalField(
        max_digits=8, decimal_places=0, verbose_name="Ціна (Kč)"
    )
    duration_minutes = models.PositiveIntegerField(
        default=45,
        verbose_name="Тривалість (у хвилинах)",
        help_text="Скільки хвилин триває процедура (наприклад, 30, 45, 60)",
    )
    is_active = models.BooleanField(default=True, verbose_name="Активна послуга")

    class Meta:
        verbose_name = "Послуга"
        verbose_name_plural = "Послуги"
        ordering = ["price"]

    def __str__(self):
        return f"{self.name_cs} ({self.duration_minutes} хв) — {self.price} Kč"

    def get_name(self, lang="cs"):
        if lang == "uk" and self.name_uk:
            return self.name_uk
        return self.name_cs


class WorkingDay(models.Model):
    date = models.DateField(unique=True, verbose_name="Дата")
    start_time = models.TimeField(verbose_name="Початок роботи")
    end_time = models.TimeField(verbose_name="Кінець роботи")
    is_day_off = models.BooleanField(default=False, verbose_name="Вихідний день")

    class Meta:
        verbose_name = "Робочий день"
        verbose_name_plural = "Робочі дні"
        ordering = ["date"]

    def __str__(self):
        if self.is_day_off:
            return f"{self.date}: Вихідний"
        return f"{self.date}: {self.start_time.strftime('%H:%M')} - {self.end_time.strftime('%H:%M')}"


class Booking(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Підтверджено"
        CANCELLED = "cancelled", "Скасовано"

    cancel_token = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True, verbose_name="Токен скасування"
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.PROTECT,
        related_name="bookings",
        verbose_name="Послуга",
    )
    client_name = models.CharField(max_length=100, verbose_name="Ім'я клієнта")
    client_phone = models.CharField(max_length=20, verbose_name="Телефон клієнта")
    date = models.DateField(verbose_name="Дата візиту")
    start_time = models.TimeField(verbose_name="Час початку")
    end_time = models.TimeField(verbose_name="Час закінчення")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CONFIRMED,
        verbose_name="Статус",
    )
    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Дата створення запису"
    )

    class Meta:
        verbose_name = "Запис"
        verbose_name_plural = "Записи"
        ordering = ["-date", "-start_time"]

    def __str__(self):
        return f"{self.date} {self.start_time.strftime('%H:%M')} — {self.client_name} ({self.service.name_cs})"

    def save(self, *args, **kwargs):
        if not self.end_time and self.start_time and self.service:
            dummy_date = datetime.today().date()
            start_dt = datetime.combine(dummy_date, self.start_time)
            end_dt = start_dt + timedelta(minutes=self.service.duration_minutes)
            self.end_time = end_dt.time()
        super().save(*args, **kwargs)
