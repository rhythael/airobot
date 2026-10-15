# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
import ast
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import queue
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.utils.menu_knowledge import local_menu_answer, local_menu_turn, load_catalog, DEFAULT_CATALOG
from core.providers.tts.dto.dto import TTSMessageDTO, SentenceType, ContentType
from core.utils.dialogue import Message


class MenuKnowledgeTests(unittest.TestCase):
    def answer(self, query, previous=None, settings=None):
        return local_menu_answer(query, settings or {'path': str(DEFAULT_CATALOG)}, previous)

    def test_all_220_records_keep_identity(self):
        data = load_catalog(str(DEFAULT_CATALOG))
        self.assertEqual(len(data['dishes']), 220)
        self.assertEqual(len({d['id'] for d in data['dishes']}), 220)
        self.assertEqual(len(data['source_sha256']), 64)

    def test_beef_noodles_ingredients_are_full_source_text(self):
        answer, ident = self.answer('能告诉我牛肉炒面的成分吗？')
        self.assertEqual(ident, '537')
        self.assertIn('熟面条（小麦粉、水、盐）', answer)
        self.assertIn('胡萝卜、洋葱、青椒', answer)
        self.assertNotIn('没有详细', answer)

    def test_allergens_keep_contains_and_trace_distinction(self):
        answer, ident = self.answer('牛肉炒面过敏原有吗？')
        self.assertEqual(ident, '537')
        self.assertIn('含有小麦、鸡蛋、大豆', answer)
        self.assertIn('可能含微量：芝麻、芹菜、牛奶', answer)
        self.assertIn('结构化过敏原标签', answer)

    def test_default_price_does_not_claim_live_machine_price(self):
        answer, ident = self.answer('牛肉炒面多少钱？')
        self.assertIn('总部默认', answer)
        self.assertIn('7.99欧元', answer)
        self.assertIn('2026-09-17', answer)
        self.assertIn('实际以机器有效标价', answer)

    def test_store_price_requires_explicit_store_identity(self):
        # 原用例拿 YZ005A + DEMO-041 做样本，断言会报出 0.11 欧元。
        # 但那条门店价本身是坏数据（默认价 7.99），现已被 price sanity gate 拦下。
        # 换成一组正常的门店差价，用例原本要守的意图不变：
        # 带门店身份才用门店价，不带就用总部默认价。
        with_store, _ = self.answer(
            'YZ004D多少钱？',
            settings={'path': str(DEFAULT_CATALOG), 'store_name': 'STORE-A'})
        self.assertIn('门店标价', with_store)
        self.assertIn('5.49欧元', with_store)

        without_store, _ = self.answer(
            'YZ004D多少钱？', settings={'path': str(DEFAULT_CATALOG)})
        self.assertIn('总部默认', without_store)
        self.assertIn('6.49欧元', without_store)

    def test_serving_alias_is_ambiguous_not_merged(self):
        answer, ident = self.answer('鸡肉蔬菜蒸饺过敏原有哪些？')
        self.assertIsNone(ident)
        # 顾客已经报过菜名，不能再反问；直接把各份量的资料答出来。
        self.assertNotIn('哪一款', answer)
        self.assertNotIn('编码', answer)
        # 三种份量的过敏原资料不同，必须分开呈现，不能合并成一条。
        for portion in ('6粒', '10粒', '12粒'):
            self.assertIn(portion, answer)
        self.assertIn('鱼类', answer)      # 仅 10 粒含鱼类
        self.assertIn('含小麦、大豆、芝麻', answer)  # 6 粒与 12 粒的写法
        self.assertEqual(self.answer('YZ004D过敏原有哪些？')[1], '457')

    def test_concise_ingredients_truncate_and_offer_full(self):
        settings = {'path': str(DEFAULT_CATALOG), 'concise_voice': True}
        short, _ = local_menu_answer('鸡肉蔬菜蒸饺(10粒)的配料是什么？', settings)
        self.assertIn('主要配料是', short)
        self.assertIn('详细说说', short)
        self.assertNotIn('％', short)
        self.assertNotIn('33%', short)          # 括号里的百分比不念
        full, _ = local_menu_answer('鸡肉蔬菜蒸饺(10粒)的完整配料表', settings)
        self.assertIn('33%', full)              # 说「完整」时仍给原文
        self.assertLess(len(short), len(full))

    def test_catalog_freshness_gate_is_opt_in(self):
        """资料时效闸：不配 max_age_days 时行为与现状完全一致。"""
        from datetime import date
        base = {'path': str(DEFAULT_CATALOG), 'concise_voice': True}
        answer, _ = local_menu_answer('虾饺有什么过敏原？', base)
        self.assertNotIn('可能已经更新', answer)

        # 配了阈值且已过期：追加提示，但原有过敏原内容一字不少
        stale = dict(base, max_age_days=3, today=date(2026, 10, 1))
        stale_answer, _ = local_menu_answer('虾饺有什么过敏原？', stale)
        self.assertIn('可能已经更新', stale_answer)
        self.assertIn('以包装标签为准', stale_answer)
        self.assertIn('过敏提示', stale_answer)   # 不删既有内容

        # 配了阈值但未过期：不追加
        fresh = dict(base, max_age_days=90, today=date(2026, 9, 22))
        fresh_answer, _ = local_menu_answer('虾饺有什么过敏原？', fresh)
        self.assertNotIn('可能已经更新', fresh_answer)

    def test_delisted_dishes_stay_out_of_recommendations(self):
        """全局下架商品不进推荐面，但主动点名问仍能回答。"""
        import json, re
        from core.utils.menu_knowledge import full_menu_context
        menu = full_menu_context(str(DEFAULT_CATALOG))
        dishes = json.loads(DEFAULT_CATALOG.read_text(encoding='utf-8'))['dishes']
        delisted = [re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]", "", d['name']).strip()
                    for d in dishes if d.get('global_status') == '全局下架']
        self.assertTrue(delisted, '样本里应当存在下架商品')
        for name in delisted:
            if name:
                self.assertNotIn(name, menu)

        # 顾客主动点名下架商品时仍照实回答，不能装作不存在
        answer, _ = local_menu_answer(
            '猪肉蔬菜蒸饺的配料是什么？',
            {'path': str(DEFAULT_CATALOG), 'concise_voice': True})
        self.assertIn('主要配料', answer)

    def test_store_price_sanity_gate(self):
        """门店价异常时回落默认价。

        菜品目录里 DEMO-041 的鱼香茄子盖饭门店价是 0.11 欧元、默认价 7.99 欧元。
        041 目前只有这一条门店价，恰好就是坏的那条。对顾客报 0.11 欧元会出实际问题。
        """
        from core.utils.menu_knowledge import _price_is_sane
        self.assertFalse(_price_is_sane('0.11', '7.99'))   # 低于绝对下限
        self.assertFalse(_price_is_sane('3.20', '7.99'))   # 偏离超过 50%
        self.assertFalse(_price_is_sane(None, '7.99'))     # 没有门店价
        self.assertFalse(_price_is_sane('abc', '7.99'))    # 脏数据
        self.assertTrue(_price_is_sane('5.49', '6.49'))    # 正常门店差价
        self.assertTrue(_price_is_sane('7.99', '7.99'))

        settings = {'path': str(DEFAULT_CATALOG), 'store_name': 'DEMO-041',
                    'concise_voice': True}
        answer, _ = local_menu_answer('鱼香茄子盖饭多少钱？', settings)
        self.assertIn('7.99', answer)
        self.assertNotIn('0.11', answer)

    def test_concise_price_keeps_disclaimer(self):
        settings = {'path': str(DEFAULT_CATALOG), 'concise_voice': True}
        answer, _ = local_menu_answer('鸡肉蔬菜蒸饺(10粒)多少钱？', settings)
        self.assertIn('6.49欧元', answer)
        self.assertIn('以机器标价为准', answer)   # 免责表述不能丢
        self.assertNotIn('总部默认', answer)
        self.assertLess(len(answer), 60)

    def test_fuzzy_matches_real_asr_errors(self):
        """语音识别把菜名听错时，按读音找回来。用例取自真机日志。"""
        from core.utils.menu_knowledge import fuzzy_match_dish, load_catalog
        dishes = load_catalog(str(DEFAULT_CATALOG))['dishes']
        for query, expected in [
            ('鸡肉蔬菜针饺的成分是。', '鸡肉蔬菜蒸饺'),   # 蒸→针，前后鼻音
            ('虾人云吞面有哪些成分？', '虾仁云吞面'),     # 仁→人，同音
            ('鸡肉、蔬菜、根饺有哪些成分？', '鸡肉蔬菜蒸饺'),
        ]:
            hits = fuzzy_match_dish(query, dishes)
            self.assertTrue(hits, f'{query} 应当命中')
            for dish in hits:
                self.assertIn(expected, dish['name'])

    def test_fuzzy_refuses_risky_matches(self):
        """读音接近但不是同一道菜时宁可不认。过敏原依此作答，认错是安全问题。"""
        from core.utils.menu_knowledge import fuzzy_match_dish, load_catalog
        dishes = load_catalog(str(DEFAULT_CATALOG))['dishes']
        for query in [
            '牛肉面的成分是什么',      # 与「卤肉面」仅差一个音节，不得认成卤肉面
            '虾人',                  # 太短，虾仁蒸饺和虾仁云吞面都可能
            '咖啡还有吗',
            '那你推荐我吃什么呢',
            '今天天气怎么样',
        ]:
            hits = fuzzy_match_dish(query, dishes)
            names = [d['name'] for d in hits]
            self.assertFalse(
                any('卤肉面' in n for n in names), f'{query} 不得匹配到卤肉面')
            if query in ('咖啡还有吗', '那你推荐我吃什么呢', '今天天气怎么样'):
                self.assertEqual(hits, [], f'{query} 不应命中任何菜品')

    def test_followups_resolve_only_last_local_dish(self):
        self.assertEqual(self.answer('具体有哪些成分呢？', '537')[1], '537')
        self.assertEqual(self.answer('过敏原有吗？', '537')[1], '537')
        self.assertIsNone(self.answer('这个咖啡的过敏原是什么？', '537')[1])
        self.assertIsNone(self.answer('过敏原有吗？')[1])

    def test_unknown_and_multiple_dishes_do_not_guess(self):
        self.assertIsNone(self.answer('火星饭的成分是什么？')[1])
        self.assertIsNone(self.answer('牛肉炒面和鸡肉炒面的过敏原是什么？')[1])

    def test_unrelated_inventory_keeps_original_path(self):
        self.assertIsNone(self.answer('现在有多少种商品？')[0])
        self.assertIsNone(local_menu_answer('牛肉炒面多少钱？', None)[0])

    def test_missing_catalog_returns_local_failure(self):
        answer, ident = self.answer('牛肉炒面成分', settings={'path':'/no-such-menu.json'})
        self.assertIn('暂时读不到', answer)
        self.assertIsNone(ident)

    def test_real_device_clarification_sequence_keeps_ingredients_intent(self):
        conn = SimpleNamespace()
        settings = {'path': str(DEFAULT_CATALOG)}
        for query in ['能告诉我牛肉面的成分是什么吗？', '牛肉面的成分是什么？', '牛肉面。', '肉场面的成分是什么？']:
            answer = local_menu_turn(conn, query, settings)
            self.assertIn('牛肉炒面', answer)
            self.assertIn('红烧牛肉面', answer)
        answer = local_menu_turn(conn, '牛肉炒面。', settings)
        self.assertIn('熟面条（小麦粉、水、盐）', answer)
        self.assertIn('胡萝卜、洋葱、青椒', answer)
        self.assertEqual(conn.last_local_menu_id, '537')
        self.assertIn('可能含微量', local_menu_turn(conn, '过敏原呢？', settings))

    def test_natural_name_correction_answers_pending_question(self):
        conn = SimpleNamespace()
        settings = {'path': str(DEFAULT_CATALOG)}
        local_menu_turn(conn, '牛肉面的成分是什么？', settings)
        self.assertIn('牛肉片', local_menu_turn(conn, '我说的是牛肉炒面啊。', settings))

    def test_name_only_before_question_binds_local_dish(self):
        conn = SimpleNamespace()
        settings = {'path': str(DEFAULT_CATALOG)}
        # 只报菜名时不反问想了解什么，交给库存/模型回答有没有货，
        # 但必须记住指代对象，下一句问过敏原才答得出来。
        self.assertIsNone(local_menu_turn(conn, '牛肉炒面。', settings))
        self.assertIn('鸡蛋', local_menu_turn(conn, '过敏原有吗？', settings))

    def test_unrelated_turn_does_not_keep_stale_pending_question(self):
        conn = SimpleNamespace()
        settings = {'path': str(DEFAULT_CATALOG)}
        local_menu_turn(conn, '牛肉面的成分是什么？', settings)
        self.assertIsNone(local_menu_turn(conn, '现在有多少种商品？', settings))
        self.assertIsNone(local_menu_turn(conn, '牛肉炒面。', settings))
        # 陈旧的 pending 不能残留：上一问的「成分」不该套到新菜名上。
        self.assertIn('鸡蛋', local_menu_turn(conn, '过敏原有吗？', settings))

    def test_concise_allergens_keep_full_contains_and_trace_statement(self):
        settings = {'path': str(DEFAULT_CATALOG), 'concise_voice': True}
        answer, ident = self.answer('牛肉炒面过敏原有哪些？', settings=settings)
        self.assertEqual(ident, '537')
        self.assertIn('含有小麦、鸡蛋、大豆', answer)
        self.assertIn('可能含微量：芝麻、芹菜、牛奶', answer)
        self.assertNotIn('结构化', answer)
        self.assertLess(len(answer), 90)
        conn = SimpleNamespace()
        local_menu_turn(conn, '牛肉炒面过敏原有哪些？', settings)
        full = local_menu_turn(conn, '详细说说', settings)
        self.assertIn('结构化过敏原标签', full)
        self.assertIn('Cereals containing gluten', full)
        self.assertIn('7.99', local_menu_turn(conn, '那多少钱？', settings))

    def test_concise_mode_never_drops_additional_allergen_tags(self):
        import copy
        catalog = copy.deepcopy(load_catalog(str(DEFAULT_CATALOG)))
        dish = next(d for d in catalog['dishes'] if d['id'] == '537')
        dish['allergen_tags'] += '；花生（Peanuts）'
        with patch('core.utils.menu_knowledge.load_catalog', return_value=catalog):
            answer, _ = self.answer('牛肉炒面过敏原', settings={'concise_voice': True})
        self.assertIn('花生（Peanuts）', answer)
        self.assertIn('标签不区分', answer)

    def test_stock_pronoun_uses_only_resolved_dish(self):
        from core.utils.menu_knowledge import resolve_stock_followup
        settings = {'path': str(DEFAULT_CATALOG)}
        conn = SimpleNamespace(last_local_menu_id='537')
        self.assertEqual(resolve_stock_followup(conn, '它还有吗？', settings), '牛肉炒面还有吗？')
        self.assertEqual(resolve_stock_followup(conn, '咖啡还有吗？', settings), '咖啡还有吗？')
        conn.last_local_menu_id = None
        self.assertEqual(resolve_stock_followup(conn, '它还有吗？', settings), '它还有吗？')

    def test_local_menu_handshake_does_not_prefetch_inventory(self):
        tree = ast.parse((DEFAULT_CATALOG.parents[2] / 'core/connection.py').read_text())
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_init_prompt_enhancement')
        namespace = {}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<real handshake>', 'exec'), namespace)
        conn = SimpleNamespace(config={'local_menu_knowledge':{'path':str(DEFAULT_CATALOG)}, 'turn_context_refresh':{'local_count_answers':True},'context_providers':[{'url':'http://test'}]})
        with patch('core.utils.turn_context.refresh_turn_context', side_effect=AssertionError('API called')):
            namespace['_init_prompt_enhancement'](conn)

    def test_chat_returns_before_refresh_or_llm(self):
        # Extract the real method to avoid unrelated audio/GPU initialization.
        source = (DEFAULT_CATALOG.parents[2] / 'core/connection.py').read_text()
        tree = ast.parse(source)
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'chat')
        namespace = {'uuid':uuid,'Message':Message,'TTSMessageDTO':TTSMessageDTO,
                     'SentenceType':SentenceType,'ContentType':ContentType,'TAG':'test'}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<real chat>', 'exec'), namespace)
        conn = SimpleNamespace(config={'local_menu_knowledge':{'path':str(DEFAULT_CATALOG)}},
            logger=Mock(), dialogue=Mock(), tts=SimpleNamespace(tts_text_queue=queue.Queue(),store_tts_text=Mock()))
        with patch('core.utils.turn_context.refresh_turn_context', side_effect=AssertionError('API called')):
            self.assertTrue(namespace['chat'](conn,'牛肉炒面过敏原有哪些？'))
        self.assertEqual(conn.last_local_menu_id, '537')
        # 本地直答按句入队（2026-10-05 起），条数随句子数变；要保证的是 FIRST 开头、LAST 收尾、
        # 中间全是文字，拼起来就是记录下来的整段回答
        queued = [conn.tts.tts_text_queue.get() for _ in range(conn.tts.tts_text_queue.qsize())]
        self.assertEqual(queued[0].sentence_type, SentenceType.FIRST)
        self.assertEqual(queued[-1].sentence_type, SentenceType.LAST)
        middle = queued[1:-1]
        self.assertTrue(middle and all(m.content_type == ContentType.TEXT for m in middle))
        self.assertEqual(''.join(m.content_detail for m in middle), conn.tts.store_tts_text.call_args.args[1])
        with patch('core.utils.turn_context.refresh_turn_context', side_effect=AssertionError('API called')):
            for query in ['牛肉面的成分是什么？', '牛肉面。', '肉场面的成分是什么？', '牛肉炒面。']:
                self.assertTrue(namespace['chat'](conn, query))
        self.assertEqual(conn.last_local_menu_id, '537')
        self.assertIn('牛肉片', conn.tts.store_tts_text.call_args.args[1])

if __name__ == '__main__':
    unittest.main()
