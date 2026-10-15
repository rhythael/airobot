# ota-alias：让 Mac 在公司网络上始终持有 192.168.0.201

## 为什么

041 售货机 NVS 里写死的服务端地址是 `http://192.168.0.201:8003/xiaozhi/ota/`。
Mac 在公司 Wi-Fi 上用的是 macOS 私有随机网卡地址（`ifconfig en0` 的 ether `fa:2f:…` ≠ 硬件地址 `a0:78:…`），
DHCP 隔一阵就换 IP：.201 → .202（09-24）→ .200（10-05）。设备找不到 .201 时屏幕报
「检查新版本失败，将在 160 秒后重试：code=113」，串口里是 `Failed to connect to 192.168.0.201:8003, code=0x71`。

设备只用 .201 做 OTA；OTA 回包里的 websocket 地址由服务端按 Mac 当时的主 IP 生成。
所以只要 .201 一直在 Mac 身上，主 IP 怎么漂都不影响，也不用再改设备。

## 怎么做的

- `airobot-ota-alias.sh`：在公司网络（默认网关是公司路由器 `00:11:22:33:44:55`）且 .201 不在本机时，
  先查 .201 有没有别的设备在用（看 ARP 回应），没人用才 `ifconfig en0 alias 192.168.0.201 netmask 255.255.255.255`；
  离开公司网络就撤掉别名。`DRY_RUN=1` 只打印要做的事，不需要 root。
- `com.smartfoodie.airobot-ota-alias.plist`：launchd 系统守护进程，开机运行、每 30 秒一次、网络变化时立刻一次。
- 安装后的副本归 root 所有：`/usr/local/libexec/airobot-ota-alias.sh`、`/Library/LaunchDaemons/com.smartfoodie.airobot-ota-alias.plist`。
  改了仓库里的脚本要重新安装才生效。
- 只在状态变化时写日志：`/var/log/airobot-ota-alias.log`。

## 常用

```bash
scripts/status.sh                       # 最后两行：.201 在不在本机、守护进程是否加载
sudo tools/ota-alias/install.sh         # 安装 / 更新（自检：撤掉 .201，看守护进程能否补回）
sudo tools/ota-alias/uninstall.sh       # 卸载并撤掉 .201
cat /var/log/airobot-ota-alias.log      # 加上 / 撤掉 / 冲突记录
```

## 什么时候会失效

| 情况 | 现象 | 处理 |
|---|---|---|
| 公司换了路由器 | status 显示「不在公司网络」 | 改脚本里的 `GW_MAC`，重新安装 |
| .201 被别的设备占了 | 日志写「被别的设备占用」 | 让那台设备换地址，或在路由器里把 .201 保留给 Mac |
| Mac 重启后语音服务没起 | 设备连上 .201 但被拒绝 | `scripts/start-all.sh`（服务端和库存桥目前不是开机自启） |
| Mac 合盖睡眠 | 设备连不上 | 接电源时系统睡眠已关；合盖会睡 |

更彻底的做法是在路由器里给 Mac 做 DHCP 保留，或者关掉这个 Wi-Fi 的「私有 Wi-Fi 地址」；
有了这个守护进程后两者都不是必需的。
