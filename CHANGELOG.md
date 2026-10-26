# Changelog

## 1.3.6

- Time every cloud request and report the refresh breakdown (login / family switch / device
  list / total) in diagnostics as `last_refresh_timings_ms`, plus a per-endpoint table. A
  refresh slower than 5 s also logs one info line, so a slow start explains itself.
- No behaviour change: this is instrumentation for tracking down the ~13 s setup time seen
  on a real installation.

## 1.3.5

- Fix diagnostics leaking the family ID for entries migrated from `hass-iotbull`: the legacy
  `selected_families` key was missing from the redaction list, so the family ID appeared in
  plain text even though the docs promise it is removed. `selected_family_count` also
  reported `0` for those entries and now reports the real count.
- Record the real-account verification of MQTT over TLS (PROTOCOL.md §8.2): `mqtt_transport`
  is `wss`, no fallback warning, entity count unchanged.

## 1.3.4

- Use MQTT over WebSocket + TLS (`emqx-prod.iotbull.com:8084/mqtt`) by default, so
  `openid` and `access_token` no longer cross the internet in plaintext. Falls back to the
  official app's plaintext `1883` channel when the TLS endpoint is unreachable, logging a
  warning so the downgrade is visible.
- Report the active MQTT transport (`wss` / `tcp`) in diagnostics.
- Document the transport probe (port scan, certificate chain, CONNACK evidence) in
  PROTOCOL.md §8.1.

## 1.3.3

- Ship brand assets inside `custom_components/bull/brand/`, so Home Assistant renders the
  integration icon locally (HA 2024.5+). This also satisfies the HACS `check brands` step.
- Mask the account in the config entry title (`138****0398` instead of the full phone number).
  The title is visible in Settings → Devices & services and in every screenshot or issue
  report. Existing entries are migrated in place (config entry version 1 → 2), so no re-adding
  is needed.
- Add a device list screenshot to the README.

## 1.3.2

- Fix entity names repeating the device name when `has_entity_name` is enabled.
- Report cloud failures as `HomeAssistantError` with the original message instead of a generic error.
- Drop `support_tier` and `product_id` from switch state attributes; both remain available in diagnostics.
- Detect `DataUpdateCoordinator` support for `config_entry` by signature instead of catching `TypeError`.
- Warn when the MQTT account bind is rejected instead of silently falling back to polling.
- Move the Thing Service charger PID list into `device_profiles.json` so device lists have one source.
- Unify the `bull_iot/` and `custom_components/bull/` client copies; the CLI now exposes the BLE helpers too.
- Declare `bleak` and `bleak-retry-connector` in the manifest. `requests` and `cryptography` are
  intentionally left out: Hassfest rejects custom integrations that list Home Assistant core
  dependencies, and both are guaranteed to be present at runtime.
- Add `scripts/check_consistency.py`, a Ruff configuration, issue templates and `RELEASING.md`.
- Document the plaintext MQTT channel, the hass-iotbull relationship and the migration path.

## 1.3.1

- Add the official Hassfest validation workflow required for HACS default inclusion.
- Mark the integration as specific to the Chinese MosHome service in HACS metadata.

## 1.3.0

- Restore capability-first discovery for standard `PowerSwitch` schemas.
- Create unprofiled load controls disabled by default; keep battery scene panels read-only.
- Add versioned device profiles with explicit evidence levels.
- Add privacy-preserving config-entry and device diagnostics.
- Reject reauthentication with a different MosHome account.
- Allow selected families to be changed from integration options.
- Adopt the standard HACS repository layout, translations, brand assets and validation workflow.
- Preserve the established `bull` domain, legacy family selection and entity unique IDs for in-place upgrades.
- Add compatibility for config-entry-aware coordinators in current Home Assistant releases.
- Clarify the 5.1.13 protocol-source and 5.3.1 compatibility-test boundary.

Existing entity unique IDs are unchanged in this release.
