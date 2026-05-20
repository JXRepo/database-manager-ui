from .models import JSONData


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

    shared_objects = (
        JSONData.objects
        .filter(shared_users=user)
        .exclude(owner=user)
        .select_related("owner")
        .order_by("-uploaded_at")
    )

    notifications = []

    for obj in shared_objects[:5]:
        data = obj.data or {}
        notifications.append(
            {
                "id": obj.id,
                "title": data.get("identifier") or data.get("title") or "Data object",
                "owner": obj.owner.username,
                "uploaded_at": obj.uploaded_at,
            }
        )

    return {
        "shared_data_count": shared_objects.count(),
        "shared_data_notifications": notifications,
    }
