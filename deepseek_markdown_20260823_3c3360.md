# Threads 舆情监控 Demo 实施指令

> **目标**：基于 Meta Threads API，构建一个具备 OAuth 授权、关键词搜索和英文情感分析功能的舆情监控 Web 应用（Python + Flask）。

---

## 一、前置准备（在 Meta 开发者后台完成）

在执行代码之前，请先完成以下 Meta 应用配置。这些步骤无法通过代码自动化，必须手动操作。

1. 登录 [Meta for Developers](https://developers.facebook.com/apps/)。
2. 创建新应用，**Use Case（用例）** 必须选择 **"Access the Threads API"**。
3. 进入应用后台 -> **Use Cases** -> **Access the Threads API** -> **Customize**。
4. 在此页面中，找到并记录：
   - **Threads App ID**（以 `THREADS_` 开头的 ID，与主页面通用 ID 不同）
   - **Threads App Secret**（同样以 `THREADS_` 开头）
5. 在同一个页面的 **"Redirect Callback URLs"** 中，添加：
http://localhost:5000/callback
（这是本地开发调试的回调地址）
6. 进入 **App Roles** -> **Roles** -> 点击 **Add People**，选择 **"Threads Tester"**，输入你自己的 Threads 用户名。
7. **登录你的 Threads 账号**，在 **设置 -> 网站权限 -> 邀请** 中，接受测试邀请。**这一步必须做**，否则授权会失败。

---

## 二、项目初始化（创建文件夹与环境）

请在 VSCode 终端中依次执行以下命令：

```bash
# 1. 创建项目文件夹
mkdir threads-舆情监控
cd threads-舆情监控

# 2. 创建 Python 虚拟环境
python -m venv venv

# 3. 激活虚拟环境
# Windows:
venv\Scripts\activate
# Mac / Linux:
source venv/bin/activate

# 4. 安装依赖库
pip install flask requests python-dotenv

三、创建环境变量文件（.env）

在项目根目录下创建 .env 文件，并填入你自己在第一步拿到的真实凭证（注意替换掉下面的占位符）：

env
THREADS_APP_ID=你的Threads_App_ID
THREADS_APP_SECRET=你的Threads_App_Secret
THREADS_REDIRECT_URI=http://localhost:5000/callback
四、创建主程序文件（app.py）

在项目根目录创建 app.py，将下方完整代码原样复制进去。这是包含前端界面和后端逻辑的全部代码，单文件即可运行。

python
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
        f"https://threads.net/oauth/authorize?"
        f"client_id={APP_ID}&"
        f"redirect_uri={REDIRECT_URI}&"
        f"scope=threads_basic,threads_keyword_search,threads_read_replies&"
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
    print(f"📍 访问地址: http://localhost:5000")
    print("=" * 50)
    app.run(debug=True, host='0.0.0.0', port=5000)
    
五、运行与验收

1. 启动程序

在 VSCode 终端（确保虚拟环境已激活）中执行：

bash
python app.py
如果看到以下输出，说明启动成功：

text
==================================================
🚀 Threads 舆情监控 Demo 已启动
📍 访问地址: http://localhost:5000
==================================================
2. 验收流程（在浏览器中操作）

打开浏览器，访问 http://localhost:5000。
页面顶部状态应显示 "❌ 未授权"。
点击 "🔑 授权 Threads 账号" 按钮，系统将跳转到 Meta 官方授权页面。
在 Meta 页面登录你的 Threads 测试账号，并同意所有权限（threads_basic、threads_keyword_search、threads_read_replies）。
授权成功后，页面将自动跳转回首页，状态变为 "✅ 已授权"。
在输入框中输入英文关键词（例如 Chery），点击 "🔎 搜索"。
系统将展示包含该关键词的帖子列表，每条帖子附带情感分析标签（正面/负面/中性）和情感分数。
3. 验收标准

□ 授权按钮能成功跳转 Meta 页面。
□ 授权后 Token 被正确存储（查看项目根目录是否生成 tokens.db 文件）。
□ 关键词搜索能返回帖子列表。
□ 帖子带有情感分析标签（正面/负面/中性）。
□ 页面无明显报错。
六、已知限制与下一步优化方向

当前 Demo 的限制

项目	说明
API 配额	threads_keyword_search 每 7 天滚动周期仅 500 次查询，仅适合演示。
Token 刷新	长期 Token 有效期 60 天，本 Demo 未实现自动刷新（重启后需手动重新授权）。
语言支持	目前仅支持英文情感分析，印尼语需替换情感词典或接入 NLP API。
数据持久化	搜索结果未存入数据库，仅实时展示。
后续可扩展的方向

印尼语支持：将 POSITIVE_WORDS 和 NEGATIVE_WORDS 替换为印尼语情感词典（如 bagus, jelek）。
定时任务：集成 APScheduler，每 30 分钟自动拉取指定关键词的最新帖子。
告警推送：当检测到负面情绪分数低于阈值时，自动发送 Telegram / 邮件通知。
自动刷新 Token：在每次请求前检查 Token 有效期，剩余 < 7 天时自动调用刷新接口并更新数据库。
七、遇到问题时排查

授权后跳转 localhost 被拒绝：

检查 Meta 后台的 Redirect URI 是否精确为 http://localhost:5000/callback（注意端口和路径）。
搜索返回空结果：

确认关键词是英文，且确实有人在 Threads 上讨论该词。
检查 Threads 账号是否已接受测试邀请。
搜索报错 403 / 权限不足：

确认授权时勾选了 threads_keyword_search 权限。
确认 Threads 账号已接受测试邀请（这一步极易被忽略）。
模块导入错误：

确认已激活虚拟环境，并安装了 flask、requests、python-dotenv。
现在，请开始执行以上所有步骤，完成后告诉我验收结果。

text

---

你可以直接把上面的内容保存为 `Hermes_实施指令.md`，然后在 VSCode 中打开，让 Hermes 按照这份文档逐项执行即可。祝你顺利！