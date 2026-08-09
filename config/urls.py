"""core URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

from apps.pages.auth_views import (
    pilot_disabled_auth_view,
    rate_limited_admin_login,
)

urlpatterns = [
    path('', include('apps.pages.urls')),
    path('charts/', include('apps.charts.urls')),
    path(
        "accounts/password-reset/",
        pilot_disabled_auth_view,
        name="pilot_password_reset_disabled",
    ),
    path(
        "accounts/password-reset-done/",
        pilot_disabled_auth_view,
        name="pilot_password_reset_done_disabled",
    ),
    path(
        "accounts/password-reset-confirm/<uidb64>/<token>/",
        pilot_disabled_auth_view,
        name="pilot_password_reset_confirm_disabled",
    ),
    path(
        "accounts/password-reset-complete/",
        pilot_disabled_auth_view,
        name="pilot_password_reset_complete_disabled",
    ),
    path(
        "admin/login/",
        rate_limited_admin_login,
        name="pilot_admin_login",
    ),
    path("", include('admin_datta.urls')),
    path("admin/", admin.site.urls),
]
