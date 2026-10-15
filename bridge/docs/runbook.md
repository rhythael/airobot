# Tuya Enterprise Bridge Runbook

## Safety boundary

This bridge is read-only. Do not add customer data, raw orders, history, files, URL resigning, refunds, inventory changes, or device controls. Keep `ALLOWED_SCOPE_IDS=company` until additional aliases are approved.

## Local setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

## Enter credentials without saving them

Run these commands in a new terminal. Values entered with `read -s` are hidden and remain only in that shell process.

```bash
echo
echo
export ALLOWED_SCOPE_IDS=company
```

Never paste these values into chat, source files, Tuya prompts, screenshots, or verification notes.

## Start the local MCP server

In the credential terminal:

```bash
.venv/bin/smartfoodie-mcp
```

Expected local endpoint: `http://127.0.0.1:8765/mcp`.

In a second terminal, repeat the in-memory exports and run:

```bash
```

Expected log: `Tuya MCP bridge connected`. No Access Secret or IdToken may appear.

## Validation budget

Run all offline tests first. Perform no more than ten real enterprise queries during the first validation session.

## Stop and clear

Press Ctrl+C in both terminals, then run:

```bash
```


## Tuya rollback

Do not deploy the test Agent to a PID. If rollback is requested, detach `smartfoodie_query` from the test Agent, delete the test Agent, then delete the custom MCP service named `Smartfoodie Read-only Data Test`.

## China machine 041 bridge

The China Agent/MCP pair is separate from the existing EU pair. Its MCP service listens only on loopback at `http://127.0.0.1:8766/mcp`. Enter the Central Kitchen API key through the hidden terminal prompt or localhost form so it never enters shell history.

This checkout lives under iCloud-synced `~/Documents`, and macOS evicts files inside `.venv`; importing `mcp_sdk` from an evicted venv hangs indefinitely. Use a venv outside iCloud instead (the commands below assume it):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'   # 涂鸦侧加 [tuya]，macOS 钥匙串工具加 [macos]
```


Probe the Central Kitchen API once for the unique 041 store and its shelf summary:

```bash
.venv/bin/python scripts/probe_machine_041.py
```

First run only: start the localhost-only credential form, open it, and submit the four values. They are saved in the macOS login Keychain under service `smartfoodie-041-bridge`, then both processes start:

```bash
open http://127.0.0.1:8878
```

Every later start reads the Keychain, so nothing is re-entered. It does nothing if a bridge already listens on 8766:

```bash
```

To revoke the stored values, delete the Keychain items (and regenerate the Access Secret in Tuya if they may have leaked):

```bash
```

Check or stop only the China machine processes:

```bash
pgrep -fal 'smartfoodie-machine-(mcp|tuya)'
pkill -f '/smartfoodie-machine-mcp$'
pkill -f '/smartfoodie-machine-tuya$'
```

Rollback means stopping these two processes and selecting the EU tab in Tuya. Do not delete or edit the EU MCP service or Agent.
