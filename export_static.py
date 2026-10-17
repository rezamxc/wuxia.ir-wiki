# export_static.py - تبدیل پایگاه داده به فایل‌های استاتیک JSON برای GitHub Pages
import sqlite3
import os
import json

DB_FILE = "novel_knowledge.db"
OUTPUT_DIR = "."
DATA_DIR = os.path.join(OUTPUT_DIR, "data")
ENTITIES_DIR = os.path.join(DATA_DIR, "entities")

os.makedirs(ENTITIES_DIR, exist_ok=True)

conn = sqlite3.connect(DB_FILE)
conn.row_factory = sqlite3.Row
c = conn.cursor()

print("⏳ در حال استخراج و ساخت آمار کلی...")

# ۱. استخراج آمار و نردبان قلمروها
c.execute("SELECT COUNT(*) FROM processed_files")
ch_count = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM entities")
ent_count = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM entities WHERE category='Character'")
char_count = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM entities WHERE category='Artifact'")
art_count = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM entities WHERE category='Technique'")
tech_count = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM entities WHERE category='Location'")
loc_count = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM entities WHERE category='Faction'")
fac_count = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM relationships")
rel_count = c.fetchone()[0]

c.execute('''
    SELECT current_realm, current_realm_order, COUNT(*) as cnt 
    FROM entities 
    WHERE category = 'Character' AND current_realm != '' AND current_realm != 'نامشخص'
    GROUP BY current_realm, current_realm_order 
    ORDER BY current_realm_order DESC, cnt DESC
''')
realm_stats = [dict(r) for r in c.fetchall()]

stats_payload = {
    "chapters": ch_count,
    "entities": ent_count,
    "characters": char_count,
    "artifacts": art_count,
    "techniques": tech_count,
    "locations": loc_count,
    "factions": fac_count,
    "relationships": rel_count,
    "realm_stats": realm_stats
}

with open(os.path.join(DATA_DIR, "stats.json"), "w", encoding="utf-8") as f:
    json.dump(stats_payload, f, ensure_ascii=False, indent=2)

print("⏳ در حال ساخت کاتالوگ سبک جستجو (catalog.json)...")

# ۲. استخراج کاتالوگ خلاصه برای جستجو و فیلتر سریع
c.execute('''
    SELECT 
        e.zh, e.fa, e.category, e.gender, 
        e.current_realm, e.current_sub_stage, 
        e.current_affiliation, e.current_status, 
        e.first_chapter, e.last_chapter, e.current_realm_order,
        COALESCE((SELECT h.realm_name FROM entity_history h WHERE h.entity_zh = e.zh ORDER BY h.chapter ASC, h.id ASC LIMIT 1), 'نامشخص') as first_realm,
        (SELECT COUNT(*) FROM entity_history h WHERE h.entity_zh = e.zh AND h.event_type = 'BREAKTHROUGH') as breakthrough_count,
        e.description
    FROM entities e ORDER BY e.current_realm_order DESC, e.last_chapter DESC, e.zh ASC
''')
all_entities = c.fetchall()

catalog = []
featured = []

for r in all_entities:
    d = dict(r)
    # جدا کردن پاراگراف اول برای نمایش کوتاه
    short_desc = d['description'].split('|')[0].strip() if d['description'] else ''
    catalog_item = {
        "zh": d['zh'],
        "fa": d['fa'],
        "category": d['category'],
        "gender": d['gender'],
        "current_realm": d['current_realm'],
        "current_sub_stage": d['current_sub_stage'],
        "current_affiliation": d['current_affiliation'],
        "current_status": d['current_status'],
        "first_chapter": d['first_chapter'],
        "last_chapter": d['last_chapter'],
        "current_realm_order": d['current_realm_order'],
        "first_realm": d['first_realm'],
        "breakthrough_count": d['breakthrough_count'],
        "short_desc": short_desc
    }
    catalog.append(catalog_item)
    if d['category'] == 'Character' and len(featured) < 4:
        featured.append(catalog_item)

with open(os.path.join(DATA_DIR, "catalog.json"), "w", encoding="utf-8") as f:
    json.dump({"catalog": catalog, "featured": featured}, f, ensure_ascii=False)

print("⏳ در حال ساخت شناسنامه‌ها و مقالات مجزا برای هر کاراکتر...")

# ۳. ساخت فایل اختصاصی برای هر مدخل (JSON مستقل)
for item in all_entities:
    zh = item['zh']
    
    # تاریخچه
    c.execute('''
        SELECT chapter, event_type, realm_name, sub_stage, realm_order, affiliation, status, milestone_desc, age, appearance 
        FROM entity_history WHERE entity_zh = ? ORDER BY chapter ASC, id ASC
    ''', (zh,))
    history = [dict(h) for h in c.fetchall()]

    # القاب
    c.execute('SELECT alias, chapter FROM aliases WHERE entity_zh = ?', (zh,))
    aliases = [dict(a) for a in c.fetchall()]

    # روابط
    c.execute('''
        SELECT r.*, e.fa as target_fa, e.category as target_cat 
        FROM relationships r 
        LEFT JOIN entities e ON r.target_zh = e.zh 
        WHERE r.source_zh = ?
        ORDER BY r.chapter ASC
    ''', (zh,))
    raw_rels = [dict(r) for r in c.fetchall()]

    grouped_rels = {}
    for r in raw_rels:
        t_zh = r['target_zh']
        display_role = r['target_role'] if r['target_role'] else r['my_role']
        cat = r['category'] or 'social'
        
        if t_zh not in grouped_rels:
            grouped_rels[t_zh] = {
                "target_zh": t_zh,
                "target_fa": r['target_fa'] or t_zh,
                "target_cat": r['target_cat'] or 'Unknown',
                "latest_role": display_role,
                "latest_status": r['status'],
                "category": cat,
                "categories": [cat],
                "history": []
            }
        else:
            if cat not in grouped_rels[t_zh]["categories"]:
                grouped_rels[t_zh]["categories"].append(cat)
                
        grouped_rels[t_zh]["latest_role"] = display_role
        grouped_rels[t_zh]["latest_status"] = r['status']
        grouped_rels[t_zh]["category"] = cat
        grouped_rels[t_zh]["history"].append({
            "chapter": r['chapter'],
            "role": r['my_role'],
            "target_role": r['target_role'],
            "category": cat,
            "reason": r['reason'],
            "status": r['status']
        })

    first_history = history[0] if history else {}
    first_realm_str = f"{first_history.get('realm_name', 'نامشخص')} {first_history.get('sub_stage', '')}".strip()
    first_realm_ch = first_history.get('chapter', item['first_chapter'])

    ent_dict = dict(item)
    ent_dict['first_realm_display'] = first_realm_str
    ent_dict['first_realm_chapter'] = first_realm_ch
    ent_dict['breakthrough_count'] = sum(1 for h in history if h['event_type'] == 'BREAKTHROUGH')

    payload = {
        "entity": ent_dict,
        "history": history,
        "aliases": aliases,
        "grouped_relationships": list(grouped_rels.values())
    }

    # ذخیره فایل جیسون اختصاصی
    file_path = os.path.join(ENTITIES_DIR, f"{zh}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

print("🎉 تمام فایل‌های استاتیک با موفقیت برای گیت‌هاب تولید شدند!")