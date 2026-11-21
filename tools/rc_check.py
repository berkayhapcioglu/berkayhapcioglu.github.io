#!/usr/bin/env python3
"""King Legends: rc.json denetleyicisi (yayından önce çalıştır).

kinglegends/rc.json oyunun bütün sürümlerinin (1.0 dahil) açılışta okuduğu uzak ayardır. Bu betik dosyayı oyunun kendi
şemasına (tools/rc-schema.json; oyun deposundaki Tools/rc_schema.py üretir) göre denetler:

  HATA (çıkış kodu 1, yazma):
    - JSON okunmuyor, kök nesne değil, aynı anahtar iki kez, NaN/Infinity
    - bilinen anahtarın türü yanlış (bool yerine 1, sayı yerine "1", tam sayı alanına 1.5)
    - varsayılanı eksi olmayan alana eksi değer (oyunun "0 ya da eksi: sınırsız" dediği alanlar hariç)
    - sınır tablosu dışında değer (altın çarpanı 1 yerine 10 gibi; tablo oyunun Meta/RcRules.cs'inde)
    - "targets" ve "news" satırlarında yanlış yazılmış süzgeç, okunamayan tarih, https olmayan bağlantı
  uyarı (yazılabilir, gözden geçir):
    - şemada olmayan anahtar (yazım hatası ya da şemadan yeni/eski anahtar; benzer ad önerilir)
    - varsayılandan 10 kattan fazla uzak sayı
    - süresi geçmiş hedef, süzgeçsiz hedef, tek dilli haber, uzun metin

Kullanım:
  python3 tools/rc_check.py                      # kinglegends/rc.json
  python3 tools/rc_check.py yeni-rc.json         # başka dosya
  python3 tools/rc_check.py --quiet              # yalnız hata ve özet
Kök anahtarlar 1.0 dahil her sürüme gider; "targets" ve "news"u yalnız 25 ve sonraki kod okur.
Ayrıntı: oyun deposu Docs/remote-config-safety.md.
"""
import difflib
import json
import math
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RC = os.path.join(os.path.dirname(HERE), "kinglegends", "rc.json")
DEFAULT_SCHEMA = os.path.join(HERE, "rc-schema.json")

MAX_BYTES = 200 * 1024
MAX_TARGETS = 50
TARGET_KEYS = {"id", "platform", "channel", "minRev", "maxRev", "from", "until", "set"}
PLATFORMS = {"ios", "android"}
CHANNELS = {"appstore", "testflight", "android", "dev"}
NEWS_KEYS = {"id", "kind", "date", "until", "trTitle", "trBody", "enTitle", "enBody", "link", "quiet", "platform",
             "channel", "minRev", "maxRev"}
NEWS_KINDS = {"", "patch", "event", "maint", "info"}   # info ve boş: oyunda "Duyuru"
AB_KEYS = {"abTest", "abShareB", "abForce"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?Z?)?$")
STORE_PREFIXES = ("https://apps.apple.com/", "itms-apps://", "https://play.google.com/store/apps/details?id=",
                  "market://details?id=")


class Report:
    def __init__(self):
        self.errors, self.warnings, self.notes = [], [], []

    def err(self, where, msg):
        self.errors.append("%s: %s" % (where, msg))

    def warn(self, where, msg):
        self.warnings.append("%s: %s" % (where, msg))


def parse_utc(s):
    """Oyunla aynı biçimler (RcRules.TryParseUtc): 2026-12-04, 2026-12-04T09:00Z, 2026-12-04 09:00; hep UTC."""
    if not isinstance(s, str) or not DATE_RE.match(s.strip()):
        return None
    t = s.strip().rstrip("Z").replace(" ", "T")
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(t, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def load_json(text, rep):
    dups = []

    def pairs(items):
        d = {}
        for k, v in items:
            if k in d:
                dups.append(k)
            d[k] = v
        return d

    def bad_constant(name):
        raise ValueError("JSON'da %s olmaz (oyun okuyamaz)" % name)

    try:
        data = json.loads(text, object_pairs_hook=pairs, parse_constant=bad_constant)
    except ValueError as e:
        rep.err("dosya", "JSON okunamadı: %s" % e)
        return None
    for k in sorted(set(dups)):
        rep.err(k, "aynı anahtar iki kez yazılmış (oyun sonuncuyu alır, hangisi niyet edildi belli değil)")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def check_scalar(where, ctype, v, rep):
    """Tek değerin türü. Doğruysa True."""
    if ctype == "bool":
        if not isinstance(v, bool):
            rep.err(where, "true ya da false olmalı (yazılan: %s)" % json.dumps(v, ensure_ascii=False))
            return False
    elif ctype in ("int", "long"):
        if is_num(v) and not is_int(v) and float(v).is_integer():
            rep.err(where, "tam sayı olmalı: %s yerine %d yaz" % (v, int(v)))
            return False
        if not is_int(v):
            rep.err(where, "tam sayı olmalı (yazılan: %s)" % json.dumps(v, ensure_ascii=False))
            return False
        if ctype == "int" and not (-2**31 <= v < 2**31):
            rep.err(where, "tam sayı alanına sığmaz (%s)" % v)
            return False
    elif ctype in ("float", "double"):
        if not is_num(v):
            rep.err(where, "sayı olmalı (yazılan: %s)" % json.dumps(v, ensure_ascii=False))
            return False
        if not math.isfinite(v):
            rep.err(where, "sayı çok büyük (sonsuz)")
            return False
    elif ctype == "string":
        if not isinstance(v, str):
            rep.err(where, "metin olmalı, tırnak içinde (yazılan: %s)" % json.dumps(v, ensure_ascii=False))
            return False
    return True


def check_number(where, name, v, field, schema, rep):
    dv = field.get("default")
    neg_ok = name in schema.get("negativeOk", [])
    if v < 0 and (dv is None or dv >= 0) and not neg_ok:
        rep.err(where, "eksi değer (%s); bu alan eksi almaz, oyun varsayılana (%s) döner" % (v, dv))
        return
    b = schema.get("bounds", {}).get(name)
    if b and not (b[0] <= v <= b[1]):
        rep.err(where, "%s izin verilen aralığın dışında [%s, %s] (varsayılan %s)" % (v, b[0], b[1], dv))
        return
    if is_num(dv) and dv != 0 and v != 0:
        ratio = abs(v / dv)
        if ratio > 10 or ratio < 0.1:
            rep.warn(where, "%s varsayılandan (%s) 10 kattan fazla uzak; bilerek mi?" % (v, dv))


def check_known(where, name, v, field, schema, rep):
    ctype = field["type"]
    if ctype.endswith("[]"):
        if not isinstance(v, list):
            rep.err(where, "dizi olmalı: [ ... ] (yazılan: %s)" % json.dumps(v, ensure_ascii=False)[:60])
            return
        if ctype == "object[]":
            if name == "news":
                check_news(where, v, rep)
            else:
                for i, el in enumerate(v):
                    if not isinstance(el, dict):
                        rep.err("%s[%d]" % (where, i), "nesne olmalı: { ... }")
            return
        el_type = ctype[:-2]
        for i, el in enumerate(v):
            if check_scalar("%s[%d]" % (where, i), el_type, el, rep) and is_num(el):
                d = field.get("default") or []
                neg_default = any(is_num(x) and x < 0 for x in d)
                if el < 0 and not neg_default and name not in schema.get("negativeOk", []):
                    rep.err("%s[%d]" % (where, i), "eksi değer (%s); oyun bütün diziyi varsayılana döndürür" % el)
        d = field.get("default")
        if isinstance(d, list) and len(d) > 1 and len(v) < len(d) and ctype != "string[]":
            rep.warn(where, "dizi kısa (%d öğe, varsayılan %d); eksik öğeler varsayılandan gelir mi, kodda bak" % (len(v), len(d)))
        return
    if ctype == "object":
        if not isinstance(v, dict):
            rep.err(where, "nesne olmalı: { ... }")
        return
    if check_scalar(where, ctype, v, rep) and is_num(v):
        check_number(where, name, v, field, schema, rep)


def check_keys(where_prefix, obj, schema, rep, in_target):
    fields = schema["fields"]
    names = list(fields)
    for k, v in obj.items():
        where = where_prefix + k
        if k == "targets":
            if in_target:
                rep.err(where, "hedefin içinde targets olmaz (iç içe hedef okunmaz)")
            else:
                check_targets(where, v, schema, rep)
            continue
        if in_target and k in AB_KEYS:
            rep.warn(where, "A/B denemesi alanları hedeften değişmez (oyun yok sayar); kök düzeyde yaz")
        f = fields.get(k)
        if f is None:
            close = difflib.get_close_matches(k, names, n=1, cutoff=0.8)
            hint = " Bunu mu demek istedin: %s?" % close[0] if close else ""
            rep.warn(where, "şemada yok: yazım hatası ya da şemadan yeni/eski bir anahtar; oyun yok sayar.%s" % hint)
            continue
        check_known(where, k, v, f, schema, rep)


def check_filters(where, item, rep):
    for key in ("platform", "channel"):
        val = item.get(key, "")
        if not isinstance(val, str):
            rep.err(where + "." + key, "metin olmalı")
            continue
        allowed = PLATFORMS if key == "platform" else CHANNELS
        for part in [p.strip().lower() for p in val.split(",") if p.strip()]:
            if part not in allowed:
                rep.err(where + "." + key, "'%s' bilinmiyor (olabilecekler: %s); bu satır hiçbir cihaza uymaz"
                        % (part, ", ".join(sorted(allowed))))
    lo, hi = item.get("minRev", 0), item.get("maxRev", 0)
    for key, val in (("minRev", lo), ("maxRev", hi)):
        if not is_int(val) or val < 0:
            rep.err(where + "." + key, "sıfır ya da artı tam sayı olmalı")
    if is_int(lo) and is_int(hi) and lo > 0 and hi > 0 and lo > hi:
        rep.err(where, "minRev (%d) maxRev'den (%d) büyük: hiçbir sürüme uymaz" % (lo, hi))
    if is_int(lo) and 0 < lo < 25:
        rep.warn(where + ".minRev", "25'ten küçük sürümler targets ve news okumaz; %d yazmak 25 yazmakla aynı" % lo)


def check_targets(where, v, schema, rep):
    if not isinstance(v, list):
        rep.err(where, "dizi olmalı: [ {...}, {...} ]")
        return
    if len(v) > MAX_TARGETS:
        rep.err(where, "en çok %d hedef okunur (%d yazılmış)" % (MAX_TARGETS, len(v)))
    ids = set()
    now = datetime.now(timezone.utc)
    for i, t in enumerate(v):
        w = "%s[%d]" % (where, i)
        if not isinstance(t, dict):
            rep.err(w, "nesne olmalı: {\"id\": ..., \"set\": {...}}")
            continue
        tid = t.get("id", "")
        if tid:
            w = "%s[%s]" % (where, tid)
            if tid in ids:
                rep.warn(w, "aynı id iki kez")
            ids.add(tid)
        else:
            rep.warn(w, "id yok (günlükte #%d diye görünür)" % i)
        for k in t:
            if k not in TARGET_KEYS:
                close = difflib.get_close_matches(k, sorted(TARGET_KEYS), n=1, cutoff=0.6)
                rep.err(w + "." + k, "bilinmeyen süzgeç; yanlış yazılan süzgeç yok sayılır ve ayar beklenenden çok cihaza gider%s"
                        % (" (bunu mu demek istedin: %s?)" % close[0] if close else ""))
        check_filters(w, t, rep)
        for key in ("from", "until"):
            val = t.get(key, "")
            if val and parse_utc(val) is None:
                rep.err(w + "." + key, "tarih okunamadı: %r (örnek: 2026-12-05 ya da 2026-12-05T18:00Z, UTC)" % val)
        until = parse_utc(t.get("until", ""))
        if until and until <= now:
            rep.warn(w, "süresi geçmiş (until %s); silinebilir" % t["until"])
        if not any(t.get(k) for k in ("platform", "channel", "minRev", "maxRev", "from", "until")):
            rep.warn(w, "süzgeç yok: 25 ve sonraki her sürüme gider; herkese gidecekse kök düzeyde yazmak daha açık (1.0 dahil)")
        s = t.get("set")
        if not isinstance(s, dict):
            rep.err(w + ".set", "nesne olmalı: \"set\": {\"anahtar\": değer}")
            continue
        if not s:
            rep.warn(w + ".set", "boş: bu hedef hiçbir şey değiştirmez")
        check_keys(w + ".set.", s, schema, rep, in_target=True)


def check_news(where, items, rep):
    ids = set()
    for i, it in enumerate(items):
        w = "%s[%d]" % (where, i)
        if not isinstance(it, dict):
            rep.err(w, "nesne olmalı")
            continue
        nid = it.get("id", "")
        if not isinstance(nid, str) or not nid:
            rep.err(w, "id gerekli (görüldü kaydı buna bakar), ör. \"2026-12-04-yama25\"")
        else:
            w = "%s[%s]" % (where, nid)
            if nid in ids:
                rep.err(w, "aynı id iki kez: ikincisi görünmez")
            ids.add(nid)
            if "|" in nid:
                rep.err(w, "id'de | olmaz")
        for k, v in it.items():
            if k not in NEWS_KEYS:
                close = difflib.get_close_matches(k, sorted(NEWS_KEYS), n=1, cutoff=0.6)
                rep.err(w + "." + k, "bilinmeyen alan%s" % (" (bunu mu demek istedin: %s?)" % close[0] if close else ""))
            elif k == "quiet":
                if not isinstance(v, bool):
                    rep.err(w + ".quiet", "true ya da false olmalı")
            elif k in ("minRev", "maxRev"):
                pass   # check_filters bakar
            elif not isinstance(v, str):
                rep.err(w + "." + k, "metin olmalı")
        kind = it.get("kind", "")
        if kind not in NEWS_KINDS:
            rep.err(w + ".kind", "'%s' bilinmiyor (patch, event, maint, info ya da boş)" % kind)
        tr, en = it.get("trTitle", ""), it.get("enTitle", "")
        if not tr and not en:
            rep.err(w, "başlık yok (trTitle ve enTitle): satır görünmez")
        elif not tr or not en:
            rep.warn(w, "tek dilli: %s yok, öteki dil gösterilir" % ("trTitle" if not tr else "enTitle"))
        for key in ("trTitle", "enTitle"):
            if isinstance(it.get(key), str) and len(it[key]) > 60:
                rep.warn(w + "." + key, "başlık uzun (%d harf, en çok 60 önerilir)" % len(it[key]))
        for key in ("trBody", "enBody"):
            if isinstance(it.get(key), str) and len(it[key]) > 600:
                rep.warn(w + "." + key, "metin 600 harften uzun; oyun keser")
        date = it.get("date", "")
        if not date:
            rep.warn(w, "date yok: yalnız listede görünür, kart olarak açılmaz")
        for key in ("date", "until"):
            val = it.get(key, "")
            if val and parse_utc(val) is None:
                rep.err(w + "." + key, "tarih okunamadı: %r (örnek: 2026-12-04 ya da 2026-12-04T09:00Z, UTC); satır görünmez" % val)
        link = it.get("link", "")
        if link and (not isinstance(link, str) or not link.startswith("https://") or len(link) > 300):
            rep.err(w + ".link", "yalnız https:// bağlantı (300 harfe kadar); yoksa düğme çıkmaz")
        check_filters(w, it, rep)
    if len(items) > 20:
        rep.warn(where, "%d haber: oyun en yeni 5'ini gösterir, eskileri silinebilir" % len(items))


def check_store(data, rep):
    rev = data.get("updateRev", 0)
    for key in ("storeUrlIos", "storeUrlAndroid"):
        u = data.get(key)
        if isinstance(u, str) and u and not u.startswith(STORE_PREFIXES):
            rep.err(key, "mağaza bağlantısı değil (apps.apple.com, itms-apps, play.google.com ya da market://); kart çıkmaz")
    targets = data.get("targets") if isinstance(data.get("targets"), list) else []
    if is_int(rev) and rev > 0 and not data.get("storeUrlIos"):
        in_targets = any(isinstance(t, dict) and isinstance(t.get("set"), dict) and t["set"].get("storeUrlIos") for t in targets)
        if not in_targets:
            rep.warn("updateRev", "storeUrlIos boş: iPhone'da \"Yeni sürüm hazır\" kartı çıkmaz (App Store bağlantısını yaz)")


def check(text, schema):
    rep = Report()
    if len(text.encode("utf-8")) > MAX_BYTES:
        rep.err("dosya", "%d KB; en çok %d KB (her açılışta her oyuncuya iner)" % (len(text.encode("utf-8")) // 1024, MAX_BYTES // 1024))
    data = load_json(text, rep)
    if data is None:
        return rep, None
    if not isinstance(data, dict):
        rep.err("dosya", "kök bir nesne olmalı: { ... } (oyun başka şeyi yok sayar)")
        return rep, None
    check_keys("", data, schema, rep, in_target=False)
    check_store(data, rep)
    fields = schema["fields"]
    changed = [k for k, v in data.items() if k in fields and fields[k].get("default") != v]
    rep.notes.append("%d anahtar, %d tanesi varsayılandan farklı%s" % (
        len(data), len(changed), "; %d hedef" % len(data["targets"]) if isinstance(data.get("targets"), list) else ""))
    return rep, data


def main(argv):
    quiet = "--quiet" in argv
    args = [a for a in argv if not a.startswith("--")]
    path = args[0] if args else DEFAULT_RC
    schema_path = DEFAULT_SCHEMA
    if "--schema" in argv:
        schema_path = argv[argv.index("--schema") + 1]
        args = [a for a in args if a != schema_path]
        path = args[0] if args else DEFAULT_RC
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    rep, _ = check(text, schema)
    for e in rep.errors:
        print("HATA  " + e)
    if not quiet:
        for w in rep.warnings:
            print("uyarı " + w)
    for n in rep.notes:
        print("bilgi " + n)
    verdict = "geçmedi, yazma" if rep.errors else "tamam"
    print("rc denetimi: %s (%d hata, %d uyarı; şema %s, %d alan)" % (
        verdict, len(rep.errors), len(rep.warnings), schema.get("commit", "?"), len(schema["fields"])))
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
