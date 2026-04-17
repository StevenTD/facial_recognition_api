from django.contrib import admin
from django.utils.html import format_html
from .models import User, Face, AttendanceLog

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'is_staff', 'created_at')

@admin.register(Face)
class FaceAdmin(admin.ModelAdmin):
    list_display = ('username', 'get_face_image', 'user', 'created_at')
    readonly_fields = ('get_face_image',)

    def get_face_image(self, obj):
        if obj.face_image:
            return format_html('<img src="{}" width="50" height="50" style="border-radius: 50%;" />', obj.face_image.url)
        return "No Image"
    get_face_image.short_description = 'Face Image preview'

@admin.register(AttendanceLog)
class AttendanceLogAdmin(admin.ModelAdmin):
    list_display = ('username', 'action', 'timestamp', 'get_captured_image')
    list_filter = ('action', 'timestamp', 'face')
    search_fields = ('username',)
    readonly_fields = ('get_captured_image',)

    def get_captured_image(self, obj):
        if obj.captured_image:
            return format_html('<img src="{}" width="50" height="50" style="border-radius: 50%;" />', obj.captured_image.url)
        return "No Image"
    get_captured_image.short_description = 'Captured Face preview'
