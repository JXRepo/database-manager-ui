from django.db import models
from django.contrib.auth.models import User

class Product(models.Model):
    """
    Store product information

    Returns
    -------
    str
        Product name
    """
    
    id    = models.AutoField(primary_key=True)
    name  = models.CharField(max_length = 100) 
    info  = models.CharField(max_length = 100, default = '')
    price = models.IntegerField(blank=True, null=True)

    def __str__(self):
        """
        Return product name

        Returns
        -------
        str
            Product name
        """
        return self.name


class JSONData(models.Model):
    """
    Store one unwrapped JSON data object

    Attributes
    ----------
    owner : User
        Owner of the data object
    data : dict
        Raw JSON object
    identifier_fingerprint : str
        Internal full digest for automatically assigned identifiers
    size_bytes : int
        Persisted UTF-8 byte size for the JSON object
    access_type : str
        Access level ("c" or "all")
    uploaded_at : datetime
        Upload timestamp
    """

    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    data = models.JSONField()
    identifier_fingerprint = models.CharField(
        max_length=64, blank=True, default="", db_index=True, editable=False,
    )
    size_bytes = models.PositiveBigIntegerField(default=0)
    access_type = models.CharField(max_length=10, default="c")
    shared_users = models.ManyToManyField(
        User,
        blank=True,
        related_name="shared_json_data",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        """
        Return a simple string representation

        Returns
        -------
        str
            Summary string
        """
        return f"{self.owner.username} - {self.access_type} - {self.id}"


class RateLimitBucket(models.Model):
    """
    Store one fixed-window rate-limit bucket

    Attributes
    ----------
    scope : str
        Rate-limit scope name
    identifier_hash : str
        HMAC hash of the persisted identifier
    window_seconds : int
        Window size in seconds
    window_id : int
        Fixed-window identifier
    count : int
        Number of consumed actions in the window
    expires_at : datetime
        Time when the bucket expires
    """

    scope = models.CharField(max_length=32)
    identifier_hash = models.CharField(max_length=64)
    window_seconds = models.PositiveIntegerField()
    window_id = models.BigIntegerField()
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("scope", "identifier_hash", "window_seconds", "window_id"),
                name="unique_rate_limit_bucket",
            ),
        ]

    def __str__(self):
        """
        Return a simple bucket summary
        """
        return (
            f"{self.scope} - {self.identifier_hash[:12]} - "
            f"{self.window_seconds} - {self.window_id}"
        )


class AccountProfile(models.Model):
    """
    Store optional research profile fields for one user

    Attributes
    ----------
    user : User
        Account that owns this profile.
    institution : str
        Optional institution name.
    orcid : str
        Unverified legacy ORCID text.
    authenticated_orcid : str or None
        Verified ORCID identity returned by authentication.
    orcid_authenticated_at : datetime or None
        Time when the ORCID identity was authenticated.
    orcid_disconnected_at : datetime or None
        Most recent disconnect time used to reject older linking callbacks.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    institution = models.CharField(max_length=255, blank=True)
    orcid = models.CharField(max_length=32, blank=True)
    authenticated_orcid = models.CharField(
        max_length=19,
        null=True,
        blank=True,
        unique=True,
        editable=False,
    )
    orcid_authenticated_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
    )
    orcid_disconnected_at = models.DateTimeField(
        null=True,
        blank=True,
        default=None,
        editable=False,
    )

    def __str__(self):
        """
        Return a simple profile summary
        """
        return f"{self.user.username} profile"


class DataNotification(models.Model):
    """
    Store one user notification

    Attributes
    ----------
    recipient : User
        User who receives the notification
    actor : User
        User who triggered the notification
    data_object : JSONData
        Data object related to the notification
    notification_type : str
        Notification category
    message : str
        User-facing notification text
    is_read : bool
        Whether the recipient has opened the notification
    created_at : datetime
        Notification creation timestamp
    """

    TYPE_SHARED_DATA = "shared_data"

    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="data_notifications",
    )
    actor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="sent_data_notifications",
    )
    data_object = models.ForeignKey(
        JSONData,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    notification_type = models.CharField(max_length=50, default=TYPE_SHARED_DATA)
    message = models.CharField(max_length=255)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("is_read", "-created_at")

    @property
    def display_title(self):
        """
        Return the related data object's best display title
        """
        data = self.data_object.data or {}
        return data.get("identifier") or data.get("title") or "Data object"

    def __str__(self):
        """
        Return a simple notification summary
        """
        return f"{self.recipient.username} - {self.notification_type} - {self.id}"
