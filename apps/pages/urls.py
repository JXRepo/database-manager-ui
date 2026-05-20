from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .views import register_view
from .forms import SignInForm
from .views import upload_json_view
from .views import (
    json_data_list_view,
    json_data_detail_view,
    json_data_delete_view,
    json_data_export_view,
    json_data_sharing_view,
    shared_with_me_view,
    export_selected_search_results_view,
    search_view,
)

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
    path("search/export-selected/", export_selected_search_results_view, name="export_selected_search_results"),
    path("data-list/", json_data_list_view, name="json_data_list"),
    path("shared-with-me/", shared_with_me_view, name="shared_with_me"),
    path("data-list/<int:pk>/", json_data_detail_view, name="json_data_detail"),
    path("data-list/<int:pk>/export/", json_data_export_view, name="json_data_export"),
    path("data-list/<int:pk>/sharing/", json_data_sharing_view, name="json_data_sharing"),
    path("data-list/<int:pk>/delete/", json_data_delete_view, name="json_data_delete"),
]
