# Changelog

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
