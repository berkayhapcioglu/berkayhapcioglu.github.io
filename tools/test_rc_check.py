#!/usr/bin/env python3
"""rc_check.py'nin kendi denetimi: canlı rc.json ve yayın günü yazması geçmeli, bilinen hatalar yakalanmalı.

Çalıştır: python3 tools/test_rc_check.py   (GitHub Actions da her değişiklikte çalıştırır)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rc_check  # noqa: E402

SCHEMA = json.load(open(os.path.join(HERE, "rc-schema.json"), encoding="utf-8"))
LIVE_TEXT = open(os.path.join(os.path.dirname(HERE), "kinglegends", "rc.json"), encoding="utf-8").read()
LIVE = json.loads(LIVE_TEXT)

fails = 0
count = 0


def run(obj_or_text):
    text = obj_or_text if isinstance(obj_or_text, str) else json.dumps(obj_or_text, ensure_ascii=False)
    rep, _ = rc_check.check(text, SCHEMA)
    return rep


def expect(name, obj, errors=None, warnings=None, error_has=None, warning_has=None):
    """errors / warnings: beklenen sayı (None: bakma). *_has: o metni içeren bir satır olmalı."""
    global fails, count
    count += 1
    rep = run(obj)
    problems = []
    if errors is not None and len(rep.errors) != errors:
        problems.append("hata sayısı %d (beklenen %d): %s" % (len(rep.errors), errors, rep.errors))
    if warnings is not None and len(rep.warnings) != warnings:
        problems.append("uyarı sayısı %d (beklenen %d): %s" % (len(rep.warnings), warnings, rep.warnings))
    if error_has and not any(error_has in e for e in rep.errors):
        problems.append("'%s' hatası yok: %s" % (error_has, rep.errors))
    if warning_has and not any(warning_has in w for w in rep.warnings):
        problems.append("'%s' uyarısı yok: %s" % (warning_has, rep.warnings))
    if problems:
        fails += 1
        print("HATA " + name + ": " + "; ".join(problems))


def live(**over):
    d = dict(LIVE)
    d.update(over)
    return d


# ---- Geçmesi şart olanlar (oyun kodu thread'inin şartı)
expect("canlı rc.json", LIVE_TEXT, errors=0)
expect("yayın günü yazması (unlockByDay + globalChat)", live(unlockByDay=True, globalChat=True), errors=0)
expect("boş dosya {}", "{}", errors=0, warnings=0)
expect("bilinmeyen anahtar yalnız uyarı", live(eskiAnahtar=3), errors=0, warning_has="şemada yok")
expect("yazım hatası önerisi", live(goldScal=0.9), errors=0, warning_has="goldScale")

# ---- Dosya düzeyi
expect("bozuk JSON", '{"goldScale": 1,}', error_has="JSON okunamadı")
expect("kök dizi", "[1,2]", error_has="kök bir nesne")
expect("aynı anahtar iki kez", '{"goldScale": 0.9, "goldScale": 9}', error_has="iki kez")
expect("NaN", '{"goldScale": NaN}', error_has="NaN")
expect("sonsuz sayı", '{"goldScale": 1e400}', error_has="sonsuz")
expect("int taşması", live(lateRealmFrom=2**40), error_has="sığmaz")

# ---- Tür ve değer
expect("bool yerine metin", live(globalChat="true"), error_has="true ya da false")
expect("bool yerine 1", live(globalChat=1), error_has="true ya da false")
expect("tam sayıya 1.5", live(lateRealmFrom=1.5), errors=1)
expect("tam sayıya 25.0", live(lateRealmFrom=25.0), error_has="25 yaz")
expect("sayı yerine metin", live(goldScale="0.9"), error_has="sayı olmalı")
expect("sınır dışı: altın çarpanı 10", live(goldScale=10), error_has="aralığın dışında")
expect("sınır içi: altın çarpanı 1.1", live(goldScale=1.1), errors=0)
expect("eksi değer", live(reviveBossStun=-5), error_has="eksi")
expect("eksi serbest alan", live(resultAdSlots=-1), errors=0)
expect("varsayılanı eksi alan", live(weekTheme=-1), errors=0)
expect("10 kat uzak: uyarı", live(reviveBossStun=200), errors=0, warning_has="10 kattan")
expect("dizi yerine sayı", live(challengeToughRealms=1.2), error_has="dizi olmalı")
expect("dizide metin", live(challengeToughRealms=[1, "a"]), error_has="sayı olmalı")
expect("dizide eksi", live(challengeToughRealms=[1, -1]), error_has="eksi")
expect("kısa dizi uyarısı", live(challengeToughRealms=[1, 1]), errors=0, warning_has="dizi kısa")

# ---- targets
ok_targets = live(targets=[
    {"id": "android-chat-off", "platform": "android", "set": {"globalChat": False}},
    {"id": "tf-gold", "channel": "testflight", "minRev": 25, "until": "2099-01-01", "set": {"goldScale": 0.9}},
    {"id": "upd-ios", "platform": "ios", "set": {"updateRev": 26, "storeUrlIos": "https://apps.apple.com/app/id6700000000"}},
])
expect("doğru hedefler", ok_targets, errors=0, warnings=0)
expect("targets dizi değil", live(targets={"a": 1}), error_has="dizi olmalı")
expect("süzgeç yazım hatası", live(targets=[{"id": "x", "plattform": "ios", "set": {"globalChat": False}}]), error_has="bilinmeyen süzgeç")
expect("bilinmeyen platform", live(targets=[{"id": "x", "platform": "iphone", "set": {"globalChat": False}}]), error_has="bilinmiyor")
expect("bilinmeyen kanal", live(targets=[{"id": "x", "channel": "beta", "set": {"globalChat": False}}]), error_has="bilinmiyor")
expect("okunamayan tarih", live(targets=[{"id": "x", "until": "1 Aralık", "set": {"globalChat": False}}]), error_has="tarih okunamadı")
expect("minRev > maxRev", live(targets=[{"id": "x", "minRev": 27, "maxRev": 26, "set": {"globalChat": False}}]), error_has="hiçbir sürüme")
expect("set yok", live(targets=[{"id": "x", "platform": "ios"}]), error_has="nesne olmalı")
expect("set içinde sınır dışı", live(targets=[{"id": "x", "platform": "ios", "set": {"goldScale": 9}}]), error_has="aralığın dışında")
expect("set içinde iç içe hedef", live(targets=[{"id": "x", "platform": "ios", "set": {"targets": []}}]), error_has="iç içe")
expect("süresi geçmiş hedef", live(targets=[{"id": "x", "until": "2020-01-01", "set": {"globalChat": False}}]), errors=0, warning_has="süresi geçmiş")
expect("süzgeçsiz hedef", live(targets=[{"id": "x", "set": {"globalChat": False}}]), errors=0, warning_has="süzgeç yok")
expect("A/B alanı hedefte", live(targets=[{"id": "x", "platform": "ios", "set": {"abTest": "y"}}]), errors=0, warning_has="A/B")

# ---- news
good_news = {"id": "2026-12-04-yama25", "kind": "patch", "date": "2026-12-04T09:00Z",
             "trTitle": "Yama 25", "enTitle": "Patch 25", "trBody": "Yeni boss.", "enBody": "New boss.",
             "link": "https://www.instagram.com/kinglegendsgame/"}
expect("doğru haber", live(news=[good_news]), errors=0, warnings=0)
expect("hedefli haber", live(targets=[{"id": "n-android", "platform": "android", "set": {"news": [good_news]}}]), errors=0)
expect("haber id yok", live(news=[dict(good_news, id="")]), error_has="id gerekli")
expect("aynı haber id", live(news=[good_news, good_news]), error_has="iki kez")
expect("haber http bağlantı", live(news=[dict(good_news, link="http://x.com")]), error_has="https")
expect("haber tarih", live(news=[dict(good_news, date="4.12.2026")]), error_has="tarih okunamadı")
expect("haber türü", live(news=[dict(good_news, kind="update")]), error_has="bilinmiyor")
expect("haber türü info", live(news=[dict(good_news, kind="info")]), errors=0, warnings=0)
expect("haber alan yazım hatası", live(news=[dict(good_news, trTitel="x")]), error_has="trTitle")
expect("haber başlıksız", live(news=[dict(good_news, trTitle="", enTitle="")]), error_has="başlık yok")
expect("haber tek dil", live(news=[dict(good_news, enTitle="")]), errors=0, warning_has="tek dilli")
expect("haber quiet metin", live(news=[dict(good_news, quiet="true")]), error_has="true ya da false")

# ---- Yeni sürüm
expect("updateRev, iPhone bağlantısı yok", live(updateRev=26), errors=0, warning_has="storeUrlIos")
expect("bozuk mağaza bağlantısı", live(storeUrlIos="https://example.com/app"), error_has="mağaza bağlantısı")

# ---- Şema sağlam mı
for k, (lo, hi) in SCHEMA["bounds"].items():
    count += 1
    f = SCHEMA["fields"].get(k)
    if not f or not (lo <= f.get("default", lo) <= hi):
        fails += 1
        print("HATA şema: %s sınırı varsayılanı kapsamıyor" % k)

print("rc_check testleri: %s (%d durum)" % ("tamam" if fails == 0 else "%d HATA" % fails, count))
sys.exit(1 if fails else 0)
