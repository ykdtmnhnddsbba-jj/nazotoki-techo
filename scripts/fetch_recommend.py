#!/usr/bin/env python3
"""謎ログAPI（非公式・ログイン不要の公開データ）から、東海・近畿（静岡〜和歌山）で
今月〜再来月（3か月）に開催中/開催予定の公演を集めて recommend.json に書き出す。
負荷をかけないよう、リクエスト間に間隔をあける。"""
import json, sys, time, datetime, re, urllib.request, urllib.parse
from html.parser import HTMLParser

API = "https://api.nazo.site/api/v1"
SITE = "https://www.nazo.site"
# 東海＝静岡・愛知・岐阜・三重／近畿＝滋賀・京都・大阪・兵庫・奈良・和歌山（地域の分け方は手帖側 index.html の REGIONS と合わせる）
PREFS = {22: "静岡県", 21: "岐阜県", 23: "愛知県", 24: "三重県",
         25: "滋賀県", 26: "京都府", 27: "大阪府", 28: "兵庫県", 29: "奈良県", 30: "和歌山県"}
OPEN_END = "9999-12-31"
GAP = 0.7  # 秒

def get(path, params):
    url = API + path + "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"User-Agent": "nazotoki-techo-recommend/1.0"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            time.sleep(GAP)
            return data
        except Exception as e:
            if i == 2:
                raise
            time.sleep(3 * (i + 1))

def paged(path, params, key):
    out, page = [], 1
    while True:
        d = get(path, {**params, "per": 100, "page": page})
        out += d.get(key, [])
        if page >= d.get("totalPages", 1):
            return out
        page += 1

N_MONTHS = 3  # 今月・来月・再来月

def month_range(today):
    """今月から N_MONTHS か月分の各月1日と、期間の最終日を返す"""
    firsts = [today.replace(day=1)]
    for _ in range(N_MONTHS):
        firsts.append((firsts[-1] + datetime.timedelta(days=32)).replace(day=1))
    return firsts[:-1], firsts[-1] - datetime.timedelta(days=1)

# ---- 店舗HP（謎ログに会場が未登録の公演を拾う）----
# SCRAP の店舗ページのイベント一覧。週1回、1ページだけ読む。
SHOP_PAGES = [("https://realdgame.jp/shop/nagoya/events/", "リアル脱出ゲーム名古屋店", "愛知県")]
SHOP_FMT = [("館内周遊型", "field"), ("街歩き型", "field"), ("周遊型", "field"), ("ホール型", "hall"),
            ("ルーム型", "room"), ("スタジアム型", "stadium"), ("キューブ型", "cube"), ("持ち帰り型", "kit")]

def norm(t):
    t = re.sub(r"[（(]リバイバル[)）]", "", t or "")
    return re.sub(r"[\s　~〜～\-－・:：!！?？()（）「」『』×✕]", "", t).lower()

class _Links(HTMLParser):
    """<a> ごとに href・画像の alt・中の文字を集める"""
    def __init__(self):
        super().__init__(); self.out = []; self.cur = None; self.depth = 0
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a":
            if self.cur is None:
                self.cur = {"href": a.get("href", ""), "alt": "", "text": []}; self.depth = 0
            self.depth += 1
        elif tag == "img" and self.cur is not None and not self.cur["alt"]:
            self.cur["alt"] = (a.get("alt") or "").strip()
    def handle_endtag(self, tag):
        if tag == "a" and self.cur is not None:
            self.depth -= 1
            if self.depth <= 0:
                self.out.append(self.cur); self.cur = None
    def handle_data(self, d):
        if self.cur is not None and d.strip():
            self.cur["text"].append(d.strip())

DATE_RE = re.compile(r"開催[：:]?\s*(\d{4})\.(\d{1,2})\.(\d{1,2})[^〜~～]*[〜~～]\s*(?:(?:(\d{4})\.)?(\d{1,2})\.(\d{1,2}))?")

def clean_title(t):
    """「【名古屋店】リアル脱出ゲーム×『逃げ上手の若君』『鬼々迫る戦場からの脱出』」→「鬼々迫る戦場からの脱出」"""
    t = re.sub(r"^【[^】]*】", "", t).strip()
    q = re.findall(r"『([^』]+)』", t)
    rev = "（リバイバル）" if re.search(r"[（(]リバイバル[)）]", t) else ""
    return (q[-1] + rev) if q else t

def shop_events(url):
    req = urllib.request.Request(url, headers={"User-Agent": "nazotoki-techo-recommend/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "replace")
    p = _Links(); p.feed(html)
    evs, seen = [], set()
    for a in p.out:
        body = " ".join(a["text"])
        m = DATE_RE.search(body)
        if not m:
            continue
        title = a["alt"]
        if not title:  # alt がなければ、仕様（「60分」など）より前の文字。名前が2回続くときは半分にする
            head = re.split(r"\s\d+分|\s開催|\s（前売）|\s\d+人", " " + body, 1)[0].strip()
            ws = head.split(" ")
            h = len(ws) // 2
            title = " ".join(ws[:h]) if len(ws) % 2 == 0 and h and ws[:h] == ws[h:] else head
        start = "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
        end = None
        if m.group(5):  # 終了日の年が省略されていたら開始年（開始より前なら翌年）
            y = int(m.group(4) or m.group(1))
            end = "%d-%02d-%02d" % (y, int(m.group(5)), int(m.group(6)))
            if not m.group(4) and end < start:
                end = "%d-%02d-%02d" % (y + 1, int(m.group(5)), int(m.group(6)))
        cat = "other"
        for k, v in SHOP_FMT:
            if k in body:
                cat = v; break
        title = clean_title(title)
        href = urllib.parse.urljoin(url, a["href"])
        if (title, start) in seen:
            continue
        seen.add((title, start))
        evs.append({"title": title, "start": start, "end": end, "category": cat, "url": href})
    return evs

def find_content_id(title):
    """謎ログの作品検索で作品IDを探す（予定・参加済みの判定に使う）。見つからなければ None"""
    try:
        d = get("/contents", {"q[keyword]": re.sub(r"[（(]リバイバル[)）]", "", title).strip(), "per": 10})
    except Exception:
        return None
    n = norm(title)
    best = None
    for c in d.get("contents", []):
        t = norm(c.get("title"))
        if len(t) >= 4 and (t in n or n in t) and (best is None or len(t) > len(norm(best["title"]))):
            best = c
    return best["id"] if best else None

def add_shop_items(items, first, last, today):
    known = [norm(i["title"]) for i in items]
    added = 0
    for url, venue, pref in SHOP_PAGES:
        try:
            evs = shop_events(url)
        except Exception as e:
            print(f"shop page skipped ({url}): {e}")
            continue
        print(f"shop page {url}: {len(evs)} events")
        for e in evs:
            print(f"    · {e['title']} {e['start']}〜{e['end'] or ''} {e['category']}")
        for e in evs:
            if e["start"] > last or (e["end"] and e["end"] < max(first, today)):
                continue
            n = norm(e["title"])
            if any(len(k) >= 4 and (k in n or n in k) for k in known):
                continue  # 謎ログにある
            cid = find_content_id(e["title"])
            items.append({
                "contentId": cid or "shop-" + n[:40], "title": e["title"], "category": e["category"],
                "venue": venue, "pref": pref, "start": e["start"], "end": e["end"], "permanent": not e["end"],
                "price": None, "playable": True, "url": e["url"], "group": "SCRAP", "groups": ["SCRAP"], "shop": True,
            })
            known.append(n); added += 1
            print(f"  + {e['title']} {e['start']}〜{e['end'] or ''} ({cid})")
    return added

def main():
    today = datetime.date.today()
    months, last = month_range(today)
    first = months[0]
    venues = {}
    for code, name in PREFS.items():
        for v in paged("/venues", {"q[prefecture_code_eq]": code}, "venues"):
            venues[v["id"]] = {"name": v["name"], "pref": name, "address": v.get("address")}
    scenes = []
    for code in PREFS:  # 会場の県コードで公演を絞り込める
        scenes += paged("/content_scenes", {
            "q[venue_prefecture_code_eq]": code,
            "q[end_date_gteq]": first.isoformat(),
            "q[start_date_lteq]": last.isoformat(),
            "include": json.dumps(["content"]),
        }, "contentScenes")
    items, seen = [], set()
    for s in scenes:
        if s.get("canceled"):
            continue
        c = s.get("content") or {}
        v = venues.get(s.get("venueId"))
        if not v or not c:
            continue
        key = (c["id"], s["venueId"])
        if key in seen:
            continue
        seen.add(key)
        permanent = s["endDate"] == OPEN_END
        if not permanent and s["endDate"] < today.isoformat():
            continue
        items.append({
            "contentId": c["id"], "title": c["title"], "category": c.get("contentCategoryId"),
            "venue": v["name"], "pref": v["pref"], "start": s["startDate"],
            "end": None if permanent else s["endDate"], "permanent": permanent,
            "price": c.get("price"), "playable": c.get("currentlyPlayable"),
            "url": SITE + c["frontendPath"],
            "group": "",
        })
    # 団体名
    cids = sorted({i["contentId"] for i in items})
    groups = {}
    try:  # 前回の結果にある団体名は再取得しない（API呼び出しを減らす）
        for it in json.load(open("recommend.json", encoding="utf-8")).get("items", []):
            if it.get("groups"):
                groups[it["contentId"]] = it["groups"]
    except Exception:
        pass
    for cid in cids:
        if cid in groups:
            continue
        c = get("/contents/" + cid, {})
        c = c.get("content", c)
        groups[cid] = [x["name"] for x in c.get("creators", [])]
    for it in items:
        g = groups.get(it["contentId"], [])
        it["group"] = "SCRAP" if "SCRAP" in g else (g[0] if g else "")
        it["groups"] = g
    # 店舗HPにしかない公演（謎ログに会場が未登録）
    add_shop_items(items, first.isoformat(), last.isoformat(), today.isoformat())
    # 手動で足す・上書きする公演（謎ログの期間が古い／載っていないもの）
    try:
        manual = json.load(open("manual-recommend.json", encoding="utf-8")).get("items", [])
    except FileNotFoundError:
        manual = []
    for m in manual:
        if m.get("end") and m["end"] < today.isoformat():
            continue
        items = [i for i in items if not (
            (m.get("contentId") and i["contentId"] == m["contentId"]) or
            (i["title"] == m["title"] and i["venue"] == m.get("venue")))]
        items.append({
            "contentId": m.get("contentId") or "manual-" + m["title"], "title": m["title"],
            "category": m.get("category", "field"), "venue": m.get("venue", ""), "pref": m.get("pref", "愛知県"),
            "start": m.get("start", today.isoformat()), "end": m.get("end"), "permanent": not m.get("end"),
            "price": m.get("price"), "playable": True, "url": m.get("url", ""),
            "group": m.get("group", ""), "groups": [m["group"]] if m.get("group") else [], "manual": True,
        })
    items.sort(key=lambda x: (x["permanent"], x["end"] or "", x["start"], x["title"]))
    out = {
        "generated_at": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec="minutes"),
        "months": [m.strftime("%Y-%m") for m in months],
        "window": [first.isoformat(), last.isoformat()],
        "source": "nazo.site+realdgame.jp",
        "items": items,
    }
    json.dump(out, open(sys.argv[1] if len(sys.argv) > 1 else "recommend.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"{len(items)} items, {len(venues)} venues")

if __name__ == "__main__":
    main()
