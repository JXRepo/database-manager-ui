from .models import DataNotification


def shared_data_notifications(request):
    """
    Return shared data notification data for the top navigation
    """
    user = getattr(request, "user", None)

    if user is None or not user.is_authenticated:
        return {
            "shared_data_count": 0,
            "shared_data_notifications": [],
        }

    notification_queryset = (
        DataNotification.objects
        .filter(
            recipient=user,
            notification_type=DataNotification.TYPE_SHARED_DATA,
            data_object__access_type="c",
        )
        .exclude(data_object__owner=user)
        .select_related("actor", "data_object", "data_object__owner")
        .order_by("is_read", "-created_at")
    )

    notifications = []

    for notification in notification_queryset[:5]:
        notifications.append(
            {
                "notification_id": notification.id,
                "data_object_id": notification.data_object_id,
                "id": notification.data_object_id,
                "title": notification.display_title,
                "owner": notification.actor.username,
                "message": notification.message,
                "is_read": notification.is_read,
                "created_at": notification.created_at,
                "uploaded_at": notification.created_at,
            }
        )

    return {
        "shared_data_count": notification_queryset.filter(is_read=False).count(),
        "shared_data_notifications": notifications,
    }
