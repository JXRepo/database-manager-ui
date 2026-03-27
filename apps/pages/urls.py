from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .views import register_view
from .forms import SignInForm
from .views import upload_json_view
from .views import json_data_list_view, json_data_detail_view, search_view

urlpatterns = [
    path("", views.index, name="index"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html",
            authentication_form=SignInForm,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("register/", register_view, name="register"),
    path("upload/", upload_json_view, name="upload_json"),
    path("search/", search_view, name="search"),
    path("data-list/", json_data_list_view, name="json_data_list"),
    path("data-list/<int:pk>/", json_data_detail_view, name="json_data_detail"),
]