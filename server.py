import json, os, sqlite3, time, hashlib, urllib.request, gzip, subprocess, shutil, datetime, threading
from flask import Flask, request, jsonify, send_from_directory
from bs4 import BeautifulSoup
from turso import TursoDB

app = Flask(__name__)

@app.after_request
def add_cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, PUT, POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return resp

DB_DIR = os.environ.get('DATA_DIR') or './data'
os.makedirs(DB_DIR, exist_ok=True)

os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, 'sync.db')

# 是否启用 Turso 云端数据库（设置 TURSO_URL + TURSO_TOKEN 即生效）
USE_TURSO = bool(os.environ.get('TURSO_URL') and os.environ.get('TURSO_TOKEN'))

def get_db():
    if USE_TURSO:
        return TursoDB(os.environ['TURSO_URL'].strip(), os.environ['TURSO_TOKEN'].strip())
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.execute('''CREATE TABLE IF NOT EXISTS rooms (
        name TEXT PRIMARY KEY, topics TEXT NOT NULL DEFAULT '[]',
        pwd_hash TEXT DEFAULT '', updated REAL DEFAULT 0)''')
    # 兼容旧版本无 pwd_hash 列的表，自动补列，保留已有数据
    cols = [r[1] for r in db.execute("PRAGMA table_info(rooms)")]
    if 'pwd_hash' not in cols:
        db.execute("ALTER TABLE rooms ADD COLUMN pwd_hash TEXT DEFAULT ''")
    db.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, room TEXT, ts REAL,
        user TEXT, action TEXT, detail TEXT)''')
    db.execute('''CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT, room TEXT, week_start REAL,
        data TEXT, created REAL)''')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_rep ON reports(room,week_start)')
    db.commit(); db.close()

init_db()

ONLINE = {}  # room -> {name: last_seen_ts}

def hash_pwd(pwd):
    if not pwd: return ''
    salt = os.urandom(8).hex()
    return salt + ':' + hashlib.sha256((salt + pwd).encode()).hexdigest()

def check_pwd(stored, pwd):
    if not stored: return True
    if not pwd: return False
    try:
        salt, h = stored.split(':', 1)
        return hashlib.sha256((salt + pwd).encode()).hexdigest() == h
    except Exception:
        return False

@app.route('/api/health')
def health():
    return jsonify({'ok': True, 'online_rooms': len(ONLINE)})

@app.route('/')
def index():
    return send_from_directory('/workspace', 'index.html')

@app.route('/manifest.webmanifest')
def manifest():
    return send_from_directory('/workspace', 'manifest.webmanifest'), {'Content-Type': 'application/manifest+json'}

@app.route('/sw.js')
def sw():
    return send_from_directory('/workspace', 'sw.js'), {'Content-Type': 'application/javascript', 'Cache-Control': 'no-cache'}

@app.route('/icon-192.png')
def icon192():
    return send_from_directory('/workspace', 'icon-192.png'), {'Content-Type': 'image/png'}

@app.route('/icon-512.png')
def icon512():
    return send_from_directory('/workspace', 'icon-512.png'), {'Content-Type': 'image/png'}

@app.route('/apple-touch-icon.png')
def apple_icon():
    return send_from_directory('/workspace', 'apple-touch-icon.png'), {'Content-Type': 'image/png'}

@app.route('/api/room/<room>', methods=['GET', 'PUT', 'OPTIONS'])
def room_api(room):
    if request.method == 'OPTIONS':
        return jsonify({})
    name = room.strip()
    pwd = request.args.get('pwd', '')
    user = request.args.get('user', '')
    db = get_db()
    if request.method == 'GET':
        row = db.execute('SELECT topics,pwd_hash FROM rooms WHERE name=?', (name,)).fetchone()
        if row and not check_pwd(row['pwd_hash'], pwd):
            db.close(); return jsonify({'error': '密码错误'}), 401
        topics = json.loads(row['topics']) if row else []
        now = time.time()
        d = ONLINE.setdefault(name, {})
        if user: d[user] = now
        for u in list(d.keys()):
            if now - d[u] > 15: del d[u]
        online = list(d.keys())
        logs = db.execute('SELECT ts,user,action,detail FROM logs WHERE room=? ORDER BY ts DESC LIMIT 20', (name,)).fetchall()
        db.close()
        return jsonify({'topics': topics, 'online': online,
                        'log': [{'ts': r['ts'], 'user': r['user'], 'action': r['action'], 'detail': r['detail']} for r in logs]})
    # PUT
    topics = request.get_json(force=True)
    if not isinstance(topics, list):
        db.close(); return jsonify({'ok': False, 'error': 'topics must be a list'}), 400
    row = db.execute('SELECT pwd_hash FROM rooms WHERE name=?', (name,)).fetchone()
    if row:
        if not check_pwd(row['pwd_hash'], pwd):
            db.close(); return jsonify({'ok': False, 'error': '密码错误'}), 401
        db.execute('UPDATE rooms SET topics=?,updated=? WHERE name=?', (json.dumps(topics, ensure_ascii=False), time.time(), name))
    else:
        db.execute('INSERT INTO rooms (name,topics,pwd_hash,updated) VALUES (?,?,?,?)',
                   (name, json.dumps(topics, ensure_ascii=False), hash_pwd(pwd), time.time()))
    db.commit(); db.close()
    return jsonify({'ok': True})

@app.route('/api/log', methods=['POST', 'OPTIONS'])
def log_api():
    if request.method == 'OPTIONS':
        return jsonify({})
    d = request.get_json(force=True) or {}
    room = (d.get('room') or '').strip(); pwd = d.get('pwd', '')
    db = get_db()
    row = db.execute('SELECT pwd_hash FROM rooms WHERE name=?', (room,)).fetchone()
    if row and not check_pwd(row['pwd_hash'], pwd):
        db.close(); return jsonify({'ok': False, 'error': '密码错误'}), 401
    db.execute('INSERT INTO logs (room,ts,user,action,detail) VALUES (?,?,?,?,?)',
               (room, time.time(), d.get('user', ''), d.get('action', ''), (d.get('detail') or '')[:200]))
    db.commit(); db.close()
    return jsonify({'ok': True})

# ---------- 真实链接抓取（无头浏览器优先，突破 JS 渲染/反爬） + AI 概括 ----------
CHROME = shutil.which('google-chrome-stable') or shutil.which('chromium') or shutil.which('chromium-browser') or '/usr/bin/google-chrome-stable'

def chromium_dump(url, timeout=18):
    """用系统 Chromium 无头渲染页面，返回渲染后的 DOM 文本。失败回退空串。"""
    if not CHROME:
        return ''
    try:
        out = subprocess.run(
            [CHROME, '--headless=new', '--no-sandbox', '--disable-gpu',
             '--disable-dev-shm-usage', '--virtual-time-budget=4000',
             '--run-all-compositor-stages-before-draw', '--dump-dom', url],
            capture_output=True, text=True, timeout=timeout)
        return out.stdout or ''
    except Exception:
        return ''

def urllib_fetch(url, timeout=8):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
            'Accept-Language': 'zh-CN,zh;q=0.9'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get('Content-Encoding', '') == 'gzip':
                raw = gzip.decompress(raw)
            return raw.decode('utf-8', 'ignore')
    except Exception:
        return ''

def fetch_page(url, timeout=8):
    html = chromium_dump(url) or urllib_fetch(url, timeout)
    if not html:
        return {'title': '', 'text': '', 'error': '抓取失败（站点不可达或需登录）'}
    try:
        soup = BeautifulSoup(html, 'html.parser')
        title = ''
        og = soup.find('meta', attrs={'property': 'og:title'}) or soup.find('meta', attrs={'name': 'og:title'})
        if og and og.get('content'): title = og['content'].strip()
        if not title:
            t = soup.find('title')
            if t and t.string: title = t.string.strip()
        desc = ''
        md = soup.find('meta', attrs={'property': 'og:description'}) or soup.find('meta', attrs={'name': 'description'})
        if md and md.get('content'): desc = md['content'].strip()
        # 备注/正文区块（小红书/抖音常放在这些标签里）
        for sel in ['#detail-title', '.note-content', '#note-page', 'article', 'main']:
            node = soup.select_one(sel)
            if node:
                for tag in node(['script', 'style', 'noscript']): tag.decompose()
                extra = ' '.join(node.get_text(separator=' ', strip=True).split())
                if len(extra) > len(desc or ''): desc = extra[:1500]
        for tag in soup(['script', 'style', 'noscript']):
            tag.decompose()
        text = ' '.join(soup.get_text(separator=' ', strip=True).split())
        text = (text or desc)[:1500]
        return {'title': title, 'text': text, 'error': ''}
    except Exception as e:
        return {'title': '', 'text': '', 'error': str(e)[:200]}

def llm_summary(api_base, model, api_key, url, title, text, usertext):
    sys = '你是一个短视频选题助手。请阅读链接信息，用一句不超过20个汉字的话概括这个内容在讲什么。只输出这句概括本身，不要解释、不要引号、不要结尾标点。'
    usr = f"链接：{url}\n页面标题：{title}\n页面正文：{text}\n用户附言：{usertext}\n\n请输出一句话概括："
    payload = {'model': model, 'messages': [{'role': 'system', 'content': sys}, {'role': 'user', 'content': usr}], 'temperature': 0.3, 'max_tokens': 60}
    req = urllib.request.Request(api_base, data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + api_key})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode('utf-8', 'ignore'))
    return data['choices'][0]['message']['content'].strip()

@app.route('/api/fetch', methods=['POST', 'OPTIONS'])
def fetch_api():
    if request.method == 'OPTIONS':
        return jsonify({})
    d = request.get_json(force=True) or {}
    url = (d.get('url') or '').strip()
    if not url:
        return jsonify({'ok': False, 'error': 'no url'})
    r = fetch_page(url)
    return jsonify({'ok': True, **r})

@app.route('/api/summarize', methods=['POST', 'OPTIONS'])
def summarize_api():
    if request.method == 'OPTIONS':
        return jsonify({})
    d = request.get_json(force=True) or {}
    url = (d.get('url') or '').strip()
    usertext = (d.get('text') or '').strip()
    api_base = (d.get('apiBase') or 'https://api.deepseek.com/v1/chat/completions').strip()
    model = (d.get('model') or 'deepseek-chat').strip()
    api_key = (d.get('apiKey') or '').strip()
    fetched = fetch_page(url) if url else {'title': '', 'text': '', 'error': ''}
    if not api_key:
        s = (fetched['title'] or (usertext.split('\n')[0][:24] if usertext else '')) or '来自链接的内容'
        return jsonify({'ok': True, 'summary': s[:24], 'fetchedTitle': fetched['title'], 'fetchedText': fetched['text'], 'noKey': True})
    try:
        summary = llm_summary(api_base, model, api_key, url, fetched['title'], fetched['text'], usertext)
    except Exception as e:
        return jsonify({'ok': False, 'error': 'AI 调用失败：' + str(e)[:200], 'fetchedTitle': fetched['title'], 'fetchedText': fetched['text']})
    return jsonify({'ok': True, 'summary': summary, 'fetchedTitle': fetched['title'], 'fetchedText': fetched['text']})

# ---------- 每周分析（按需补生成，不依赖沙箱常驻） ----------
def compute_week_stats(items, start, end):
    clip_used = {'skill': 0, 'share': 0, 'daily': 0, 'view': 0}
    link_import = 0
    for t in items:
        if t.get('lib') == 'clip' and t.get('cat') in clip_used:
            ua = t.get('usedAt') or 0
            if ua > 1e12: ua /= 1000
            if start <= ua < end: clip_used[t['cat']] += 1
        if t.get('source'):
            ca = t.get('createdAt') or 0
            if ca > 1e12: ca /= 1000
            if start <= ca < end: link_import += 1
    return {'clip_used': clip_used, 'link_import': link_import}

def ensure_room_reports(room, items):
    """保证该房间在 last_monday 之前的每一周都有周报；沙箱休眠错过周一也能在打开时补齐。"""
    now = datetime.datetime.now()
    this_monday = (now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    last_monday = this_monday - datetime.timedelta(days=7)
    last_start = last_monday.timestamp()
    db = get_db()
    row = db.execute('SELECT week_start FROM reports WHERE room=? ORDER BY week_start DESC LIMIT 1', (room,)).fetchone()
    latest = row['week_start'] if row else None
    # 从最新一周的下一周开始补；若从没生成过，最多回填约 12 周
    w = (latest + 7 * 86400) if latest else (last_start - 11 * 7 * 86400)
    while w <= last_start:
        data = compute_week_stats(items, w, w + 7 * 86400)
        data['generated_at'] = time.time()
        db.execute('INSERT OR IGNORE INTO reports (room,week_start,data,created) VALUES (?,?,?,?)',
                   (room, w, json.dumps(data, ensure_ascii=False), time.time()))
        w += 7 * 86400
    db.commit(); db.close()

def gen_weekly_report():
    db = get_db()
    for r in db.execute('SELECT name,topics FROM rooms').fetchall():
        try:
            items = json.loads(r['topics'])
        except Exception:
            continue
        ensure_room_reports(r['name'], items)
    db.close()

@app.route('/api/reports/<room>')
def reports_api(room):
    name = room.strip(); pwd = request.args.get('pwd', '')
    db = get_db()
    row = db.execute('SELECT pwd_hash,topics FROM rooms WHERE name=?', (name,)).fetchone()
    if row and not check_pwd(row['pwd_hash'], pwd):
        db.close(); return jsonify({'error': '密码错误'}), 401
    if row:
        items = json.loads(row['topics'])
        ensure_room_reports(name, items)  # 打开时按需补生成缺失周报（不依赖定时任务常驻）
    rs = db.execute('SELECT week_start,data FROM reports WHERE room=? ORDER BY week_start DESC LIMIT 12', (name,)).fetchall()
    db.close()
    return jsonify([{'week_start': r['week_start'], **json.loads(r['data'])} for r in rs])

_last_report_date = ''
def _scheduler():
    global _last_report_date
    while True:
        time.sleep(60)
        try:
            now = datetime.datetime.now()
            if now.weekday() == 0 and _last_report_date != now.strftime('%Y-%m-%d'):
                gen_weekly_report()
                _last_report_date = now.strftime('%Y-%m-%d')
        except Exception:
            pass
threading.Thread(target=_scheduler, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3001))
    app.run(host='0.0.0.0', port=port, debug=False)
