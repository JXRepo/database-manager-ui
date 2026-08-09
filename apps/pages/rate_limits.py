import hashlib
import hmac
import ipaddress
import math
from dataclasses import dataclass
from datetime import datetime, timezone as datetime_timezone

from django.conf import settings
from django.db import DatabaseError, transaction
from django.http import HttpRequest
from django.utils import timezone

from .models import RateLimitBucket

CONSUME_RETRY_ATTEMPTS = 3


class _WindowChanged(Exception):
    """
    Signal that consumption crossed into a new fixed window
    """


@dataclass(frozen=True)
class RateLimitDecision:
    """
    Describe whether one limited action may proceed

    Attributes
    ----------
    allowed : bool
        Whether the caller may continue.
    retry_after_seconds : int
        Whole seconds until a denied caller may try again.
    """

    allowed: bool
    retry_after_seconds: int


def _identifier_hash(scope: str, identifier: str) -> str:
    """
    Build the keyed persisted identifier digest

    Parameters
    ----------
    scope : str
        Rate limit scope.
    identifier : str
        Raw identifier that must not be stored.

    Returns
    -------
    str
        HMAC SHA256 digest for the scoped identifier.
    """
    message = f"{scope}:{identifier}".encode()
    return hmac.new(
        settings.SECRET_KEY.encode(),
        message,
        hashlib.sha256,
    ).hexdigest()


def _scope_settings(scope: str) -> tuple[int, int]:
    """
    Return the configured limit and window for a scope

    Parameters
    ----------
    scope : str
        Rate limit scope.

    Returns
    -------
    tuple[int, int]
        Configured action limit and window length in seconds.
    """
    config = settings.PILOT_RATE_LIMITS[scope]
    return int(config["limit"]), int(config["window_seconds"])


def _window_values(now: datetime, window_seconds: int) -> tuple[int, datetime]:
    """
    Calculate the current fixed window identifier and expiry

    Parameters
    ----------
    now : datetime
        Current timezone aware time.
    window_seconds : int
        Fixed window length in seconds.

    Returns
    -------
    tuple[int, datetime]
        Integer window identifier and its ending time.
    """
    window_id = int(now.timestamp()) // window_seconds
    expires_at = datetime.fromtimestamp(
        (window_id + 1) * window_seconds,
        tz=datetime_timezone.utc,
    )
    return window_id, expires_at


def _retry_after_seconds(now: datetime, expires_at: datetime) -> int:
    """
    Calculate a positive Retry-After value for a full bucket

    Parameters
    ----------
    now : datetime
        Current timezone aware time.
    expires_at : datetime
        End of the fixed window.

    Returns
    -------
    int
        Whole seconds until the bucket expires.
    """
    return max(1, math.ceil((expires_at - now).total_seconds()))


def _validated_address(value: object) -> str | None:
    """
    Return a canonical IP address when the input is valid

    Parameters
    ----------
    value : object
        Request metadata value to validate.

    Returns
    -------
    str or None
        Canonical address, or None for an invalid value.
    """
    if not isinstance(value, str):
        return None

    candidate = value.strip()
    if not candidate:
        return None

    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def get_client_identifier(request: HttpRequest) -> str:
    """
    Derive a client address without trusting unvalidated proxy input

    The configured number of rightmost proxy hops is removed only when the
    full forwarded chain is valid and contains a client address.

    Parameters
    ----------
    request : HttpRequest
        Incoming Django request.

    Returns
    -------
    str
        Canonical client address or a shared fallback identifier.
    """
    remote_address = _validated_address(request.META.get("REMOTE_ADDR"))
    if remote_address is None:
        return "unknown"

    trusted_proxy_hops = int(getattr(settings, "TRUSTED_PROXY_HOPS", 0))
    render_hostname = getattr(settings, "RENDER_EXTERNAL_HOSTNAME", "")
    forwarded_value = request.META.get("HTTP_X_FORWARDED_FOR")
    if not render_hostname or trusted_proxy_hops <= 0 or not forwarded_value:
        return remote_address

    forwarded_addresses = []
    for value in forwarded_value.split(","):
        address = _validated_address(value)
        if address is None:
            return remote_address
        forwarded_addresses.append(address)

    address_chain = forwarded_addresses + [remote_address]
    if len(address_chain) <= trusted_proxy_hops:
        return remote_address

    client_chain = address_chain[:-trusted_proxy_hops]
    return client_chain[-1]


def check_rate_limit(scope: str, identifier: str) -> RateLimitDecision:
    """
    Inspect the current bucket without consuming an action

    Parameters
    ----------
    scope : str
        Rate limit scope.
    identifier : str
        Raw caller identifier.

    Returns
    -------
    RateLimitDecision
        Current allow or deny decision.
    """
    limit, window_seconds = _scope_settings(scope)
    identifier_hash = _identifier_hash(scope, identifier)
    now = timezone.now()
    window_id, expires_at = _window_values(now, window_seconds)

    bucket = RateLimitBucket.objects.filter(
        scope=scope,
        identifier_hash=identifier_hash,
        window_seconds=window_seconds,
        window_id=window_id,
    ).first()

    if bucket is None or bucket.count < limit:
        return RateLimitDecision(allowed=True, retry_after_seconds=0)

    return RateLimitDecision(
        allowed=False,
        retry_after_seconds=_retry_after_seconds(now, expires_at),
    )


def consume_rate_limit(scope: str, identifier: str) -> RateLimitDecision:
    """
    Atomically consume one action from the current fixed window

    Parameters
    ----------
    scope : str
        Rate limit scope.
    identifier : str
        Raw caller identifier.

    Returns
    -------
    RateLimitDecision
        Allow or deny decision after the atomic check.
    """
    limit, window_seconds = _scope_settings(scope)
    identifier_hash = _identifier_hash(scope, identifier)
    for _attempt in range(CONSUME_RETRY_ATTEMPTS):
        sampled_now = timezone.now()
        window_id, expires_at = _window_values(sampled_now, window_seconds)

        try:
            with transaction.atomic():
                bucket, _created = RateLimitBucket.objects.get_or_create(
                    scope=scope,
                    identifier_hash=identifier_hash,
                    window_seconds=window_seconds,
                    window_id=window_id,
                    defaults={
                        "count": 0,
                        "expires_at": expires_at,
                    },
                )
                bucket = RateLimitBucket.objects.select_for_update().get(
                    pk=bucket.pk,
                )

                verified_now = timezone.now()
                verified_window_id, _verified_expiry = _window_values(
                    verified_now,
                    window_seconds,
                )
                if verified_window_id != window_id:
                    raise _WindowChanged

                if bucket.count >= limit:
                    decision = RateLimitDecision(
                        allowed=False,
                        retry_after_seconds=_retry_after_seconds(
                            verified_now,
                            expires_at,
                        ),
                    )
                else:
                    bucket.count += 1
                    bucket.save(update_fields=["count"])
                    decision = RateLimitDecision(
                        allowed=True,
                        retry_after_seconds=0,
                    )

                cleanup_cutoff = datetime.fromtimestamp(
                    (window_id - 1) * window_seconds,
                    tz=datetime_timezone.utc,
                )
                RateLimitBucket.objects.filter(
                    scope=scope,
                    identifier_hash=identifier_hash,
                    expires_at__lte=cleanup_cutoff,
                ).delete()

                commit_now = timezone.now()
                commit_window_id, _commit_expiry = _window_values(
                    commit_now,
                    window_seconds,
                )
                if commit_window_id != window_id:
                    raise _WindowChanged

                return decision
        except (RateLimitBucket.DoesNotExist, _WindowChanged):
            continue

    raise DatabaseError(
        "Rate limit bucket changed repeatedly during consumption."
    )


def reset_rate_limit(scope: str, identifier: str) -> None:
    """
    Remove all stored buckets for one scoped identifier

    Parameters
    ----------
    scope : str
        Rate limit scope.
    identifier : str
        Raw caller identifier.
    """
    identifier_hash = _identifier_hash(scope, identifier)

    with transaction.atomic():
        bucket_ids = list(
            RateLimitBucket.objects.select_for_update()
            .filter(
                scope=scope,
                identifier_hash=identifier_hash,
            )
            .values_list("pk", flat=True)
        )
        RateLimitBucket.objects.filter(pk__in=bucket_ids).delete()
