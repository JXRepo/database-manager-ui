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
    access_type : str
        Access level ("c" or "all")
    uploaded_at : datetime
        Upload timestamp
    """

    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    data = models.JSONField()
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
        Optional ORCID identifier.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    institution = models.CharField(max_length=255, blank=True)
    orcid = models.CharField(max_length=32, blank=True)

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
