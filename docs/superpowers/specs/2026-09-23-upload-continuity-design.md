# Upload progress and navigation

The user approved limits on the upload page, real transfer and object validation
progress, and uploads that continue during internal navigation. Investigation of
Ronak's unsuccessful file is deferred until the actual file is available.

## Behavior

- Read displayed allowances from Django settings. Keep existing limits unchanged.
- Send files once in one multipart request. Report actual browser transfer bytes.
- Check batch file count, bytes and total objects before saving any data.
- Validate each complete file, publish completed object counts, then save the file
  atomically. Only committed records may be labelled saved.
- Preserve grouped, escaped errors, identifier checks, sharing and quota locks.
- A private task record lets its owner recover results after navigation. Never
  retry a submission or interrupted file automatically.

## Architecture

A new authenticated jobs endpoint stages files in a private directory and returns
a task snapshot. A separate management command processes tasks belonging to its
own hosting instance. The existing ordinary form and NDJSON endpoint remain
available. File completion is recorded in the same database transaction as data
objects and notifications. Heartbeats distinguish processing from interruption.

The Render web service starts Gunicorn and the worker under one supervisor with
a shared instance UUID. This adds no paid service or raw-file database storage.
Staging is ephemeral on the existing host: redeploys or instance loss can interrupt
unfinished files. Confirmed results survive; lost work is not retried. This is
navigation continuity, not a promise to resume after hosting failures.

During browser transfer, the original upload document stays alive. Internal
navigation uses a full-page same-origin frame, preserving each page's normal
script lifecycle. Only authenticated application views allow same-origin framing;
authentication and admin responses retain DENY. Leaving the site or reloading
before server receipt warns about interruption. After receipt, owner-scoped
status requests recover progress on another document.

## Verification

Test object progress and atomic result commits; global prechecks; owner isolation;
duplicate submission protection; worker interruption and cleanup; legacy uploads;
real browser transfer, navigation and result recovery; desktop layout with long
file names and empty state. Use DEBUG=True and isolated local test databases.
