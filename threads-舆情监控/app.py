import os
import json
import requests
import sqlite3
from flask import Flask, request, redirect, render_template_string, session, jsonify
from dotenv import load_dotenv
from datetime import datetime, timedelta
import re

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)  # 用于 session 加密

# ========== 配置 ==========
APP_ID = os.getenv("THREADS_APP_ID")
APP_SECRET = os.getenv("THREADS_APP_SECRET")
REDIRECT_URI = os.getenv("THREADS_REDIRECT_URI")

# ========== 启动前检查：防止未填 .env 就启动 ==========
def check_env():
    problems = []
    if not APP_ID or "你的Threads" in (APP_ID or ""):
        problems.append("THREADS_APP_ID 未填写（.env 中仍是占位符）")
    if not APP_SECRET or "你的Threads" in (APP_SECRET or ""):
        problems.append("THREADS_APP_SECRET 未填写（.env 中仍是占位符）")
    if not REDIRECT_URI:
        problems.append("THREADS_REDIRECT_URI 未配置")
    return problems

# ========== 数据库初始化（存储 Token） ==========
def init_db():
    conn = sqlite3.connect('tokens.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS token (
            id INTEGER PRIMARY KEY,
            access_token TEXT,
            user_id TEXT,
            expires_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def save_token(access_token, user_id, expires_in):
    """保存长期 Token 到数据库"""
    expires_at = (datetime.now() + timedelta(seconds=expires_in)).isoformat()
    conn = sqlite3.connect('tokens.db')
    c = conn.cursor()
    c.execute('DELETE FROM token')  # 简单起见只保留一个
    c.execute('INSERT INTO token (access_token, user_id, expires_at) VALUES (?, ?, ?)',
              (access_token, user_id, expires_at))
    conn.commit()
    conn.close()

def get_token():
    """从数据库读取 Token"""
    conn = sqlite3.connect('tokens.db')
    c = conn.cursor()
    c.execute('SELECT access_token, user_id, expires_at FROM token ORDER BY id DESC LIMIT 1')
    row = c.fetchone()
    conn.close()
    if row:
        return {'access_token': row[0], 'user_id': row[1], 'expires_at': row[2]}
    return None

def is_token_valid():
    """检查 Token 是否过期"""
    token_data = get_token()
    if not token_data:
        return False
    expires_at = datetime.fromisoformat(token_data['expires_at'])
    return datetime.now() < expires_at

# ========== 页面模板（HTML + CSS） ==========
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Threads 舆情监控 Demo</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
               background: #f5f7fa; padding: 40px 20px; }
        .container { max-width: 900px; margin: 0 auto; }
        .card { background: white; border-radius: 16px; padding: 30px; 
                box-shadow: 0 4px 20px rgba(0,0,0,0.08); margin-bottom: 24px; }
        h1 { font-size: 28px; color: #1a1a2e; margin-bottom: 8px; }
        .subtitle { color: #666; font-size: 14px; margin-bottom: 20px; }
        .status-badge { display: inline-block; padding: 6px 16px; border-radius: 20px;
                        font-size: 14px; font-weight: 600; }
        .status-success { background: #d4edda; color: #155724; }
        .status-error { background: #f8d7da; color: #721c24; }
        .btn { display: inline-block; padding: 12px 28px; border: none; border-radius: 8px;
               font-size: 16px; font-weight: 600; cursor: pointer; text-decoration: none;
               transition: all 0.2s; }
        .btn-primary { background: #1877f2; color: white; }
        .btn-primary:hover { background: #1464d9; transform: translateY(-1px); }
        .btn-success { background: #28a745; color: white; }
        .btn-success:hover { background: #218838; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-danger:hover { background: #c82333; }
        .btn:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
        .input-group { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 12px; }
        .input-group input { flex: 1; min-width: 200px; padding: 12px 16px; 
                             border: 2px solid #e2e8f0; border-radius: 8px; font-size: 16px; }
        .input-group input:focus { outline: none; border-color: #1877f2; }
        .post-item { padding: 16px 20px; border: 1px solid #eef2f7; border-radius: 12px;
                     margin-bottom: 12px; transition: all 0.2s; }
        .post-item:hover { background: #fafbfc; border-color: #d0d7e2; }
        .post-meta { display: flex; gap: 16px; font-size: 13px; color: #888; margin-bottom: 6px; flex-wrap: wrap; }
        .post-content { font-size: 15px; line-height: 1.6; color: #1a1a2e; }
        .sentiment { display: inline-block; padding: 2px 12px; border-radius: 12px;
                     font-size: 13px; font-weight: 600; margin-left: 10px; }
        .sentiment-positive { background: #d4edda; color: #155724; }
        .sentiment-negative { background: #f8d7da; color: #721c24; }
        .sentiment-neutral { background: #e2e3e5; color: #383d41; }
        .loading { color: #666; font-style: italic; }
        .empty-state { text-align: center; padding: 40px 0; color: #999; }
        .flex-between { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
    </style>
</head>
<body>
<div class="container">
    <div class="card">
        <div class="flex-between">
            <div>
                <h1>🔍 Threads 舆情监控</h1>
                <div class="subtitle">监控品牌关键词在 Threads 上的讨论</div>
            </div>
            <div>
                {% if token_valid %}
                    <span class="status-badge status-success">✅ 已授权</span>
                {% else %}
                    <span class="status-badge status-error">❌ 未授权</span>
                {% endif %}
            </div>
        </div>
        
        <div style="margin-top: 16px;">
            {% if token_valid %}
                <a href="/auth" class="btn btn-primary">🔄 重新授权</a>
                <a href="/logout" class="btn btn-danger" style="margin-left: 8px;">🚪 退出</a>
            {% else %}
                <a href="/auth" class="btn btn-primary">🔑 授权 Threads 账号</a>
            {% endif %}
        </div>
    </div>

    {% if token_valid %}
    <div class="card">
        <h3>📊 关键词搜索</h3>
        <p style="color:#666;font-size:14px;">输入你想监控的品牌关键词（英文），系统将搜索 Threads 上的相关帖子并进行情感分析</p>
        <div class="input-group">
            <input type="text" id="keyword" placeholder="例如: Chery, Tesla, Apple..." value="Chery">
            <button class="btn btn-success" onclick="searchPosts()">🔎 搜索</button>
        </div>
        <div id="search-status" style="margin-top: 12px; font-size: 14px; color: #666;"></div>
    </div>

    <div class="card">
        <h3>📝 搜索结果</h3>
        <div id="results">
            <div class="empty-state">输入关键词后点击搜索</div>
        </div>
    </div>
    {% else %}
    <div class="card">
        <div class="empty-state" style="padding: 40px 0;">
            <p style="font-size: 18px; margin-bottom: 12px;">👆 请先点击「授权 Threads 账号」</p>
            <p style="font-size: 14px; color: #aaa;">授权后才能搜索 Threads 内容</p>
        </div>
    </div>
    {% endif %}
</div>

<script>
function searchPosts() {
    const keyword = document.getElementById('keyword').value.trim();
    if (!keyword) {
        alert('请输入关键词');
        return;
    }
    const statusEl = document.getElementById('search-status');
    const resultsEl = document.getElementById('results');
    statusEl.textContent = '⏳ 正在搜索...';
    resultsEl.innerHTML = '<div class="loading">⏳ 加载中...</div>';
    
    fetch('/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keyword: keyword })
    })
    .then(res => res.json())
    .then(data => {
        statusEl.textContent = '✅ 搜索完成，共 ' + (data.count || 0) + ' 条结果';
        if (data.posts && data.posts.length > 0) {
            resultsEl.innerHTML = data.posts.map(p => `
                <div class="post-item">
                    <div class="post-meta">
                        <span>👤 ${p.username || '未知用户'}</span>
                        <span>🕐 ${p.timestamp || '未知时间'}</span>
                        <span class="sentiment sentiment-${p.sentiment_class}">
                            ${p.sentiment_label} (${p.sentiment_score})
                        </span>
                    </div>
                    <div class="post-content">${p.text}</div>
                </div>
            `).join('');
        } else {
            resultsEl.innerHTML = '<div class="empty-state">😕 没有找到包含该关键词的帖子</div>';
        }
    })
    .catch(err => {
        statusEl.textContent = '❌ 搜索失败: ' + err.message;
        resultsEl.innerHTML = '<div class="empty-state">❌ 加载失败，请重试</div>';
    });
}
</script>
</body>
</html>
'''

# ========== 路由 ==========
@app.route('/')
def index():
    """首页"""
    token_valid = is_token_valid()
    return render_template_string(HTML_TEMPLATE, token_valid=token_valid)

@app.route('/auth')
def auth():
    """Step 1: 生成授权 URL，跳转 Meta"""
    auth_url = (
        f"https://threads.com/oauth/authorize?"
        f"client_id={APP_ID}&"
        f"redirect_uri={REDIRECT_URI}&"
        f"scope=threads_basic,threads_read_replies&"
        f"response_type=code"
    )
    return redirect(auth_url)

@app.route('/callback')
def callback():
    """Step 2: Meta 回调，携带 code，兑换 Token"""
    code = request.args.get('code')
    if not code:
        return "授权失败：未收到 code 参数", 400

    # 兑换短期 Token
    token_url = "https://graph.threads.net/oauth/access_token"
    data = {
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI
    }
    resp = requests.post(token_url, data=data)
    if resp.status_code != 200:
        return f"兑换 Token 失败: {resp.text}", 500
    
    short_token_data = resp.json()
    short_token = short_token_data.get('access_token')
    
    # 兑换长期 Token
    long_token_url = "https://graph.threads.net/oauth/access_token"
    long_params = {
        "grant_type": "fb_exchange_token",
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
        "fb_exchange_token": short_token
    }
    long_resp = requests.get(long_token_url, params=long_params)
    if long_resp.status_code != 200:
        return f"兑换长期 Token 失败: {long_resp.text}", 500
    
    long_token_data = long_resp.json()
    access_token = long_token_data.get('access_token')
    expires_in = long_token_data.get('expires_in', 5184000)
    
    # 获取 user_id
    me_resp = requests.get(
        "https://graph.threads.net/v1.0/me",
        params={"access_token": access_token}
    )
    user_id = me_resp.json().get('id', 'unknown') if me_resp.status_code == 200 else 'unknown'
    
    # 保存到数据库
    save_token(access_token, user_id, expires_in)
    
    return redirect('/')

@app.route('/logout')
def logout():
    """清除 Token"""
    conn = sqlite3.connect('tokens.db')
    c = conn.cursor()
    c.execute('DELETE FROM token')
    conn.commit()
    conn.close()
    return redirect('/')

@app.route('/search', methods=['POST'])
def search():
    """关键词搜索 API"""
    if not is_token_valid():
        return jsonify({'error': 'Token 已过期，请重新授权'}), 401
    
    token_data = get_token()
    access_token = token_data['access_token']
    
    data = request.get_json()
    keyword = data.get('keyword', '').strip()
    if not keyword:
        return jsonify({'error': '请输入关键词'}), 400
    
    # 调用 Threads 关键词搜索 API
    search_url = "https://graph.threads.net/v1.0/threads_search"
    params = {
        "query": keyword,
        "access_token": access_token,
        "limit": 20  # 最多返回 20 条
    }
    resp = requests.get(search_url, params=params)
    
    if resp.status_code != 200:
        return jsonify({'error': f'搜索失败: {resp.text}'}), 500
    
    result = resp.json()
    posts = []
    
    # 解析返回的帖子列表
    threads_data = result.get('data', [])
    for thread in threads_data:
        thread_id = thread.get('id')
        if not thread_id:
            continue
        
        # 获取帖子详细信息（内容、用户名等）
        detail_url = f"https://graph.threads.net/v1.0/{thread_id}"
        detail_resp = requests.get(detail_url, params={"access_token": access_token})
        if detail_resp.status_code != 200:
            continue
        
        detail = detail_resp.json()
        text = detail.get('text', '')
        username = detail.get('username', '未知用户')
        timestamp = detail.get('timestamp', '')
        
        # 情感分析
        sentiment_score, sentiment_label, sentiment_class = analyze_sentiment(text)
        
        posts.append({
            'id': thread_id,
            'text': text,
            'username': username,
            'timestamp': timestamp,
            'sentiment_score': sentiment_score,
            'sentiment_label': sentiment_label,
            'sentiment_class': sentiment_class
        })
    
    return jsonify({
        'count': len(posts),
        'posts': posts
    })

# ========== 情感分析模块（英文） ==========
# 简单英文情感词典
POSITIVE_WORDS = {
    'good', 'great', 'excellent', 'amazing', 'wonderful', 'fantastic', 'awesome',
    'love', 'like', 'best', 'perfect', 'happy', 'glad', 'beautiful', 'nice',
    'brilliant', 'outstanding', 'superb', 'terrific', 'magnificent', 'impressive'
}

NEGATIVE_WORDS = {
    'bad', 'terrible', 'awful', 'horrible', 'worst', 'poor', 'hate', 'dislike',
    'disappointed', 'disappointing', 'fail', 'failed', 'failure', 'useless',
    'waste', 'sucks', 'suck', 'stupid', 'dumb', 'ridiculous', 'unacceptable',
    'worst', 'lame', 'garbage', 'trash'
}

def analyze_sentiment(text):
    """
    基于词典的英文情感分析
    返回: (score, label, class)
    """
    if not text:
        return 0, '中性', 'neutral'
    
    # 预处理：转小写、分词（按空格和标点分割）
    words = re.findall(r'\b[a-z]+\b', text.lower())
    
    pos_count = sum(1 for w in words if w in POSITIVE_WORDS)
    neg_count = sum(1 for w in words if w in NEGATIVE_WORDS)
    
    total = pos_count + neg_count
    if total == 0:
        return 0, '中性', 'neutral'
    
    # 计算情感分数：-1 到 1 之间
    score = (pos_count - neg_count) / total
    
    if score > 0.2:
        return round(score, 2), '正面 😊', 'positive'
    elif score < -0.2:
        return round(score, 2), '负面 😞', 'negative'
    else:
        return round(score, 2), '中性 😐', 'neutral'

# ========== 启动服务 ==========
if __name__ == '__main__':
    print("=" * 50)
    print("🚀 Threads 舆情监控 Demo 已启动")
    print(f"📍 访问地址: http://localhost:5001")
    print("=" * 50)
    env_problems = check_env()
    if env_problems:
        print("\n⚠️  注意：.env 尚未配置完整，授权功能暂不可用：")
        for p in env_problems:
            print(f"   - {p}")
        print("   请编辑 .env 填入真实凭证后重启。\n")
    app.run(debug=True, host='0.0.0.0', port=5001)
