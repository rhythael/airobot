#!/bin/sh
# 以 root 运行：sudo tools/ota-alias/uninstall.sh
LABEL=com.smartfoodie.airobot-ota-alias
launchctl bootout "system/$LABEL" 2>/dev/null || true
rm -f "/Library/LaunchDaemons/$LABEL.plist" /usr/local/libexec/airobot-ota-alias.sh
ifconfig en0 -alias 192.168.0.201 2>/dev/null || true
echo "已卸载，并撤掉了 192.168.0.201"
