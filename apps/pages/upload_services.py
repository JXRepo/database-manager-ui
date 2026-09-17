import hashlib
import json
import math
from dataclasses import dataclass
from typing import Sequence

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Sum

from apps.dyn_api.helpers import REQUIRED_TOP_LEVEL_FIELDS

from .models import DataNotification, JSONData
from .notifications import build_shared_data_notification_message

INVALID_UNICODE_UPLOAD_MESSAGE = "Uploaded JSON contains invalid Unicode text."


class UploadResourceLimitError(Exception):
    """
    Signal that an upload exceeds a request resource limit
    """


class UploadQuotaExceeded(UploadResourceLimitError):
    """
    Signal that an upload exceeds the owner's stored byte quota
    """


class UploadIdentifierConflict(Exception):
    """
    Carry identifiers that conflict during the transactional recheck
    """

    def __init__(self, identifiers: Sequence[str]):
        self.identifiers = tuple(dict.fromkeys(identifiers))
        super().__init__(*self.identifiers)


@dataclass(frozen=True)
class PreparedJSONData:
    """
    Hold one validated JSON object until the request is ready to save
    """

    data: dict
    access_type: str
    shared_users: tuple[User, ...]
    size_bytes: int


def generate_data_identifier(data: dict) -> str:
    """
    Hash the required metadata of one validated data object

    Following Ronak Shoghi's MiMeDat content based identifier approach, this
    uses required fields only. A canonical mapping preserves field boundaries,
    zero and false values; a full SHA256 digest avoids an eight digit hash.

    Parameters
    ----------
    data : dict
        Object that has passed required field and numeric validation.

    Returns
    -------
    str
        Deterministic 64 character hexadecimal identifier.
    """
    content = {}
    for field in REQUIRED_TOP_LEVEL_FIELDS:
        content[field] = data[field]
    encoded = json.dumps(
        content, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_json_size(value: object) -> int:
    """
    Return the compact UTF8 JSON byte size
    """
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except UnicodeEncodeError as error:
        raise UploadResourceLimitError(
            INVALID_UNICODE_UPLOAD_MESSAGE
        ) from error

    return len(encoded)


def validate_upload_files(files: Sequence[UploadedFile]) -> None:
    """
    Validate request file count and byte limits before parsing
    """
    if len(files) > settings.PILOT_MAX_UPLOAD_FILES:
        raise UploadResourceLimitError(
            f"You can upload up to {settings.PILOT_MAX_UPLOAD_FILES} JSON files at once."
        )

    total_size = 0

    for uploaded_file in files:
        file_size = uploaded_file.size
        file_name = uploaded_file.name or "Uploaded file"

        if file_size > settings.PILOT_MAX_UPLOAD_FILE_BYTES:
            raise UploadResourceLimitError(
                f"{file_name} exceeds the per file upload size limit."
            )

        total_size += file_size

    if total_size > settings.PILOT_MAX_UPLOAD_REQUEST_BYTES:
        raise UploadResourceLimitError(
            "The combined files exceed the upload request size limit."
        )


def validate_json_depth(value: object) -> None:
    """
    Validate JSON container depth and finite numeric values
    """
    pending = [(value, 0)]

    while pending:
        current, parent_depth = pending.pop()

        if isinstance(current, float) and not math.isfinite(current):
            raise UploadResourceLimitError(
                "Uploaded JSON cannot contain nonfinite numeric values."
            )

        if not isinstance(current, (dict, list)):
            continue

        current_depth = parent_depth + 1

        if current_depth > settings.PILOT_MAX_JSON_DEPTH:
            raise UploadResourceLimitError(
                "Uploaded JSON exceeds the maximum container depth."
            )

        if isinstance(current, dict):
            children = current.values()
        else:
            children = current

        for child in children:
            pending.append((child, current_depth))


def save_prepared_json_data(
    owner: User,
    objects: list[PreparedJSONData],
) -> list[JSONData]:
    """
    Atomically save prepared objects inside the owner's live quota
    """
    incoming_size = sum(item.size_bytes for item in objects)

    with transaction.atomic():
        global_lock_user = (
            User.objects.select_for_update()
            .order_by("pk")
            .first()
        )

        if global_lock_user is None:
            raise User.DoesNotExist

        if global_lock_user.pk == owner.pk:
            locked_owner = global_lock_user
        else:
            locked_owner = User.objects.select_for_update().get(pk=owner.pk)

        conflicts = []
        seen_identifiers = set()

        for prepared in objects:
            identifier = str(prepared.data.get("identifier", "")).strip()

            if identifier in seen_identifiers:
                conflicts.append(identifier)
            elif JSONData.objects.filter(
                data__identifier=identifier
            ).exists():
                conflicts.append(identifier)

            seen_identifiers.add(identifier)

        if conflicts:
            raise UploadIdentifierConflict(conflicts)

        used_size = (
            JSONData.objects.filter(owner=locked_owner).aggregate(
                total=Sum("size_bytes")
            )["total"]
            or 0
        )

        if used_size + incoming_size > settings.PILOT_MAX_USER_JSON_BYTES:
            raise UploadQuotaExceeded(
                "Upload quota exceeded. Delete existing data before uploading more."
            )

        saved_objects = []

        for prepared in objects:
            data_object = JSONData.objects.create(
                owner=locked_owner,
                data=prepared.data,
                access_type=prepared.access_type,
                size_bytes=prepared.size_bytes,
            )

            if prepared.access_type == "c" and prepared.shared_users:
                data_object.shared_users.add(*prepared.shared_users)

                for recipient in prepared.shared_users:
                    if recipient.pk == locked_owner.pk:
                        continue

                    title = (
                        prepared.data.get("identifier")
                        or prepared.data.get("title")
                        or "Data object"
                    )
                    DataNotification.objects.create(
                        recipient=recipient,
                        actor=locked_owner,
                        data_object=data_object,
                        notification_type=DataNotification.TYPE_SHARED_DATA,
                        message=build_shared_data_notification_message(
                            locked_owner,
                            title,
                        ),
                    )

            saved_objects.append(data_object)

        return saved_objects
