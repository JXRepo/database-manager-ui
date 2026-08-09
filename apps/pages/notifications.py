from .models import DataNotification


def build_shared_data_notification_message(actor, display_title):
    """
    Build a bounded message for one shared data notification

    The actor and surrounding message stay intact while only the data object's
    display title is shortened to the model field budget.

    Parameters
    ----------
    actor : User
        User who shared the data object.
    display_title : object
        Identifier or title displayed for the data object.

    Returns
    -------
    str
        Notification message no longer than the model field limit.
    """
    prefix = f"{actor.username} shared "
    suffix = " with you."
    maximum_length = DataNotification._meta.get_field("message").max_length
    title_budget = maximum_length - len(prefix) - len(suffix)
    title = str(display_title)

    return f"{prefix}{title[:title_budget]}{suffix}"
