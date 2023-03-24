from aqt.addons import AddonManager


class Config:
    """A manager for config.json loading/updating/saving"""

    def __init__(self, addon_manager: AddonManager, addon_name: str = __name__):
        self._addon_manager = addon_manager
        self._addon_name = addon_name
        self._addon_manager.setConfigUpdatedAction(self._addon_name, self._config_updated_action)

    def _config(self):
        return self._addon_manager.getConfig(self._addon_name)

    def _config_updated_action(self, new_config) -> None:
        self._config().update(new_config)

    def _write(self) -> None:
        self._addon_manager.writeConfig(self._addon_name, self._config())

    def __getitem__(self, key):
        return self._config()[key]

    def __setitem__(self, key, value):
        self._config()[key] = value
        self._write()

    def get(self, key, default=None):
        return self._config().get(key, default)
