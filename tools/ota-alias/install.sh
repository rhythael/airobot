#!/bin/sh
# 以 root 运行：sudo tools/ota-alias/install.sh
# 脚本复制成 root 所有的副本再交给 launchd：root 进程不能去执行用户可改的文件。
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
LABEL=com.smartfoodie.airobot-ota-alias
ADDR=192.168.0.201
install -d -o root -g wheel -m 755 /usr/local/libexec
install -o root -g wheel -m 755 "$HERE/airobot-ota-alias.sh" /usr/local/libexec/airobot-ota-alias.sh
install -o root -g wheel -m 644 "$HERE/$LABEL.plist" "/Library/LaunchDaemons/$LABEL.plist"
launchctl bootout "system/$LABEL" 2>/dev/null || true
launchctl bootstrap system "/Library/LaunchDaemons/$LABEL.plist"
# 自检：撤掉别名，看守护进程能不能马上补回来
ifconfig en0 -alias "$ADDR" 2>/dev/null || true
launchctl kickstart -k "system/$LABEL"
sleep 3
if ifconfig en0 | grep -q "inet $ADDR "; then
    echo "OK: 已安装，守护进程把 $ADDR 补回来了"
else
    echo "FAIL: 守护进程没有补回 $ADDR，看 /var/log/airobot-ota-alias.log"
    exit 1
fi
