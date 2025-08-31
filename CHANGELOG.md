# Changelog

## [1.1.0] - 2023-08-31

### Added
- New configuration option to control whether weekends and holidays are always treated as non-working days
- Added a checkbox in the config flow UI to enable/disable workday sensor integration
- When workday sensor integration is disabled, shifts will be shown according to the schedule pattern only, regardless of weekends and holidays

### Changed
- Modified both binary and state sensors to respect the new workday sensor configuration
- Added better code documentation and comments
- Improved error handling for workday sensor state changes

### Technical Details
- Added new configuration constant `CONF_USE_WORKDAY_SENSOR`
- Default value for the new option is set to `True` for backward compatibility
- Workday sensor state changes are only tracked when the feature is enabled
