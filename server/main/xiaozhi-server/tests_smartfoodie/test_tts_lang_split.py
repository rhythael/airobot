# SmartFoodie 041 语音助手 · 定制模块 · 作者 Heyao Rong（2026-09 至 2026-10）· 不属于上游 xiaozhi-esp32-server
# SmartFoodie 041 voice assistant · custom module · author Heyao Rong (2026-09 to 2026-10) · not part of upstream xiaozhi-esp32-server
"""按语言切句：一句话里的中文、德语、英语各交给对应音色。句子都取自实机日志。"""

import json
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER))

from core.utils.tts_lang_split import dish_languages, split_by_language

CATALOG = json.loads((SERVER / "resources/smartfoodie/menu_catalog.json").read_text())
DISHES = dish_languages([d.get("name") for d in CATALOG["dishes"]])


def langs(text):
    return [lang for lang, _ in split_by_language(text, DISHES)]


def joined(text):
    return "".join(part for _, part in split_by_language(text, DISHES))


def test_single_language_is_one_piece():
    assert langs("鸡肉蔬菜蒸饺在一号七货道，现在还有三份。") == ["zh"]
    assert langs("Vier Gerichte sind gerade verfügbar.") == ["de"]
    assert langs("There are twelve products available right now.") == ["en"]


def test_chinese_sentence_with_german_dish():
    text = "现在还有货的有鸡肉蔬菜蒸饺、虾饺，还有1份Tagliatelle mit Kalbsgeschnetzeltem in Champignon-Rahmsauce"
    pieces = split_by_language(text, DISHES)
    assert [p[0] for p in pieces] == ["zh", "de"]
    assert pieces[0][1].endswith("还有1份")  # 数字跟着中文念
    assert pieces[1][1].startswith("Tagliatelle")


def test_german_sentence_with_chinese_dish():
    assert langs("Du findest unter anderem 牛肉炒面 und Dampfnudel mit Vanillesauce und Kirschen.") == [
        "de", "zh", "de"]


def test_english_sentence_routes_german_dish_to_german():
    text = "We have Wiesnschmaus Bowl mit Kartoffelsalat und Leberkäswürfeln and shrimp dumplings."
    pieces = split_by_language(text, DISHES)
    assert [p[0] for p in pieces] == ["en", "de", "en"]
    assert "Wiesnschmaus" in pieces[1][1]


def test_german_sentence_routes_english_dish_to_english():
    pieces = split_by_language("Es gibt noch Korean Spicy Chicken Noodles im Fach eins drei.", DISHES)
    assert [p[0] for p in pieces] == ["de", "en", "de"]


def test_chinese_sentence_with_english_dish():
    assert langs("还有Korean Spicy Chicken Noodles和虾饺") == ["zh", "en", "zh"]


def test_short_latin_fragments_stay_chinese():
    assert langs("请到A区取餐，OK吗") == ["zh"]
    # 中文句里夹一个英文词，不为它换音色
    assert langs("我是Smartfoodie的语音小助手") == ["zh"]
    assert langs("可以用PayPal付款") == ["zh"]


def test_english_sentence_keeps_short_english_words():
    """以英文为主的句子里，夹在中文菜名之间的 and 仍用英文音色。"""
    text = "Tagliatelle mit Kalbsgeschnetzeltem in Champignon-Rahmsauce, 虾饺 and 红烧牛肉面. Note that it is expired."
    assert "en" in langs(text)


def test_slot_numbers_stay_with_their_sentence():
    assert langs("Es liegt in 1-7. Guten Appetit.") == ["de"]
    assert langs("041号机器现在有9个空货道") == ["zh"]


def test_slot_numbers_between_chinese_dishes_are_read_in_german():
    """货道号是取餐依据。德语句里夹在中文菜名之间的货道号不能被中文音色念成「二杠六」。"""
    text = "Am Automaten 041 gibt es aktuell vier Gerichte zur Auswahl: 1-6 鸡肉蔬菜蒸饺，2-6 虾饺 und 2-9 红烧牛肉面."
    pieces = split_by_language(text, DISHES)
    for lang, part in pieces:
        if lang == "zh":
            assert not any(slot in part for slot in ("1-6", "2-6", "2-9")), pieces
    assert joined(text) == text


def test_chinese_counts_stay_chinese():
    pieces = split_by_language("还有1份Tagliatelle mit Kalbsgeschnetzeltem in Champignon-Rahmsauce 2份", DISHES)
    assert pieces[0] == ("zh", "还有1份")
    assert pieces[-1][0] == "zh" and "2" in pieces[-1][1]


def test_nothing_is_lost_or_reordered():
    for text in (
        "有牛肉炒面、Wiesnschmaus Bowl mit Kartoffelsalat und Leberkäswürfeln和Dampfnudel mit Vanillesauce und Kirschen，还有很多其他餐",
        "Tagliatelle mit Kalbsgeschnetzeltem in Champignon-Rahmsauce, 虾饺（10粒）, and 红烧牛肉面. No items are sold out",
        "虾饺enthält Weizenstärke",
    ):
        assert joined(text) == text


def test_dish_language_classification():
    table = dict(DISHES)
    assert table["Korean Spicy Chicken Noodles"] == "en"
    assert table["Dampfnudel mit Vanillesauce und Kirschen"] == "de"
    assert table["Rindergulasch mit Fusilli"] == "de"
    assert table["Beef Goulash with Fusilli"] == "en"
    assert "ball" not in table


def test_empty_and_punctuation_only():
    assert split_by_language("", DISHES) == []
    assert split_by_language("1-7", DISHES) == [("de", "1-7")]


def test_short_replies_get_the_right_latin_language():
    """实机上真说过的短句，这些必须认对。"""
    from core.utils.tts_lang_split import detect_latin
    for text in ("Ja, gerne. Wie kann ich dir helfen?", "Ja", "gerne", "Hallo, wie kann ich dir helfen?",
                 "Gerne, ich spreche Deutsch", "Was möchtest du wissen?", "Vier Gerichte sind verfügbar"):
        assert detect_latin(text) == "de", text
    for text in ("Sure", "Got it, speaking English now", "Which kind interests you?",
                 "There are 12 products available", "It was expired", "Hello! How can I help?"):
        assert detect_latin(text) == "en", text


def test_unknown_latin_uses_the_given_default():
    assert langs("Spaghetti") in (["de"],)
    assert [l for l, _ in split_by_language("Mochi", DISHES, default_latin="en")] == ["en"]


def test_english_frame_with_many_chinese_dishes():
    """句子骨架是英文，中文菜名再多也不能把 and、货道号划给中文音色。"""
    pieces = split_by_language(
        "Right now you can get four items from machine 041: 鸡肉蔬菜蒸饺(10粒), 虾饺 and 红烧牛肉面.", DISHES)
    assert pieces[0][0] == "en" and "041" in pieces[0][1]
    assert any(lang == "en" and "and" in part for lang, part in pieces)
