# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""Import the supplied menu snapshot into a local, versioned JSON catalog."""
import hashlib
import json
import re
import sys
from pathlib import Path


import datetime


def _today():
    """快照日期取导入当天。原先写死 2026-09-17，重新导入后日期不变，
    时效校验会永远看到一个假的新鲜度。"""
    return datetime.date.today().isoformat()


def compile_catalog(source):
    text = Path(source).read_text(encoding="utf-8")
    parts = re.split(r'<a id="dish-(\d+)"></a>\n', text)
    index_rows = {}
    for line in text.splitlines():
        if line.startswith('| ') and '[查看](#dish-' in line:
            cells = [cell.strip() for cell in line.strip('|').split('|')]
            ident = re.search(r'/ (\d+)$', cells[0])
            if ident:
                index_rows[ident[1]] = {"global_status": cells[2], "store_price_range": cells[4]}
    dishes = []
    for index in range(1, len(parts), 2):
        ident, block = parts[index:index + 2]
        block = block.split('\n## 数据来源与范围', 1)[0]
        name = re.search(r'^### (.+)$', block, re.M)
        code = re.search(r'菜品编码：`([^`]+)`；菜单 ID：`(\d+)`', block)
        price = re.search(r'默认售价：\*\*€([0-9.]+)/份\*\*', block)
        tags = re.search(r'^- 结构化过敏原标签（中英对照）：(.*)$', block, re.M)
        if not (name and code and price and tags) or code[2] != ident:
            raise ValueError(f"Incomplete menu record {ident}")
        quoted = '\n'.join(line[1:].lstrip(' ') for line in block.splitlines() if line.startswith('>'))
        allergy = re.search(r'(?im)^\s*(?:过敏|allergen)', quoted)
        overrides = {}
        for amount, stores in re.findall(r'^- 门店差异价 €([0-9.]+)/份：(.*)$', block, re.M):
            for store in stores.rstrip('。').split('、'):
                overrides[store] = amount
        dishes.append({"id": ident, **index_rows[ident], "code": code[1], "name": name[1],
            "default_price_eur": price[1], "store_price_eur": overrides,
            "allergen_tags": tags[1].rstrip('。'), "details": quoted,
            "ingredients": quoted[:allergy.start()].strip() if allergy else quoted.strip(),
            "allergen_text": quoted[allergy.start():].strip() if allergy else "",
            "price_notes": [l[2:] for l in block.splitlines() if l.startswith('- ') and ('门店' in l or '售价' in l)]})
    if len(dishes) != 220 or len({d['id'] for d in dishes}) != len(dishes):
        raise ValueError("Expected 220 distinct menu IDs")
    return {"schema_version": 1, "snapshot_date": _today(), "currency": "EUR",
        "source_name": Path(source).name, "source_sha256": hashlib.sha256(text.encode()).hexdigest(), "dishes": dishes}


if __name__ == "__main__":
    catalog = compile_catalog(sys.argv[1])
    destination = Path(sys.argv[2])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding="utf-8")
    print(f"Imported {len(catalog['dishes'])} distinct menu records")
