import hashlib
import json
import math
from contextlib import closing
from dataclasses import dataclass
from typing import Sequence

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Q, Sum

from apps.dyn_api.helpers import REQUIRED_TOP_LEVEL_FIELDS
from apps.dyn_api.metadata_compat import field_value, identifier_lookup

from .models import DataNotification, JSONData
from .notifications import build_shared_data_notification_message

INVALID_UNICODE_UPLOAD_MESSAGE = "Uploaded JSON contains invalid Unicode text."


class UploadResourceLimitError(Exception):
    """
    Signal that an upload exceeds a request resource limit
    """

    def __init__(self, message: str, *, category: str = "save_error"):
        """
        Keep the problem category separate from its user facing message

        Parameters
        ----------
        message : str
            Description of the rejected data or resource limit.
        category : str, optional
            Feedback group for errors that affect a single file or object.
        """
        self.category = category
        super().__init__(message)


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


def _remove_empty_entries(data):
    """
    Reproduce the template's cleanup on a separate value used only for hashing

    Ronak's list cleanup also removes falsy items, including zero and false.
    Stored and exported JSON must keep those values, so this never edits data.

    Parameters
    ----------
    data : object
        Original JSON value.

    Returns
    -------
    object
        Value cleaned as in MiMeDat metadata_template.py.
    """
    if isinstance(data, dict):
        new_dict = {}
        for key, value in data.items():
            cleaned_value = _remove_empty_entries(value)
            if cleaned_value is not None and cleaned_value != {} and cleaned_value != []:
                new_dict[key] = cleaned_value
        return new_dict if new_dict else None
    elif isinstance(data, list):
        cleaned_list = filter(None, (_remove_empty_entries(item) for item in data))
        return [item for item in cleaned_list if item != {} and item != []]
    else:
        return data if data is not None else None


def generate_data_identifier(data: dict) -> str:
    """
    Generate exactly the eight character MD5 identifier from Ronak's template

    Use the original field names and values, template cleanup, mandatory field
    order and default JSON serialization. Database contents never affect the ID.
    Source: https://github.com/Ronakshoghi/MiMeDat/blob/main/metadata_template.py

    Parameters
    ----------
    data : dict
        Validated uploaded object.

    Returns
    -------
    str
        First eight lowercase hexadecimal characters of the MD5 digest.
    """
    cleaned_data = _remove_empty_entries(data)
    hash_string = ""
    for field in REQUIRED_TOP_LEVEL_FIELDS:
        value = cleaned_data.get(field)
        if value is not None:
            hash_string += json.dumps(value, sort_keys=True)
    return hashlib.md5(hash_string.encode()).hexdigest()[:8]


def identifier_query(identifier):
    """
    Match an identifier regardless of its original metadata field spelling

    Parameters
    ----------
    identifier : str
        Exact identifier value, without case folding.

    Returns
    -------
    Q
        Indexed lookup with a fallback for older canonical records.
    """
    query = Q(data__identifier=identifier)
    digest = identifier_lookup(identifier)
    if digest:
        query |= Q(identifier_lookup=digest)
    return query


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
            INVALID_UNICODE_UPLOAD_MESSAGE, category="invalid_unicode",
        ) from error

    return len(encoded)


def validate_upload_files(files: Sequence[UploadedFile], *, check_file_sizes: bool = True) -> None:
    """
    Validate request file count and byte limits before parsing

    Parameters
    ----------
    files : sequence of UploadedFile
        Files included in the submission.
    check_file_sizes : bool, optional
        Check individual sizes as well as request limits. The upload view
        checks individual files separately so one oversized file can be rejected.
    """
    if len(files) > settings.PILOT_MAX_UPLOAD_FILES:
        raise UploadResourceLimitError(
            f"You can upload up to {settings.PILOT_MAX_UPLOAD_FILES} JSON files at once."
        )

    total_size = 0

    for uploaded_file in files:
        file_size = uploaded_file.size
        file_name = uploaded_file.name or "Uploaded file"

        if check_file_sizes and file_size > settings.PILOT_MAX_UPLOAD_FILE_BYTES:
            raise UploadResourceLimitError(
                f"{file_name} exceeds the per file upload size limit.",
                category="file_size",
            )

        total_size += file_size

    if total_size > settings.PILOT_MAX_UPLOAD_REQUEST_BYTES:
        raise UploadResourceLimitError(
            "The combined files exceed the upload request size limit."
        )


def validate_json_depth(value: object, *, initial_depth: int = 0) -> None:
    """
    Validate JSON container depth and finite numeric values

    Iterators retain only the current path through nested containers, avoiding
    a separate work item for every value in a large numerical array.

    Parameters
    ----------
    value : object
        Parsed JSON data to inspect.
    initial_depth : int, optional
        Number of surrounding containers when validating an unwrapped object.
    """
    pending = [(iter((value,)), initial_depth)]

    while pending:
        children, parent_depth = pending[-1]
        try:
            current = next(children)
        except StopIteration:
            pending.pop()
            continue

        if isinstance(current, float) and not math.isfinite(current):
            raise UploadResourceLimitError(
                "Uploaded JSON cannot contain nonfinite numeric values.",
                category="invalid_number",
            )

        if not isinstance(current, (dict, list)):
            continue

        current_depth = parent_depth + 1

        if current_depth > settings.PILOT_MAX_JSON_DEPTH:
            raise UploadResourceLimitError(
                "Uploaded JSON exceeds the maximum container depth.",
                category="json_depth",
            )

        if isinstance(current, dict):
            children = current.values()
        else:
            children = current

        pending.append((iter(children), current_depth))


def consume_upload_progress(events, progress=None):
    """
    Run an upload iterator to completion and close it if an observer interrupts

    Parameters
    ----------
    events : generator
        Processing iterator yielding stage, completed count and total count.
    progress : callable, optional
        Observer for each actual progress event.

    Returns
    -------
    object
        The iterator's final return value.
    """
    with closing(events):
        while True:
            try:
                event = next(events)
            except StopIteration as finished:
                return finished.value
            if progress is not None:
                progress(*event)


def save_prepared_json_data(
    owner: User,
    objects: list[PreparedJSONData],
    progress=None,
) -> list[JSONData]:
    """
    Atomically save prepared objects inside the owner's live quota

    Parameters
    ----------
    owner : User
        Authenticated uploader.
    objects : list of PreparedJSONData
        Validated data awaiting the final identifier and quota recheck.
    progress : callable, optional
        Observer receiving actual completed save work and the total. These
        counts do not confirm persistence until the outer transaction commits.

    Returns
    -------
    list of JSONData
        Created records, still subject to the caller's outer transaction.
    """
    return consume_upload_progress(iter_save_prepared_json_data(owner, objects), progress)


def iter_save_prepared_json_data(owner, objects):
    """
    Yield provisional object save counts within one atomic file transaction

    Closing the iterator before completion rolls back its objects and notifications.

    Parameters
    ----------
    owner : User
        Authenticated uploader.
    objects : list of PreparedJSONData
        Validated data awaiting final identifier and quota checks.

    Yields
    ------
    tuple
        Saving stage, completed object count and total count.

    Returns
    -------
    list of JSONData
        Created records, still subject to any caller's outer transaction.
    """
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
            identifier = str(field_value(prepared.data, "identifier", "")).strip()

            if identifier in seen_identifiers:
                conflicts.append(identifier)
            elif JSONData.objects.filter(
                identifier_query(identifier)
            ).exists():
                conflicts.append(identifier)

            seen_identifiers.add(identifier)

        if conflicts:
            raise UploadIdentifierConflict(conflicts)

        incoming_size = sum(item.size_bytes for item in objects)
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
                        field_value(prepared.data, "identifier")
                        or field_value(prepared.data, "title")
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
            yield "saving", len(saved_objects), len(objects)

        return saved_objects
