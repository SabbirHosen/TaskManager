from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import CustomUser, OTP


class CustomUserAdmin(BaseUserAdmin):
    model = CustomUser
    list_display = ('id','email', 'first_name', 'last_name', 'is_staff', 'is_active', 'is_email_verified', 'date_joined')
    list_filter = ('is_staff', 'is_active', 'is_email_verified')
    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('date_joined',)
    readonly_fields = ('date_joined',)  # Mark date_joined as read-only
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Personal Info'), {'fields': ('first_name', 'last_name', 'profile_pic')}),
        (_('Permissions'),
         {'fields': ('is_active', 'is_staff', 'is_superuser', 'is_email_verified', 'groups', 'user_permissions')}),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'is_staff', 'is_active')}
         ),
    )


class OTPAdmin(admin.ModelAdmin):
    model = OTP
    list_display = ('user', 'otp', 'created_at')
    search_fields = ('user__email', 'otp')
    ordering = ('-created_at',)


# Register models with the admin site
admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(OTP, OTPAdmin)
