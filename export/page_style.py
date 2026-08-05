"""
export/page_style.py
====================
Общият стил на ДВЕТЕ лица — дашбордът (`index.html`) и методологията
(`methodology.html`) — на ЕДНО място (мандат №52).

Защо изобщо съществува този файл: №43 корен-прецедентът с палитрата. Щом една
и съща декларация живее на две места, тя се разминава тихо — втората страница
почва да изглежда „почти като" първата и никой тест не пада. Затова тъмната
тема, типографията, картите, таблиците, методологичните заглавия и футърът са
ЕДНА константа, а двата генератора я инжектират в своя `<style>`.

Тук стои САМО общото. Специфичното за едно лице (режимният герой, филмът,
модул-баровете, котвената лента, графиките — само на дашборда; обратният линк
— само на методологията) остава при своя генератор.

Константата е обикновен низ (единични скоби) — тя се ИНТЕРПОЛИРА в f-string,
а интерполираната стойност не се обработва повторно.
"""

BASE_CSS = """
  :root {
    --bg:#0f1117; --card:#1a1d27; --border:#2a2d3e;
    --text:#e2e8f0; --muted:#8892a4; --accent:#7c6af7;
    --pos:#22c55e; --neg:#ef4444;
  }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; padding:20px; }
  a { color:var(--accent); text-decoration:none; }

  .container { max-width:1280px; margin:0 auto; }

  /* Header */
  .header { display:flex; justify-content:space-between; align-items:center; padding:20px 0 30px; border-bottom:1px solid var(--border); margin-bottom:30px; flex-wrap:wrap; gap:10px; }
  .header-left h1 { font-size:1.6em; font-weight:700; }
  .header-left .sub { color:var(--muted); font-size:0.85em; margin-top:4px; }
  .header-right { text-align:right; }
  .updated { color:var(--muted); font-size:0.8em; }

  /* Cards */
  .card { background:var(--card); border-radius:12px; padding:24px; border:1px solid var(--border); }
  .card h2 { font-size:1.1em; color:var(--muted); text-transform:uppercase; letter-spacing:1px; margin-bottom:16px; }

  /* Table */
  table { width:100%; border-collapse:collapse; font-size:0.88em; }
  th { color:var(--muted); font-weight:500; padding:8px 10px; text-align:left; border-bottom:1px solid var(--border); }
  td { padding:9px 10px; border-bottom:1px solid #1e2130; }
  tr:hover td { background:#1e2130; }
  .pos { color:var(--pos); }
  .neg { color:var(--neg); }

  /* Методология (мандат №52: същият стил на двете страници) */
  .methodology { background:var(--card); border:1px solid var(--border); border-radius:12px;
                 padding:18px 24px; margin-bottom:30px; }
  .methodology summary { cursor:pointer; font-weight:600; font-size:0.95em; }
  .methodology h4 { font-size:0.85em; text-transform:uppercase; letter-spacing:0.6px;
                    color:var(--accent); margin:16px 0 4px; }
  .methodology p { color:var(--muted); font-size:0.87em; line-height:1.55; }
  .methodology code { background:#252836; padding:1px 5px; border-radius:4px; font-size:0.92em; }
  .zone-table { width:100%; border-collapse:collapse; font-size:0.82em; margin:10px 0 4px; }
  .zone-table th { font-size:0.95em; padding:6px 8px; }
  .zone-table td { padding:6px 8px; color:var(--muted); vertical-align:top; }

  /* Застояли / тънки наблюдения — маркерите се четат и в двете лица */
  .stale { color:#ff9800; cursor:help; }
  .thin { color:#ff9800; cursor:help; }

  /* Footer */
  footer { text-align:center; color:var(--muted); font-size:0.8em; padding:30px 0 10px; border-top:1px solid var(--border); margin-top:10px; }
"""

# Репото — един адрес за футъра на двете страници.
REPO_URL = "https://github.com/tsvetoslavtsachev/bg-macro-dashboard"
