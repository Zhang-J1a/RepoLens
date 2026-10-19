# Fixture Design Notes

## Archive semantics

Archiving keeps the task record and marks it inactive so callers can distinguish it from a missing task. Active lists exclude archived records.

## Notifications

Task creation sends a notification only when the task's `notify` flag is true. The fixture does not document why the notification timeout is three seconds.

## Explicit limits

Task records are held in an in-memory dictionary, so this fixture does not provide durable persistence. There is no retry or idempotency guarantee for notifications. The fixture API does not define pagination or an authorization policy.
