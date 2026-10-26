"""公牛智家云（MosHome）Home Assistant 自定义集成。

使用随组件分发的 bull_iot 客户端模块（client/signing/crypto/mqtt_listener）。
支持：开关、灯、窗帘、安防/电量传感器、PID 296 数显插座及充电桩。
"""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import DOMAIN, PLATFORMS, mask_account
from .coordinator import BullCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate older entries in place.

    Version 2 masks the account name in the entry title. Older entries were
    created with the raw username, which is a phone number.
    """
    if entry.version < 2:
        new_title = mask_account(entry.title)
        hass.config_entries.async_update_entry(entry, title=new_title, version=2)
        _LOGGER.debug("配置条目名已脱敏: %s", new_title)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Bull IoT from a config entry."""
    coordinator = BullCoordinator(hass, entry)
    await coordinator.async_load_info_cache()
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        raise
    except Exception as err:
        raise ConfigEntryNotReady(f"无法连接公牛智家云: {err}") from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 凭证更新后重载集成
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options/data change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: BullCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok
