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
