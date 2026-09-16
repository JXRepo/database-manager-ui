from django.urls import path
from django.urls import reverse_lazy
from django.contrib.auth import views as auth_views
from . import views
from .auth_views import RateLimitedLoginView
from .credential_validation import validate_account_credentials
from .views import account_settings_view, register_view
from .forms import StyledPasswordChangeForm
from .views import upload_json_view
from .views import (
    json_data_list_view,
    json_data_detail_view,
    json_data_delete_view,
    json_data_export_view,
    json_data_sharing_view,
    notification_list_view,
    notification_mark_all_read_view,
    notification_open_view,
    share_view,
    shared_with_me_view,
    sharing_history_view,
    export_selected_search_results_view,
    export_selected_my_data_objects_view,
    delete_selected_my_data_objects_view,
    fair_assistant_ask_view,
    search_live_data_objects_view,
    search_view,
)

urlpatterns = [
    path("", views.index, name="index"),
    path("healthz/", views.healthz_view, name="healthz"),
    path("accounts/login/", RateLimitedLoginView.as_view()),
    path("accounts/register/", register_view),
    path(
        "accounts/validate-credentials/",
        validate_account_credentials,
        name="validate_account_credentials",
    ),
    path(
        "login/",
        RateLimitedLoginView.as_view(),
        name="login",
    ),
    path("login/orcid/", views.orcid_login_view, name="orcid_login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("register/", register_view, name="register"),
    path("settings/", account_settings_view, name="account_settings"),
    path("settings/orcid/connect/", views.orcid_connect_view, name="orcid_connect"),
    path("settings/orcid/disconnect/", views.orcid_disconnect_view, name="orcid_disconnect"),
    path("settings/orcid/setup/", views.orcid_setup_credentials_view, name="orcid_setup_credentials"),
    path("settings/orcid/callback/", views.orcid_callback_view, name="orcid_callback"),
    path(
        "password/change/",
        auth_views.PasswordChangeView.as_view(
            form_class=StyledPasswordChangeForm,
            template_name="accounts/password_change.html",
            success_url=reverse_lazy("password_change_done"),
        ),
        name="password_change",
    ),
    path(
        "password/change/done/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="accounts/password_change_done.html",
        ),
        name="password_change_done",
    ),
    path("upload/", upload_json_view, name="upload_json"),
    path("assistant/ask/", fair_assistant_ask_view, name="fair_assistant_ask"),
    path("search/", search_view, name="search"),
    path("search/live-data/", search_live_data_objects_view, name="search_live_data_objects"),
    path("search/export-selected/", export_selected_search_results_view, name="export_selected_search_results"),
    path("data-list/", json_data_list_view, name="json_data_list"),
    path("data-list/export-selected/", export_selected_my_data_objects_view, name="export_selected_my_data_objects"),
    path("data-list/delete-selected/", delete_selected_my_data_objects_view, name="delete_selected_my_data_objects"),
    path("share/", share_view, name="share"),
    path("shared-with-me/", shared_with_me_view, name="shared_with_me"),
    path("sharing-history/", sharing_history_view, name="sharing_history"),
    path("notifications/", notification_list_view, name="notification_list"),
    path("notifications/mark-all-read/", notification_mark_all_read_view, name="notification_mark_all_read"),
    path("notifications/<int:pk>/open/", notification_open_view, name="notification_open"),
    path("data-list/<int:pk>/", json_data_detail_view, name="json_data_detail"),
    path("data-list/<int:pk>/export/", json_data_export_view, name="json_data_export"),
    path("data-list/<int:pk>/sharing/", json_data_sharing_view, name="json_data_sharing"),
    path("data-list/<int:pk>/delete/", json_data_delete_view, name="json_data_delete"),
]
