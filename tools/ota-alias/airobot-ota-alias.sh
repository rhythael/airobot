#!/bin/sh
# 让这台 Mac 在公司网络上始终持有 192.168.0.201。
#
# 为什么：041 售货机 NVS 里写死的服务端地址是 http://192.168.0.201:8003/xiaozhi/ota/。
# Mac 在公司 Wi-Fi 上用的是私有随机网卡地址（ether ≠ 硬件地址），DHCP 隔一阵就换 IP
# （.201 → .202 → .200），设备就报「检查新版本失败 code=113」（2026-09-24、10-09 两次）。
# 设备只用 .201 做 OTA；OTA 回包里的 websocket 地址由服务端按 Mac 当时的主 IP 生成，
# 所以只要 .201 一直在 Mac 身上，主 IP 怎么漂都不影响。
#
# 由 launchd 以 root 每 30 秒 + 网络变化时运行一次（com.smartfoodie.airobot-ota-alias）。
# 只在公司网络（默认网关是公司路由器的网卡地址）加；离开公司网络就撤掉，免得占别人家的地址。
# 加之前先查 .201 有没有别的设备在用（看 ARP 有没有回应，挡 ping 的设备也查得出来）。
# DRY_RUN=1 只打印要执行的命令，不需要 root，用于测试。

IF="${AIROBOT_IF:-en0}"
ADDR="${AIROBOT_OTA_ADDR:-192.168.0.201}"
# 公司路由器（192.168.0.1）的网卡地址。换路由器后改这里，或用环境变量覆盖
GW_MAC="${AIROBOT_GW_MAC:-00:11:22:33:44:55}"
LOG="${AIROBOT_LOG:-/var/log/airobot-ota-alias.log}"

log() {
    if [ -n "${DRY_RUN}" ]; then echo "log: $*"; else echo "$(date '+%F %T') $*" >> "${LOG}"; fi
}
run() {
    if [ -n "${DRY_RUN}" ]; then echo "would: $*"; else "$@"; fi
}
has_alias() {
    ifconfig "${IF}" 2>/dev/null | grep -q "inet ${ADDR} "
}
mac_of() {
    # 「? (192.168.0.1) at 00:11:22:33:44:55 on en0 ...」→ 第 4 列；没有条目或 incomplete 时为空
    arp -n "$1" 2>/dev/null | awk '$4 ~ /^[0-9a-f:]+$/ && $4 ~ /:/ {print $4}' | tr 'A-F' 'a-f'
}

gw=$(route -n get default 2>/dev/null | awk '/gateway/{print $2}')
[ -n "${gw}" ] && ping -c 1 -t 1 "${gw}" >/dev/null 2>&1   # 刚开机 ARP 表可能还是空的
gw_mac=$(mac_of "${gw}")

if [ -z "${gw}" ] || [ "${gw_mac}" != "$(echo "${GW_MAC}" | tr 'A-F' 'a-f')" ]; then
    if has_alias; then
        run ifconfig "${IF}" -alias "${ADDR}" && log "不在公司网络（网关 ${gw:-无} ${gw_mac:-?}），已撤掉 ${ADDR}"
    fi
    [ -n "${DRY_RUN}" ] && echo "state: off-network"
    exit 0
fi

primary=$(ipconfig getifaddr "${IF}" 2>/dev/null)
if [ "${primary}" = "${ADDR}" ]; then
    [ -n "${DRY_RUN}" ] && echo "state: primary-is-alias"
    exit 0
fi
if has_alias; then
    [ -n "${DRY_RUN}" ] && echo "state: ok"
    exit 0
fi

# 冲突检查：清掉旧缓存再问一次，有网卡地址回应就说明别的设备在用
run arp -d "${ADDR}" >/dev/null 2>&1
ping -c 1 -t 1 "$ADDR" >/dev/null 2>&1
other=$(mac_of "${ADDR}")
if [ -n "${other}" ]; then
    log "${ADDR} 被别的设备（${other}）占用，没有加别名。041 售货机会连不上，需要人工处理"
    [ -n "${DRY_RUN}" ] && echo "state: conflict"
    exit 1
fi

run ifconfig "${IF}" alias "${ADDR}" netmask 255.255.255.255 && log "已加上 ${ADDR}（主地址 ${primary}）"
[ -n "${DRY_RUN}" ] && echo "state: added"
exit 0
