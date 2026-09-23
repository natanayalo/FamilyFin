# Daily local automation on macOS

Family Finance does not install or modify operating-system schedules. After
the application and its virtual environment are installed, a user may create
`~/Library/LaunchAgents/com.family-finance.automation.plist` with the following
example. Replace the two paths with the checkout and data locations in use.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.family-finance.automation</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/you/FamilyFin/.venv/bin/family-finance</string>
    <string>automate</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/you/FamilyFin</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>FAMILY_FINANCE_DATA_ROOT</key><string>/Users/you/FamilyFin/data/local</string>
    <key>FAMILY_FINANCE_AUTOMATION_BACKUP_ROOT</key><string>/Users/you/FamilyFin/backups/automation</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>6</integer><key>Minute</key><integer>0</integer></dict>
</dict>
</plist>
```

Install manually with `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.family-finance.automation.plist` and inspect with `launchctl print gui/$(id -u)/com.family-finance.automation`.
