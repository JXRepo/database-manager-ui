import hashlib
import json
import math
from dataclasses import dataclass, replace
from typing import Sequence

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Q, Sum
from django.utils.http import int_to_base36

from apps.dyn_api.helpers import REQUIRED_TOP_LEVEL_FIELDS

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
    identifier_fingerprint: str = ""


def data_fingerprint(data: dict) -> str:
    """
    Hash the required metadata of one validated data object

    Following Ronak Shoghi's MiMeDat content based identifier approach, this
    uses required fields only. A canonical mapping preserves field boundaries,
    zero and false values. The full digest identifies generated content even
    when its public identifier has been extended to avoid a collision.

    Parameters
    ----------
    data : dict
        Object that has passed required field and numeric validation.

    Returns
    -------
    str
        Deterministic 64 character hexadecimal fingerprint.
    """
    content = {}
    for field in REQUIRED_TOP_LEVEL_FIELDS:
        content[field] = data[field]
    encoded = json.dumps(
        content, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _identifier_candidates(fingerprint: str):
    """
    Yield progressively longer lowercase base36 identifiers

    Start at eight characters. Reading the least significant digits first
    keeps the short prefix from being restricted by leading zero padding.

    Parameters
    ----------
    fingerprint : str
        Full SHA256 hexadecimal digest.

    Yields
    ------
    str
        Prefixes from eight to fifty characters, extending one at a time.
    """
    digits = int_to_base36(int(fingerprint, 16)).zfill(50)[::-1]
    for length in range(8, len(digits) + 1):
        yield digits[:length]


def _has_fingerprint(data: dict, fingerprint: str) -> bool:
    """
    Compare content while tolerating incomplete historical objects

    Parameters
    ----------
    data : dict
        Existing JSON, which may predate current upload validation.
    fingerprint : str
        Fingerprint of the incoming validated object.

    Returns
    -------
    bool
        Whether the required content has the same fingerprint.
    """
    try:
        return data_fingerprint(data) == fingerprint
    except (KeyError, TypeError, ValueError, RecursionError):
        return False


def _resolve_generated_identifier(
    fingerprint: str, pending_objects: Sequence[PreparedJSONData],
) -> str:
    """
    Recognize repeated content or allocate its shortest available identifier

    Existing matches are returned so callers can report duplicates instead
    of giving identical content a new identifier. The final save invokes
    this again under the upload transaction lock.

    Parameters
    ----------
    fingerprint : str
        Digest captured before adding the identifier to the uploaded JSON.
    pending_objects : sequence of PreparedJSONData
        Other objects already prepared or reserved in this upload.

    Returns
    -------
    str
        Existing identifier for duplicate content, or an available candidate.

    Raises
    ------
    UploadResourceLimitError
        If all candidate lengths are occupied by different content.
    """
    pending = {}
    for prepared in pending_objects:
        identifier = prepared.data.get("identifier")
        if prepared.identifier_fingerprint == fingerprint or identifier == fingerprint:
            return identifier
        pending[identifier] = prepared

    existing = JSONData.objects.filter(
        Q(identifier_fingerprint=fingerprint) | Q(data__identifier=fingerprint)
    ).values_list("data", flat=True).first()
    if isinstance(existing, dict) and isinstance(existing.get("identifier"), str):
        return existing["identifier"]

    candidates = list(_identifier_candidates(fingerprint))
    for identifier, prepared in pending.items():
        if identifier in candidates and _has_fingerprint(prepared.data, fingerprint):
            return identifier

    occupied = set()
    for data in JSONData.objects.filter(
        data__identifier__in=candidates,
    ).values_list("data", flat=True):
        identifier = data["identifier"]
        if _has_fingerprint(data, fingerprint):
            return identifier
        occupied.add(identifier)

    for candidate in candidates:
        if candidate not in pending and candidate not in occupied:
            return candidate

    raise UploadResourceLimitError(
        "Could not allocate a unique identifier. Please provide your own unique "
        "identifier for this data object and upload it again.",
        category="identifier_allocation",
    )


def generate_data_identifier(
    data: dict, pending_objects: Sequence[PreparedJSONData] = (),
) -> str:
    """
    Preview a short identifier without reserving or saving it

    Parameters
    ----------
    data : dict
        Validated uploaded object.
    pending_objects : sequence of PreparedJSONData, optional
        Other accepted objects in the same upload.

    Returns
    -------
    str
        Identifier to check for a duplicate or prepare for final allocation.
    """
    return _resolve_generated_identifier(data_fingerprint(data), pending_objects)


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


def save_prepared_json_data(
    owner: User,
    objects: list[PreparedJSONData],
) -> list[JSONData]:
    """
    Atomically save prepared objects inside the owner's live quota
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
        resolved_objects = []
        supplied_objects = [item for item in objects if not item.identifier_fingerprint]

        for prepared in objects:
            original_identifier = str(prepared.data.get("identifier", "")).strip()
            identifier = original_identifier
            if prepared.identifier_fingerprint:
                identifier = _resolve_generated_identifier(
                    prepared.identifier_fingerprint, resolved_objects + supplied_objects,
                )
                data = dict(prepared.data, identifier=identifier)
                prepared = replace(prepared, data=data, size_bytes=canonical_json_size(data))

            if identifier in seen_identifiers:
                conflicts.append(original_identifier)
            elif JSONData.objects.filter(
                data__identifier=identifier
            ).exists():
                conflicts.append(original_identifier)

            seen_identifiers.add(identifier)
            if prepared.identifier_fingerprint:
                seen_identifiers.add(prepared.identifier_fingerprint)
            resolved_objects.append(prepared)

        if conflicts:
            raise UploadIdentifierConflict(conflicts)

        incoming_size = sum(item.size_bytes for item in resolved_objects)
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

        for prepared in resolved_objects:
            data_object = JSONData.objects.create(
                owner=locked_owner,
                data=prepared.data,
                identifier_fingerprint=prepared.identifier_fingerprint,
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
