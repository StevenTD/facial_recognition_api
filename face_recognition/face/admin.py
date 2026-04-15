from django.contrib import admin
from django.utils.html import format_html
from .models import User

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'is_staff', 'get_face_image', 'created_at')
    readonly_fields = ('get_face_image',)

    def get_face_image(self, obj):
        if obj.face_image:
            return format_html('<img src="{}" width="50" height="50" style="border-radius: 50%;" />', obj.face_image.url)
        return "No Image"
    get_face_image.short_description = 'Face Image preview'
