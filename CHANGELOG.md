# Changelog

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
