# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""Product stock answers must use only validated, fresh, purchasable rows."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.utils.product_answer import local_product_answer
from core.utils.context_provider import ContextDataProvider


class ProductAnswerTests(unittest.TestCase):
    def setUp(self):
        self.settings = {"local_product_answers": True, "unavailable_context": "unavailable"}
        self.data = {"inventory": {"machine_number": "041", "items": [
            {"slot": "1-6", "name": "鸡肉蔬菜蒸饺(10粒）", "quantity": 2, "purchasable": False},
            {"slot": "2-7", "name": "鸡肉蔬菜蒸饺(10粒）", "quantity": 1, "purchasable": True},
            {"slot": "2-6", "name": "虾饺（10粒）", "quantity": 2, "purchasable": False},
        ]}}

    def answer(self, query, data=None, context="fresh"):
        return local_product_answer(query, context, self.data if data is None else data, self.settings)

    def test_three_languages_exclude_expired_quantity_and_keep_original_name(self):
        questions = ("鸡肉蔬菜蒸饺还有吗？", "Is 鸡肉蔬菜蒸饺 still in stock?", "Ist 鸡肉蔬菜蒸饺 noch verfügbar?")
        for query in questions:
            answer = self.answer(query)
            self.assertIn("2-7", answer)
            self.assertNotIn("1-6", answer)
            self.assertIn("鸡肉蔬菜蒸饺(10粒）", answer)
        self.assertTrue(self.answer(questions[0]).startswith("还有1份"))

    def test_quantities_are_summed_across_available_slots(self):
        self.data["inventory"]["items"].append({"slot": "1-1", "name": "鸡肉蔬菜蒸饺(10粒）", "quantity": 3, "purchasable": True})
        self.assertTrue(self.answer("那个鸡肉蔬菜蒸饺还有吗？").startswith("还有4份"))

    def test_expired_only_product_is_not_available_for_purchase(self):
        self.assertEqual(self.answer("虾饺还有吗？"), "没有可购买的虾饺（10粒）。")

    def test_unknown_or_ambiguous_names_cannot_be_reported_sold_out(self):
        self.assertIsNone(self.answer("咖啡还有吗？"))
        self.data["inventory"]["items"].append({"slot": "1-1", "name": "鸡肉蔬菜蒸饺(20粒）", "quantity": 3, "purchasable": True})
        self.assertIsNone(self.answer("鸡肉蔬菜蒸饺还有吗？"))
        self.assertIn("2-7", self.answer("鸡肉蔬菜蒸饺(10粒)还有吗？"))

    def test_opt_in_missing_inventory_name_reports_lookup_not_sold_out(self):
        self.settings['report_unmatched_product'] = True
        self.assertEqual(self.answer('牛肉炒面还有吗？'), '现在机器里没看到牛肉炒面。')
        self.assertNotIn('售罄', self.answer('牛肉炒面还有吗？'))
        self.assertEqual(self.answer('它还有吗？'), '你说的是哪款商品？')
        self.assertIsNone(self.answer('牛肉炒面和咖啡还有吗？'))
        self.assertEqual(self.answer('牛肉炒面还有吗？', context='unavailable'), '暂时查不到库存，请看机器屏幕。')

    def test_multiple_requests_prices_and_other_machine_stay_with_model(self):
        for query in ("鸡肉蔬菜蒸饺还有吗？多少钱？", "42号机器的鸡肉蔬菜蒸饺还有吗？", "Is 鸡肉蔬菜蒸饺 and 虾饺 still available?", "Do you still have 鸡肉蔬菜蒸饺 and what is the price?"):
            self.assertIsNone(self.answer(query))

    def test_german_product_name_with_und_is_not_treated_as_multiple_requests(self):
        name = "Dampfnudel mit Vanillesauce und Kirschen"
        self.data["inventory"]["items"].append({"slot": "1-3", "name": name, "quantity": 2, "purchasable": True})
        answer = self.answer(f"Ist {name} noch verfügbar?")
        self.assertIn(name, answer)
        self.assertIn("1-3", answer)

    def test_failed_refresh_ignores_even_existing_rows(self):
        self.assertIsNone(self.answer("42号机器的鸡肉蔬菜蒸饺还有吗？", context="unavailable"))
        self.assertEqual(self.answer("鸡肉蔬菜蒸饺还有吗？", context="unavailable"), "暂时查不到库存，请看机器屏幕。")

    def test_invalid_rows_duplicate_slots_or_foreign_machine_are_rejected(self):
        for field, invalid in (("quantity", True), ("quantity", -1), ("quantity", "1"), ("purchasable", "true"), ("slot", "3-1"), ("name", None)):
            data = copy.deepcopy(self.data)
            data["inventory"]["items"][1][field] = invalid
            self.assertIsNone(self.answer("鸡肉蔬菜蒸饺还有吗？", data=data))
        data = copy.deepcopy(self.data)
        data["inventory"]["items"].append(data["inventory"]["items"][1])
        self.assertIsNone(self.answer("鸡肉蔬菜蒸饺还有吗？", data=data))
        data["inventory"]["machine_number"] = "042"
        self.assertIsNone(self.answer("鸡肉蔬菜蒸饺还有吗？", data=data))

    def test_provider_preserves_structured_fields_and_clears_them_on_failure(self):
        provider = ContextDataProvider({"context_providers": [{"url": "http://127.0.0.1/context", "structured_fields": ["inventory"]}]})
        response = Mock(status_code=200)
        response.json.return_value = {"code": 0, "data": {"summary": "fresh", **self.data}}
        with patch("core.utils.context_provider.httpx.get", return_value=response):
            text = provider.fetch_all("sim", refresh=True)
            self.assertEqual(provider.structured_data["inventory"], self.data["inventory"])
            self.assertNotIn("purchasable", text)
            response.json.return_value = {"code": 1, "msg": "unavailable"}
            self.assertEqual(provider.fetch_all("sim", refresh=True), "")
            self.assertEqual(provider.structured_data, {})


if __name__ == "__main__":
    unittest.main()
