#!/usr/bin/env python3
"""謎ログAPI（非公式・ログイン不要の公開データ）から、愛知・岐阜・三重で
今月〜来月に開催中/開催予定の公演を集めて recommend.json に書き出す。
負荷をかけないよう、リクエスト間に間隔をあける。"""
import json, sys, time, datetime, urllib.request, urllib.parse

API = "https://api.nazo.site/api/v1"
SITE = "https://www.nazo.site"
PREFS = {21: "岐阜県", 23: "愛知県", 24: "三重県"}
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

def month_range(today):
    first = today.replace(day=1)
    nxt = (first + datetime.timedelta(days=32)).replace(day=1)
    after = (nxt + datetime.timedelta(days=32)).replace(day=1)
    return first, nxt, after - datetime.timedelta(days=1)

def main():
    today = datetime.date.today()
    first, nxt, last = month_range(today)
    venues = {}
    for code, name in PREFS.items():
        for v in paged("/venues", {"q[prefecture_code_eq]": code}, "venues"):
            venues[v["id"]] = {"name": v["name"], "pref": name, "address": v.get("address")}
    ids = list(venues)
    scenes = []
    for i in range(0, len(ids), 50):
        scenes += paged("/content_scenes", {
            "q[venue_id_in]": ids[i:i + 50],
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
    for cid in cids:
        c = get("/contents/" + cid, {})
        c = c.get("content", c)
        groups[cid] = [x["name"] for x in c.get("creators", [])]
    for it in items:
        g = groups.get(it["contentId"], [])
        it["group"] = "SCRAP" if "SCRAP" in g else (g[0] if g else "")
        it["groups"] = g
    items.sort(key=lambda x: (x["permanent"], x["end"] or "", x["start"], x["title"]))
    out = {
        "generated_at": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec="minutes"),
        "months": [first.strftime("%Y-%m"), nxt.strftime("%Y-%m")],
        "window": [first.isoformat(), last.isoformat()],
        "source": "nazo.site",
        "items": items,
    }
    json.dump(out, open(sys.argv[1] if len(sys.argv) > 1 else "recommend.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"{len(items)} items, {len(venues)} venues")

if __name__ == "__main__":
    main()
