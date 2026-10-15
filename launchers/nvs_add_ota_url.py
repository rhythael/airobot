# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""Append wifi:ota_url to an ESP32 NVS image, leaving every other byte untouched.

The device had no ota_url key, so the firmware fell back to the compiled-in
xiaozhi.me address. Rather than regenerating the whole 16 KB partition (which
would mean re-encoding phy:cal_data blobs and every other entry), this appends
one string entry into the free space of the ACTIVE page.

CRC32 must match what nvs_parser.py computes, or the firmware skips the entry:
  header CRC: crc32(raw[:4] + raw[8:32], 0xFFFFFFFF)
  data   CRC: crc32(children_bytes[:size], 0xFFFFFFFF)   # size includes the NUL

  python nvs_add_ota_url.py in.bin out.bin http://192.168.0.201:8003/xiaozhi/ota/
  esptool --port /dev/cu.usbserial-10 write_flash 0x9000 out.bin
"""

from __future__ import annotations

import pathlib
import struct
import sys
import zlib

PAGE, HDR, ENTRY = 4096, 64, 32
TYPE_STR, TYPE_U8 = 0x21, 0x01
STATE_WRITTEN, STATE_FREE = 2, 3
PAGE_ACTIVE, PAGE_EMPTY = 0xFFFFFFFE, 0xFFFFFFFF
NS_NAME, KEY = "wifi", "ota_url"


def entry_state(page: bytes, i: int) -> int:
    return (page[32 + i // 4] >> ((i % 4) * 2)) & 0x3


def set_entry_state(buf: bytearray, page_off: int, i: int, state: int) -> None:
    off = page_off + 32 + i // 4
    shift = (i % 4) * 2
    buf[off] = (buf[off] & ~(0x3 << shift)) | (state << shift)


def find_namespace_index(data: bytes, name: str) -> int | None:
    """Namespace definitions live in namespace 0 as uint8 entries: key=name, value=index."""
    for p in range(0, len(data), PAGE):
        page = data[p : p + PAGE]
        if len(page) < HDR or struct.unpack("<I", page[0:4])[0] == PAGE_EMPTY:
            continue
        for i in range(126):
            if entry_state(page, i) != STATE_WRITTEN:
                continue
            e = page[HDR + i * ENTRY : HDR + (i + 1) * ENTRY]
            if e[0] == 0 and e[1] == TYPE_U8 and e[8:24].split(b"\0")[0] == name.encode():
                return e[24]
    return None


def has_key(data: bytes, ns_index: int, key: str) -> bool:
    for p in range(0, len(data), PAGE):
        page = data[p : p + PAGE]
        if len(page) < HDR:
            break
        for i in range(126):
            if entry_state(page, i) != STATE_WRITTEN:
                continue
            e = page[HDR + i * ENTRY : HDR + (i + 1) * ENTRY]
            if e[0] == ns_index and e[8:24].split(b"\0")[0] == key.encode():
                return True
    return False


def append_string(data: bytearray, ns_index: int, key: str, value: str) -> tuple[int, int]:
    raw = value.encode() + b"\0"
    n_data = (len(raw) + ENTRY - 1) // ENTRY
    span = 1 + n_data

    page_off = next(
        p for p in range(0, len(data), PAGE)
        if struct.unpack("<I", data[p : p + 4])[0] == PAGE_ACTIVE
    )
    page = data[page_off : page_off + PAGE]
    start = next(i for i in range(126) if entry_state(page, i) == STATE_FREE)
    if not all(entry_state(page, start + k) == STATE_FREE for k in range(span)):
        raise SystemExit("not enough contiguous free entries on the active page")

    body = bytearray(raw) + b"\xff" * (n_data * ENTRY - len(raw))
    head = bytearray(b"\xff" * ENTRY)
    head[0:4] = bytes([ns_index, TYPE_STR, span, 0xFF])
    head[8:24] = key.encode().ljust(16, b"\0")
    struct.pack_into("<H", head, 24, len(raw))
    struct.pack_into("<H", head, 26, 0xFFFF)
    struct.pack_into("<I", head, 28, zlib.crc32(bytes(body)[: len(raw)], 0xFFFFFFFF))
    struct.pack_into("<I", head, 4, zlib.crc32(bytes(head[:4]) + bytes(head[8:32]), 0xFFFFFFFF))

    base = page_off + HDR + start * ENTRY
    data[base : base + ENTRY] = head
    data[base + ENTRY : base + ENTRY + len(body)] = body
    for k in range(span):
        set_entry_state(data, page_off, start + k, STATE_WRITTEN)
    return start, span


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    src, dst, value = sys.argv[1], sys.argv[2], sys.argv[3]

    original = pathlib.Path(src).read_bytes()
    data = bytearray(original)

    ns_index = find_namespace_index(data, NS_NAME)
    if ns_index is None:
        raise SystemExit(f"namespace {NS_NAME} not found")
    if has_key(data, ns_index, KEY):
        raise SystemExit(f"{NS_NAME}:{KEY} already exists; this script only appends")

    start, span = append_string(data, ns_index, KEY, value)
    pathlib.Path(dst).write_bytes(bytes(data))

    changed = [i for i in range(len(original)) if original[i] != data[i]]
    print(f"namespace {NS_NAME}={ns_index}, entry {start}, span {span}")
    print(f"wrote {dst}: {len(changed)} bytes changed "
          f"(0x{min(changed):x}-0x{max(changed):x}), {len(original) - len(changed)} unchanged")
    print("verify before flashing:  nvs_tool.py --integrity-check -d minimal " + dst)


if __name__ == "__main__":
    main()
