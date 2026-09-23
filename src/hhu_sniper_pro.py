"""
HHU 抢课工具 v1.03 (正式版) - by MerrillXu
适合所有 HHU 同学使用，启动问答式配置，无需改代码
HHU 真实接口：/jsxsd/xsxkkc/yl_xsxkBxxk + bxxkOper/xxxkOper/ggxxkxkOper
[BK] 强智教务 / CAS 单点登录 / 同时抢多个课程
[!]  仅供学习交流，使用风险自负。 
"""

import sys
import os
import io

# Windows cmd 默认 GBK 编码，把 stdout 强制改成 UTF-8
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

import re
import json
import time
import base64
import secrets
import socket
import threading
import requests

# === 网络兼容性修复 ==========================================
# Windows requests 默认优先尝试 IPv6，校园网 IPv6 不稳 → 强制 IPv4
def _ipv4_only():
    return socket.AF_INET

import urllib3.util.connection as _urllib3_cn
_urllib3_cn.allowed_gai_family = _ipv4_only

def beep(n=3):
    return 


AES_CHARS = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"

def rand_str(n):
    return ''.join(secrets.choice(AES_CHARS) for _ in range(n))

def _aes_key(s, n=16):
    """把任意字符串规范成 AES 用的 n 字节 key/iv"""
    b = s.encode('utf-8', errors='ignore')[:n]
    return b.ljust(n, b'\0')

def encrypt_password(password, salt, iv_str):
    """HHU CAS 加密：64 位随机前缀 + 密码，IV 从 happyVoyage cookie 同步"""
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    key = _aes_key(salt, 16)
    iv = _aes_key(iv_str, 16)
    plain = (rand_str(64) + password).encode('utf-8')
    cipher = AES.new(key, AES.MODE_CBC, iv=iv)
    return base64.b64encode(cipher.encrypt(pad(plain, 16))).decode()


# === 抢课相关 URL =============================================
LOGIN_PAGE = 'https://authserver.hhu.edu.cn/authserver/login?service=https%3A%2F%2Fjwxt.hhu.edu.cn%2Fjsxsd%2Fsso.jsp'
SSO_JSP = 'https://jwxt.hhu.edu.cn/jsxsd/sso.jsp'
JWXT_BASE = 'https://jwxt.hhu.edu'

# 必修 + 选修 + 公选 各有独立接口
URL_LIST_BX = '/jsxsd/xsxkkc/yl_xsxkBxxk'         # 必修
URL_LIST_XX = '/jsxsd/xsxkkc/yl_xsxkXxxk'         # 选修
URL_LIST_GGXK = '/jsxsd/xsxkkc/yl_xsxkGgxxkxk'    # 公选

# 抢课提交接口（HHU 强智教务真实接口 —— 暴力枚举发现的）
URL_SUBMIT_BX = '/jsxsd/xsxkkc/bxxkOper'        # 必修
URL_SUBMIT_XX = '/jsxsd/xsxkkc/xxxkOper'        # 选修
URL_SUBMIT_GGXK = '/jsxsd/xsxkkc/ggxxkxkOper'   # 公选


ENTRY = '' 


def _make_dt_payload(page_num, page_size, kind_opened_flag):
    """DataTables 协议 payload。kind_opened_flag: 'bxxk'/'xxxk'/'ggxxkxk'"""
    p = {
        'sEcho': str(page_num),
        'iColumns': '11',
        'sColumns': '',
        'iDisplayStart': str((page_num - 1) * page_size),
        'iDisplayLength': str(page_size),
        'mDataProp_0': 'kcmc',
        'mDataProp_1': 'fzmc',
        'mDataProp_2': 'xf',
        'mDataProp_3': 'skjs',
        'mDataProp_4': 'skxs',
        'mDataProp_5': 'jxrs',
        'mDataProp_6': 'syrs',
        'mDataProp_7': 'bxxkIsOpened',
        'mDataProp_8': 'xxxkIsOpened',
        'mDataProp_9': 'ggxxkxkIsOpened',
        'mDataProp_10': 'kcapList',
    }
    if kind_opened_flag == 'bxxk':
        p['bxxkIsOpened'] = '1'
    elif kind_opened_flag == 'xxxk':
        p['xxxkIsOpened'] = '1'
    elif kind_opened_flag == 'ggxxkxk':
        p['ggxxkxkIsOpened'] = '1'
    return p


def _get_list_url(kind):
    return {'bxxk': URL_LIST_BX, 'xxxk': URL_LIST_XX, 'ggxxkxk': URL_LIST_GGXK}.get(kind)


def _get_submit_url(kind):
    return {'bxxk': URL_SUBMIT_BX, 'xxxk': URL_SUBMIT_XX, 'ggxxkxk': URL_SUBMIT_GGXK}.get(kind)



def _load_config():
    p = os.path.join(os.path.expanduser('~'), 'hhu_config.json')
    if os.path.exists(p):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f), p
        except Exception:
            return {}, p
    return {}, p


def _save_config(cfg, p):
    try:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f'  [!] 保存配置失败: {e}', flush=True)
        return False


def _looks_like_zbid(s):
    if not s:
        return False
    s = s.replace(' ', '').replace('-', '')
    if len(s) != 32:
        return False
    try:
        int(s, 16)
        return True
    except Exception:
        return False


_XKLC_LIST_ZBIDS = []


def _try_auto_detect_zbid(session):
    """登录后自动探测 zbid. 多种深挖方法, 找到返回 zbid, 找不到返回 None."""
    global _XKLC_LIST_ZBIDS
    if not session:
        return None

    # a) GET xsxk_index 看 302 Location 是否带 zbid
    try:
        r = session.get('https://jwxt.hhu.edu.cn/jsxsd/xsxk/xsxk_index',
                        timeout=10, allow_redirects=False)
        if r.status_code in (301, 302):
            loc = r.headers.get('Location', '') + r.headers.get('location', '')
            m = re.search(r'jx0502zbid=([0-9A-Fa-f]{32})', loc)
            if m:
                return m.group(1).upper()
    except Exception:
        pass

    # b) 试 11 个候选 API
    api_candidates = [
        '/jsxsd/framework/xsMain_new.htmlx',
        '/jsxsd/framework/main.htmlx',
        '/jsxsd/framework/xsrkxz.htmlx',
        '/jsxsd/jwglxt/index/cxCurrentXq',
        '/jsxsd/jwglxt/jkgl/index',
        '/jsxsd/jwglxt/xkgl/cxXkglZbid',
        '/jsxsd/jwglxt/xkgl/cxXkZbid',
        '/jsxsd/jwglxt/xkgl/getCurrentZbid',
        '/jsxsd/xsxkkc/getXkkzZbid',
        '/jsxsd/xsxkkc/getXqkjZbid',
        '/jsxsd/xsxk/getCurrentXqZbid',
    ]
    for u in api_candidates:
        try:
            r = session.get('https://jwxt.hhu.edu.cn' + u,
                            timeout=6, allow_redirects=False)
            text = r.text if r.status_code == 200 else ''
            if text and 'application/json' in r.headers.get('content-type', ''):
                m = re.search(r'"([0-9A-Fa-f]{32})"', text)
                if m:
                    return m.group(1).upper()
            m = re.search(r'jx0502zbid=([0-9A-Fa-f]{32})', text)
            if m:
                return m.group(1).upper()
        except Exception:
            continue

    try:
        r = session.get('https://jwxt.hhu.edu.cn/jsxsd/framework/main.htmlx',
                        timeout=10, allow_redirects=False)
        if r.status_code == 200:
            js_urls = set(re.findall(r'src="(/[^"]+\.js)"', r.text))
            for ju in js_urls:
                try:
                    rj = session.get('https://jwxt.hhu.edu.cn' + ju, timeout=8)
                    m = re.search(r'\b([0-9A-F]{32})\b', rj.text)
                    if m:
                        return m.group(1).upper()
                except Exception:
                    continue
    except Exception:
        pass

    try:
        r = session.get('https://jwxt.hhu.edu.cn/jsxsd/framework/xsMain_new.htmlx',
                        timeout=10, allow_redirects=False)
        if r.status_code == 200:
            js_urls = set(re.findall(r'src="(/[^"]+\.js)"', r.text))
            for ju in js_urls:
                try:
                    rj = session.get('https://jwxt.hhu.edu.cn' + ju, timeout=8)
                    m = re.search(r'\b([0-9A-F]{32})\b', rj.text)
                    if m:
                        return m.group(1).upper()
                except Exception:
                    continue
    except Exception:
        pass

 
    flow_urls = [
        'https://jwxt.hhu.edu.cn/jsxsd/xsxk/xklc_list?Ves632DSdyV=NEW_XSD_PYGL',
        'https://jwxt.hhu.edu.cn/jsxsd/xsxk/xklc_list',
        'https://jwxt.hhu.edu.cn/jsxsd/xsxk/xklc_view',
        'https://jwxt.hhu.edu.cn/jsxsd/xsxk/xsxk_index',
    ]
    seen = []
    for fu in flow_urls:
        try:
            r = session.get(fu, timeout=10, allow_redirects=True)
            if r.status_code != 200:
                continue
            body = r.text or ''
            # 1) 页面直接含 jx0502zbid=xxx
            for m in re.finditer(r'jx0502zbid=([0-9A-Fa-f]{32})', body):
                z = m.group(1).upper()
                if z not in seen:
                    seen.append(z)
            # 2) 302 Location 里含 zbid
            for m in re.finditer(r'jx0502zbid=([0-9A-Fa-f]{32})', r.headers.get('Location', '')):
                z = m.group(1).upper()
                if z not in seen:
                    seen.append(z)
            # 3) 页面引用的 JS 也扫一遍 (部分轮次 JS 动态渲染)
            for ju in set(re.findall(r'src="(/[^"]+\.js[^"]*)"', body)):
                try:
                    rj = session.get('https://jwxt.hhu.edu.cn' + ju, timeout=8)
                    for m in re.finditer(r'jx0502zbid=([0-9A-Fa-f]{32})', rj.text):
                        z = m.group(1).upper()
                        if z not in seen:
                            seen.append(z)
                except Exception:
                    continue
        except Exception:
            continue
    if seen:
        _XKLC_LIST_ZBIDS = seen
        if len(seen) == 1:
            return seen[0]
        return '__MULTI__'

    #    <a href="xsxk_index?jx0502zbid=xxx" ...>进入选课</a>
    try:
        r = session.get('https://jwxt.hhu.edu.cn/jsxsd/xsxk/xklc_list',
                        timeout=10, allow_redirects=True)
        if r.status_code == 200:
            for m in re.finditer(
                r'<a[^>]+href=["\']([^"\']*jx0502zbid=([0-9A-Fa-f]{32})[^"\']*)["\']',
                r.text,
            ):
                z = m.group(2).upper()
                if z not in seen:
                    seen.append(z)
    except Exception:
        pass
    if seen:
        _XKLC_LIST_ZBIDS = seen
        if len(seen) == 1:
            return seen[0]
        return '__MULTI__'

    try:
        r = session.get(
            'https://jwxt.hhu.edu.cn/jsxsd/xsxk/xsxk_index?Ves632DSdyV=NEW_XSD_PYGL',
            timeout=10, allow_redirects=False,
        )
        if r.status_code in (301, 302):
            loc = r.headers.get('Location', '') + r.headers.get('location', '')
            m = re.search(r'jx0502zbid=([0-9A-Fa-f]{32})', loc)
            if m:
                return m.group(1).upper()
    except Exception:
        pass

    return None


def collect_zbid(session):

    print()
    print('=' * 60)
    print('  [Z] 第 1.5 步: 选课轮次 zbid (登录后)')
    print('=' * 60)
    print('  说明:')
    print('  · zbid = 选课地址 ?jx0502zbid= 后面 32 位 hex')
    print('  · 每轮选课换一个; 来源 = 教务系统「进入选课」地址栏')
    print('  · 本脚本 **优先自动获取** (7 种方法深挖)')
    print('  · 自动全部失败才让主人手输; 没有默认值!')
    print('=' * 60)

    cfg, path = _load_config()

    # ---- 1) 登录后自动探测 ----
    print('\n  [1/2] 自动探测 zbid (7 种方法 + 跟「进入选课」链接)...', flush=True)
    detected = _try_auto_detect_zbid(session)
    if detected == '__MULTI__':
        zbids = _XKLC_LIST_ZBIDS[:]
        print(f'\n  ★ 自动探测到 {len(zbids)} 个选课轮次:', flush=True)
        for i, z in enumerate(zbids, 1):
            tag = ' [本地缓存]' if z == cfg.get('zbid') else ''
            print(f'      [{i}] {z}{tag}', flush=True)
        print(f'      [0] 我要自己输入 (跳过自动)', flush=True)
        while True:
            pick = input(f'  选轮次 (1-{len(zbids)} 或 0=手动): ').strip()
            if pick == '0':
                break
            if pick.isdigit() and 1 <= int(pick) <= len(zbids):
                chosen = zbids[int(pick) - 1]
                cfg['zbid'] = chosen
                _save_config(cfg, path)
                print(f'  -> 已选: {chosen}', flush=True)
                return chosen
            print(f'  [!] 输入不对, 重新选')
        # pick = 0 → 落到下面的强制手动
    elif detected:
        last = cfg.get('zbid')
        if last and _looks_like_zbid(last) and detected != last:
            print(f'\n  ★ 自动探测到 zbid = {detected}', flush=True)
            print(f'     本地缓存的是   = {last}', flush=True)
            while True:
                ans = input('  用哪个? [1=探测到的 / 2=本地的 / 0=自己手输]: ').strip()
                if ans == '1':
                    cfg['zbid'] = detected
                    _save_config(cfg, path)
                    print(f'  -> 使用探测到的: {detected}', flush=True)
                    return detected
                if ans == '2':
                    print(f'  -> 使用本地的: {last}', flush=True)
                    return last
                if ans == '0':
                    break
                print(f'  [!] 请输入 1 / 2 / 0')
            # ans = 0 → 落到强制手动
        else:
            print(f'  ★ 自动探测成功! zbid = {detected}', flush=True)
            cfg['zbid'] = detected
            _save_config(cfg, path)
            return detected
    else:
        print(f'  [X] 7 种方法都没找到 zbid', flush=True)

    # ---- 2) 自动失败 → 强制手动 (不允许 Enter 默认沿用) ----
    last = cfg.get('zbid')
    print()
    print('  [2/2] 必须主人手动输入 zbid', flush=True)
    print('        来源: 浏览器打开 https://jwxt.hhu.edu.cn', flush=True)
    print('              → 学生选课中心 → 进入选课', flush=True)
    print('              → 复制地址栏 ?jx0502zbid= 后面的 32 位 hex', flush=True)
    if last and _looks_like_zbid(last):
        print(f'  (想沿用本地缓存, 输入 s = "s")',
              flush=True)
    print()
    while True:
        v = input('  zbid (32 位 hex, 或输入 s 沿用本地): ').strip()
        if v.lower() == 's' and last and _looks_like_zbid(last):
            v = last
            print(f'  -> 沿用本地: {v}', flush=True)
        elif _looks_like_zbid(v):
            v = v.upper()
        else:
            print('  [!] 不像 zbid (需要 32 位 0-9A-F), 重新输')
            continue
        cfg['zbid'] = v
        _save_config(cfg, path)
        print(f'  -> 已保存: {v}')
        return v


def do_login(username, password):
    """登录 CAS 拿 bzb_jsxsd + happyVoyage。返回 (ok, session_or_msg)"""
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    })

    print('  ... 正在访问登录页 (authserver.hhu.edu.cn)', flush=True)
    try:
        r = s.get(LOGIN_PAGE, timeout=15)
    except requests.exceptions.ConnectTimeout:
        return False, '[X] 连接登录页超时（>15s），校园网断开了？'
    except requests.exceptions.ReadTimeout:
        return False, '[X] 登录页响应超时（>15s），被限流了'
    except requests.exceptions.ConnectionError as e:
        return False, f'[X] 网络错误: {str(e)[:120]}'
    print(f'  ... 登录页 {r.status_code} ({len(r.text)} bytes)', flush=True)
    if r.status_code != 200:
        return False, f'登录页加载失败: {r.status_code}'

    # 提取表单字段
    salt_m = re.search(r'id="pwdEncryptSalt"\s+value="([^"]+)"', r.text)
    exe_m = re.search(r'name="execution"\s+value="([^"]+)"', r.text)
    if not salt_m or not exe_m:
        return False, '提取 salt/execution 失败，登录页面结构可能变了'

    salt = salt_m.group(1)
    exe = exe_m.group(1)

    # IV 必须跟 happyVoyage cookie 同步（HHU CAS 关键！）
    cookies_now = s.cookies.get_dict()
    happyvoyage = cookies_now.get('happyVoyage', '') or cookies_now.get('HAPPYVOYAGE', '')
    print(f'  ... 抓到的 cookie: {list(cookies_now.keys())}', flush=True)
    print(f'  ... happyVoyage = {happyvoyage[:20] if happyvoyage else "(无！)"}', flush=True)
    if not happyvoyage:
        happyvoyage = salt
        print(f'  ... happyVoyage 缺失，使用 salt 兜底: {happyvoyage[:20]}', flush=True)

    enc_pwd = encrypt_password(password, salt, happyvoyage)

    data = {
        'username': username,
        'password': enc_pwd,
        'execution': exe,
        '_eventId': 'submit',
        'cllt': 'userNameLogin',
        'dllt': 'generalLogin',
        'rmShown': '1',
    }
    s.headers.update({
        'Referer': LOGIN_PAGE,
        'Origin': 'https://authserver.hhu.edu.cn',
        'Content-Type': 'application/x-www-form-urlencoded',
    })

    print('  ... 正在提交登录表单 (CAS 会重定向到教务)', flush=True)
    try:
        r2 = s.post(LOGIN_PAGE, data=data, allow_redirects=True, timeout=20)
    except requests.exceptions.ConnectTimeout:
        return False, '[X] 提交登录超时，重定向步骤太久'
    except requests.exceptions.ReadTimeout:
        return False, '[X] 登录响应超时（>20s）'
    except requests.exceptions.ConnectionError as e:
        return False, f'[X] 登录网络错误: {str(e)[:120]}'
    print(f'  ... 登录响应 {r2.status_code} ({len(r2.text)} bytes)，跳转: {r2.url[:80]}', flush=True)
    cookies = s.cookies.get_dict()
    print(f'  ... 拿到 cookie: {list(cookies.keys())}', flush=True)

    if 'bzb_jsxsd' in cookies:
        return True, s
    if '错误' in r2.text or '用户名或密码' in r2.text:
        return False, '[X] 用户名或密码错误'
    if '请输入验证码' in r2.text:
        return False, '[X] 触发验证码，请稍后再试或手动登录一次'
    title_m = re.search(r'<title>(.*?)</title>', r2.text)
    title = title_m.group(1) if title_m else '?'
    return False, f'登录失败（页面标题: {title}）'


# === 拉课程池 =================================================
def check_open(session):
    """检测选课是否开放。返回 (status, msg)
       status: 'open' | 'closed' | 'login_lost'
    """
    try:
        r = session.get(ENTRY, timeout=15)
        text = r.text
        if 'authserver' in r.url or 'passportservice' in r.url or len(text) < 200:
            return 'login_lost', 'session 失效'
        if '未开放' in text or '未开始' in text or '不在选课时间' in text:
            return 'closed', '选课未开放'
        if 'xkkz_id' in text or '选课' in text and '未开放' not in text:
            return 'open', '已开放'
        if len(text) < 1000 and ('DOCTYPE' in text or '<html>' in text):
            return 'closed', '教务网关拒绝（选课系统未启动？）'
        return 'open', '可继续尝试'
    except Exception as e:
        return 'closed', f'网络错误: {str(e)[:60]}'


def fetch_pool(session):
    """一次拉全量课程（HHU DataTables 协议 + 3 个分桶）。

    """
    print('  ... 访问选课入口激活 session', flush=True)
    try:
        r0 = session.get(ENTRY, timeout=15)
        print(f'  ... 选课入口 {r0.status_code} ({len(r0.text)} bytes)', flush=True)
    except Exception as e:
        print(f'     [!] 选课入口失败: {str(e)[:120]}', flush=True)

    for k, p in [('bxxk', '/jsxsd/xsxkkc/comeInBxxk'),
                 ('xxxk', '/jsxsd/xsxkkc/comeInXxxk'),
                 ('ggxxkxk', '/jsxsd/xsxkkc/comeInGgxxkxk')]:
        try:
            r = session.get(JWXT_BASE + p, timeout=10)
            print(f'  ... 预热 {k}: {r.status_code} ({len(r.text)} bytes)', flush=True)
        except Exception as e:
            print(f'     [!] 预热 {k} 失败: {str(e)[:120]}', flush=True)

    all_courses = []
    kind_summary = {}
    for kind in ('bxxk', 'xxxk', 'ggxxkxk'):
        list_url = _get_list_url(kind)
        page = 1
        rows_all = []
        while page <= 10:
            p = _make_dt_payload(page, 50, kind)
            try:
                r = session.post(
                    JWXT_BASE + list_url,
                    data=p,
                    headers={
                        'X-Requested-With': 'XMLHttpRequest',
                        'Referer': ENTRY,
                        'Content-Type': 'application/x-www-form-urlencoded',
                    },
                    timeout=15,
                )
            except Exception as e:
                print(f'     [!] {kind} 第 {page} 页请求失败: {str(e)[:120]}', flush=True)
                time.sleep(1)
                continue

            if 'bzb_jsxsd' not in session.cookies.get_dict():
                print(f'     [!] session 掉了，停止拉取 {kind}', flush=True)
                break

            try:
                d = r.json()
            except Exception:
                if len(r.text) < 1500 and ('DOCTYPE' in r.text or '<html>' in r.text):
                    print(f'     ... {kind} 返 HTML 错误页（多半未开放）', flush=True)
                    break
                print(f'     [!] {kind} 第 {page} 页非 JSON ({r.status_code}, {len(r.text)} bytes)', flush=True)
                break

            if isinstance(d, dict):
                total = d.get('iTotalRecords', 0)
                rows = d.get('aaData', [])
            elif isinstance(d, list):
                total = len(d)
                rows = d
            else:
                rows, total = [], 0

            if not rows:
                if page == 1:
                    print(f'     ... {kind} 无课程数据', flush=True)
                break

            for row in rows:
                row['_kind'] = kind
            rows_all.extend(rows)

            if len(rows) < 50 or (total and len(rows_all) >= total):
                print(f'     ... {kind} 拉完: {len(rows_all)} 门（iTotalRecords={total}）', flush=True)
                break
            page += 1
            time.sleep(0.2)

        kind_summary[kind] = len(rows_all)
        all_courses.extend(rows_all)

    print(f'  ... 汇总: {kind_summary}', flush=True)
    return all_courses


def get_teacher(course):
    """从课程对象里提取教师（兼容中英文字段）"""
    for key in ('skjs', '上课教师', 'teacherName', 'jsxm'):
        v = course.get(key)
        if v:
            return v
    for key in ('kkapList', '教师列表', 'teachers'):
        lst = course.get(key)
        if lst and isinstance(lst, list) and lst:
            return lst[0].get('jgxm') or lst[0].get('name') or ''
    return '-'


def get_jxid(course):
    """提取抢课必要字段 jx0404id（教学班 id）"""
    for key in ('jx0404id', 'kxh', '课序号', 'id', 'jxbh', 'jxbid'):
        v = course.get(key)
        if v:
            return str(v)
    return ''


def get_attr(course):
    """课程属性（必修/限选/公选/通识）"""
    for key in ('kcsx', '课程属性', 'kclb', '课程类别', 'courseAttr'):
        v = course.get(key)
        if v:
            return str(v)
    return ''


def get_remain(course):
    """剩余名额"""
    for key in ('syrs', '剩余', 'remain', 'available'):
        v = course.get(key)
        if v is not None:
            return v
    return '0'


# === 匹配规则 =================================================
def match_course(course, rule):
    """根据规则判断课程是否为目标。返回 bool"""
    name = (course.get('kcmc', '') or course.get('课程名', '') or '').strip()
    group_name = (course.get('fzmc', '') or course.get('分组名', '') or '').strip()
    teacher = get_teacher(course)
    attr = get_attr(course)

    # 类型筛选
    kind = rule.get('类型', '全部')
    if kind == '公共课':
        if '公选' not in attr and '通识' not in attr and '任选' not in attr:
            return False
    elif kind == '专业课':
        if '必修' not in attr and '限选' not in attr and '专业' not in attr:
            return False

    # 关键词（必须出现其一）
    inc = rule.get('关键词', []) or []
    if inc and not any(kw in name or kw in group_name for kw in inc):
        return False

    # 教师名（可选，留空=任何）
    teacher_filter = (rule.get('教师', '') or '').strip()
    if teacher_filter and teacher_filter not in teacher:
        return False

    # 排除词
    exc = rule.get('排除', []) or []
    if exc and any(kw in name or kw in group_name or kw in teacher for kw in exc):
        return False

    # 剩余必须 > 0
    try:
        if int(str(get_remain(course)).strip()) <= 0:
            return False
    except Exception:
        pass

    return True


# === 抢课提交 =================================================
def try_take(session, course):
    """尝试抢一次。返回 (success, msg, give_up)"""
    jxid = get_jxid(course)
    if not jxid:
        return False, 'jx0404id 缺失', False

    kind = course.get('_kind', 'ggxxkxk')
    submit_url = _get_submit_url(kind)
    if not submit_url:
        return False, f'未知分桶: {kind}', True

    payload = {'kch': course.get('kch', ''), 'jx0404id': jxid}

    try:
        r = session.post(
            JWXT_BASE + submit_url,
            data=payload,
            headers={
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': ENTRY,
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            timeout=10,
        )
    except Exception as e:
        return False, f'网络错误: {e}', False

    text = r.text.strip()
    if not text:
        return False, '空响应（可能掉线）', False
    if len(text) < 1500 and 'DOCTYPE' in text:
        # 服务端返 HTML 错误页
        return False, '服务端返错误页（选课未开放或接口错）', False

    try:
        d = r.json()
        if isinstance(d, dict):
            msg = d.get('message', d.get('msg', '')) or ''
            success = d.get('success')
            if success is True:
                return True, '选课成功: ' + msg, True
            # 失败：用 message 判断可重试/放弃
            if '人数已满' in msg or '课程人数已满' in msg or '已选满' in msg or 'JF_GGMXKC_FULL' in msg:
                return False, '已满: ' + msg, False
            if '未开放' in msg or '未开通' in msg or '选课未开放' in msg or 'JF_KCSJWK' in msg:
                return False, '未开放: ' + msg, False
            if '时间冲突' in msg or '上课时间' in msg and '冲突' in msg:
                return False, '时间冲突: ' + msg, True
            if '已选' in msg or '已在选课列表' in msg:
                return True, '已选: ' + msg, True
            if '跨专业' in msg or '非推荐' in msg or '跨校' in msg:
                return False, '不可选: ' + msg, True
            return False, msg[:120] or str(d)[:120], False
        if isinstance(d, list):
            return False, f'意外响应: {str(d)[:120]}', False
    except Exception:
        pass

    # 纯文本兜底（一般不会到这里）
    if '选课成功' in text or '抢课成功' in text or '添加成功' in text:
        return True, text, True
    if '已在选课列表' in text or '已选上' in text or '课程已选' in text or '已选择该课程' in text:
        return True, '已选: ' + text, True
    if '时间冲突' in text or '上课时间冲突' in text:
        return False, '时间冲突: ' + text, True
    if '人数已满' in text or '已选满' in text or '课程人数已满' in text:
        return False, '已满: ' + text, False
    return False, text[:80], False


# === 后台抢课 worker ==========================================
class SnipeWorker(threading.Thread):
    def __init__(self, session, course, rule_name, interval, log_every=10):
        super().__init__(daemon=True)
        self.session = session
        self.course = course
        self.rule_name = rule_name
        self.interval = interval
        self.log_every = log_every
        self.done = threading.Event()
        self.success = False
        self.msg = ''
        self.attempts = 0

    def run(self):
        name = self.course.get('kcmc', '') or self.course.get('课程名', '?')
        teacher = get_teacher(self.course)
        attr = get_attr(self.course)
        remain = get_remain(self.course)
        print(f'\n  >> [抢课中] {self.rule_name}', flush=True)
        print(f'     课程：{name} | 教师：{teacher or "-"} | 属性：{attr or "-"} | 剩余：{remain}', flush=True)

        n = 0
        while True:
            n += 1
            try:
                ok, msg, stop = try_take(self.session, self.course)
            except Exception as e:
                ok, msg, stop = False, f'异常: {e}', False
            self.attempts = n
            ts = time.strftime('%H:%M:%S')
            if ok:
                print(f'\n  [OK][OK][OK] [{ts}] 抢课成功！{name} ({self.rule_name})', flush=True)
                print(f'     {msg}\n', flush=True)
                self.success = True
                self.msg = msg
                beep(5)
                self.done.set()
                return
            if stop:
                print(f'  [X] [{ts}] 第 {n:4d} 次 - {msg[:60]}（放弃该班次）', flush=True)
                self.msg = msg
                self.done.set()
                return
            if n == 1 or n % self.log_every == 0:
                print(f'  [L] [{ts}] 第 {n:4d} 次 - {msg[:60]}', flush=True)
            time.sleep(self.interval)


# === 启动交互 =================================================
def banner():
    print()
    print('HHU 抢课工具 v1.03 (正式版)  build_by_MerrillXu')
    print('任何 HHU 学子可以交流学习')
    print('同时抢多个课程（最高 16 个并发 worker）')
    print('[!]  学术使用，违规选课后果自负。')
    print('[!]  学术使用，违规选课后果自负。')
    print('[!]  学术使用，违规选课后果自负。')
    print('关注塔菲喵 关注塔菲谢谢喵 塔不灭塔不灭 雏草姬不灭')
    print('啊啊啊啊好想玩鸣潮')
    print()


def ask(prompt, default='', allow_empty=False):
    if default:
        prompt = f'{prompt} [{default}]: '
    else:
        prompt = f'{prompt}: '
    while True:
        v = input(prompt).strip()
        if v == '' and default:
            return default
        if v == '' and not allow_empty:
            print('  （不能为空，重新输）')
            continue
        return v


def ask_choice(prompt, options):
    """单选。options = [(key, label), ...]"""
    print(f'\n{prompt}')
    for i, (k, label) in enumerate(options, 1):
        print(f'  [{i}] {label}')
    while True:
        v = ask('  请选择编号')
        if v.isdigit() and 1 <= int(v) <= len(options):
            return options[int(v) - 1][0]
        print('  （输入错误，重新选）')


def collect_rules():
    """收集多个抢课规则"""
    print()
    print('=' * 60)
    print('  [M] 第 1 步：添加想抢的课程（可多次添加）')
    print('=' * 60)

    kind_choices = [
        ('公共课',  '公共课 / 公选课 / 通识课'),
        ('专业课',  '专业课 / 必修课 / 限选课'),
        ('全部',    '不管类型，匹配就抢'),
    ]

    rules = []
    while True:
        print(f'\n  ----- 第 {len(rules) + 1} 条规则 -----')
        kind = ask_choice('  第 1 问：选课类型？', kind_choices)

        keyword = ask('  第 2 问：课程名称关键词（如 "大学英语|高数" 用 | 分隔多个）')
        teacher = ask('  第 3 问：教师姓名（留空 = 不限）', allow_empty=True)
        exclude = ask('  第 4 问：排除词（不想抢的教学班，含 | 分隔，留空 = 不限）', allow_empty=True)
        try:
            priority = int(ask('  第 5 问：优先级（数字小=先抢，默认 5）', default='5'))
        except ValueError:
            priority = 5

        rules.append({
            '类型': kind,
            '关键词': [k.strip() for k in keyword.split('|') if k.strip()],
            '教师': teacher,
            '排除': [k.strip() for k in exclude.split('|') if k.strip()],
            '优先级': priority,
        })

        if len(rules) >= 8:
            print('\n  [i] 已达上限 8 条规则')
            break
        cont = ask('\n  要继续添加下一条吗？(y/n)', default='y').lower()
        if cont not in ('y', 'yes', '是', '好'):
            break

    return rules


def collect_creds():
    """收集学号密码"""
    print()
    print('=' * 60)
    print('  [K] 第 4 步：登录')
    print('=' * 60)
    user = ask('  学号')
    pwd = ask('  教务密码（输入不可见，建议直接粘贴）')
    return user, pwd


def collect_snipe_params():
    """收集抢课运行参数"""
    print()
    print('=' * 60)
    print('  [X] 第 2 步：抢课参数（直接回车 = 默认）')
    print('=' * 60)
    print('  解释：')
    print('    轮询间隔 = 多久拉一次课程列表（秒）')
    print('    提交间隔 = 每个 worker 提交一次抢课的间隔（秒）')
    print('    并发数   = 同时抢几门课的 worker 数（1~16）')
    print('  调参建议：')
    print('    普通选手：默认（1.0s / 0.5s / 6 并发）够用')
    print('    热门课/卷王：轮询 0.5s / 提交 0.3s / 12 并发')
    print('    怕风控：  轮询 2.0s / 提交 1.0s / 3 并发')
    print()
    while True:
        pi = ask('  轮询间隔秒数', default='1.0')
        try:
            poll = float(pi)
            if poll < 0.1: raise ValueError
            break
        except ValueError:
            print('  （请输入 >= 0.1 的数字）')
    while True:
        si = ask('  提交间隔秒数', default='0.5')
        try:
            submit = float(si)
            if submit < 0.05: raise ValueError
            break
        except ValueError:
            print('  （请输入 >= 0.05 的数字）')
    while True:
        mw = ask('  最大并发 worker 数', default='6')
        try:
            workers_n = int(mw)
            if 1 <= workers_n <= 16: break
            print('  （请输入 1~16）')
        except ValueError:
            print('  （请输入整数）')

    print(f'\n  -> 轮询 {poll}s / 提交 {submit}s / 并发 {workers_n}')
    return poll, submit, workers_n


def collect_start_time():
    """收集开始时间：立即 / HH:MM[:SS] / 明天HH:MM[:SS] / 秒数"""
    print()
    print('  [T] 第 3 步：什么时候开始抢？')
    print('  说明：')
    print('    直接回车        = 立即开始')
    print('    HH:MM:SS        = 最近的那个时间点（今天已过则自动算明天）')
    print('    明天HH:MM:SS    = 明确等到明天（如 明天12:30:00）')
    print('    数字            = 多少秒后开始（如 60 = 1 分钟后）')
    while True:
        s = input('  开始时间（直接回车=立即）：').strip()
        if not s:
            return 0
        # 「明天 / 后天 / 今天」前缀
        day_offset = 0
        for pre, off in (('明天', 1), ('后天', 2), ('今天', 0)):
            if s.startswith(pre):
                day_offset = off
                s = s[len(pre):].strip()
                break
        if ':' in s:
            try:
                parts = s.split(':')
                h = int(parts[0])
                m = int(parts[1])
                sec = int(parts[2]) if len(parts) > 2 else 0
                from datetime import datetime, timedelta
                now = datetime.now()
                target = (now + timedelta(days=day_offset)).replace(
                    hour=h, minute=m, second=sec, microsecond=0)
                if day_offset == 0 and target < now:
                    target += timedelta(days=1)
                return int((target - now).total_seconds())
            except Exception:
                print('  （格式不对，如 12:30:00 或 明天12:30:00）')
                continue
        try:
            n = int(s)
            if n < 0:
                raise ValueError
            return n
        except ValueError:
            print('  （请输入 HH:MM:SS / 明天HH:MM:SS / 秒数，或回车跳过）')

def summary(rules):
    print()
    print('=' * 60)
    print('  [M] 抢课清单')
    print('=' * 60)
    for i, r in enumerate(rules, 1):
        kws = '|'.join(r['关键词'])
        tch = r['教师'] or '不限'
        exc = '|'.join(r['排除']) or '不限'
        print(f'  {i}. [{r["类型"]}] [{kws}] [{tch}] 排除=[{exc}] 优先级={r["优先级"]}')


# === 主循环 ===================================================
def main():
    banner()

    # 1. 配置
    rules = collect_rules()
    if not rules:
        print('\n  [X] 没有添加任何规则，退出')
        return

    poll_interval, submit_interval, max_workers = collect_snipe_params()
    start_in = collect_start_time()
    user, pwd = collect_creds()
    summary(rules)

    go_at = (time.time() + start_in) if start_in > 0 else 0
    if start_in > 60:
        pre_target = go_at - 60
        print()
        print('=' * 60)
        print(f'  [T] 距开抢还有 {start_in}s, 先等到开抢前 60s 再登录')
        print(f'      开抢时刻: {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(go_at))}')
        print('=' * 60)
        try:
            while True:
                remain = pre_target - time.time()
                if remain <= 0:
                    break
                h = int(remain // 3600)
                m = int((remain % 3600) // 60)
                s = int(remain % 60)
                print(f'\r  距登录 {h:02d}:{m:02d}:{s:02d}（按 Ctrl+C 中断）', end='', flush=True)
                time.sleep(1)
        except KeyboardInterrupt:
            print('\n\n  [B] 用户中断，退出')
            return
        print('\n  [GO] 开始登录（距开抢约 60s）')


    print()
    print('=' * 60)
    print('  [L] 正在登录...')
    print('=' * 60)
    ok, res = do_login(user, pwd)
    if not ok:
        print(f'\n  [X] 登录失败：{res}', flush=True)
        print('  💡 检查账号密码是否正确，或 5 分钟后再试（防 CAS 风控）', flush=True)
        input('  按回车退出...')
        return
    session = res
    cookies = session.cookies.get_dict()
    print(f'  [V] 登录成功！', flush=True)
    print(f'     bzb_jsxsd = {cookies.get("bzb_jsxsd", "")[:20]}...', flush=True)
    print(f'     happyVoyage = {"有" if "happyVoyage" in cookies else "无"}', flush=True)

    zbid = collect_zbid(session)
    global ENTRY
    ENTRY = f'https://jwxt.hhu.edu.cn/jsxsd/xsxk/xsxk_index?jx0502zbid={zbid}'

    # 2. 拉课程池
    print()
    print('=' * 60)
    print('  [BK] 正在拉课程池...')
    print('=' * 60)
    print(f'  ... 选课轮次 zbid = {zbid}', flush=True)

    if start_in > 0:
        from datetime import datetime
        target = go_at if go_at else (datetime.now().timestamp() + start_in)
        print()
        print('=' * 60)
        print(f'  [T] 等待 {start_in}s 后开始抢课（按 Ctrl+C 中断）')
        print(f'      预计开始时间：{datetime.fromtimestamp(target).strftime("%Y-%m-%d %H:%M:%S")}')
        print('=' * 60)
        try:
            while True:
                remain = target - datetime.now().timestamp()
                if remain <= 0:
                    break
                h = int(remain // 3600)
                m = int((remain % 3600) // 60)
                s = int(remain % 60)
                print(f'\r  倒计时 {h:02d}:{m:02d}:{s:02d}（按 Ctrl+C 中断等待）', end='', flush=True)
                time.sleep(1)
        except KeyboardInterrupt:
            print('\n\n  [B] 用户中断，退出')
            return
        print('\n\n  [GO] 到达开始时间，检查选课状态并拉课')

    # 检测选课开放状态，未开放则安静等待（避免空扫日志刷屏）
    open_status = check_open(session)
    print(f'  ... 选课状态: {open_status[0]} - {open_status[1]}', flush=True)
    wait_round = 0
    while open_status[0] == 'closed':
        wait_round += 1
        if wait_round == 1 or wait_round % 10 == 0:
            print(f'  ... 第 {wait_round} 次检测: 选课未开放，{poll_interval:.1f}s 后重试', flush=True)
        time.sleep(poll_interval)
        open_status = check_open(session)
        if open_status[0] == 'open':
            print(f'  ... 第 {wait_round} 次检测: 【选课已开放！】', flush=True)
        elif open_status[0] == 'login_lost':
            print('  [X] session 失效，退出', flush=True)
            return

    courses = fetch_pool(session)
    print(f'\n  [V] 拉到 {len(courses)} 门课', flush=True)
    if courses:
        sample = courses[0]
        print(f'     样例字段: {list(sample.keys())[:10]}', flush=True)

    # 3. 匹配 + 抢
    print()
    print('=' * 60)
    print('  >> 进入抢课循环  [模式: 抢完所有命中后自动结束]')
    print('=' * 60)

    workers = []
    sniped_set = set()  # jx0404id 去重
    winners = []        # 抢成功的 worker（用于退出总结）

    cycle = 0
    first_cycle = True  # 第一轮永远不退出（防止启动前就判空）
    while True:
        cycle += 1
        ts = time.strftime('%H:%M:%S')
        print(f'\n--- [{ts}] 第 {cycle} 轮扫描 ---', flush=True)

        # 检查存活 worker
        alive = [w for w in workers if w.is_alive()]
        done = [w for w in workers if not w.is_alive()]
        workers = alive

        for w in done:
            name = w.course.get('kcmc', '') or w.course.get('课程名', '?')
            if w.success:
                winners.append(w)
                print(f'  [V] 抢到: {name}', flush=True)
            else:
                print(f'  [X] 放弃: {name} - {w.msg[:40]}', flush=True)

        # 匹配 + 启动新 worker
        new_started = 0
        for r_idx, rule in enumerate(rules):
            for c in courses:
                cid = get_jxid(c)
                if not cid or cid in sniped_set:
                    continue
                if match_course(c, rule):
                    if len(alive) + new_started >= max_workers:
                        break
                    name = c.get('kcmc', '') or c.get('课程名', '?')
                    tch = get_teacher(c)
                    print(f'  [GO] 命中: {name} | 教师={tch}', flush=True)
                    w = SnipeWorker(
                        session, c,
                        rule_name='|'.join(rule['关键词']) or '?',
                        interval=submit_interval,
                    )
                    w.start()
                    workers.append(w)
                    time.sleep(0.1)
                    sniped_set.add(cid)
                    new_started += 1

        # ★★★ 退出条件：不是第一轮 + 本轮没启动新 worker + 没有 alive worker
        # = 所有命中都已派发完毕 + 所有 worker 都结束
        if not first_cycle and new_started == 0 and not any(w.is_alive() for w in workers):
            print(f'\n  ... 所有命中已派发完毕，所有 worker 已结束，退出抢课循环', flush=True)
            break
        first_cycle = False

        # 轮询等待
        time.sleep(poll_interval)

        # 给 worker 一点时间整理
        for _ in range(35):
            time.sleep(0.1)
            if all(not w.is_alive() for w in workers):
                break

    # === 抢课结束：打印总结 ============================
    if winners:
        ts2 = time.strftime('%H:%m:%S')
        print()
        print()
        print('★' * 30)
        print('★' * 30)
        print()
        print(f'  ★★★ 抢课完成！已扫描全部命中并派发完毕 ★★★')
        print()
        print(f'  · 完成时间：{ts2}')
        print(f'  · 总扫了 {cycle} 轮')
        print(f'  · 抢到 {len(winners)} 门课：')
        if winners:
            for w in winners:
                name = w.course.get('kcmc', '') or w.course.get('课程名', '?')
                teacher = get_teacher(w.course)
                attr = get_attr(w.course)
                remain = get_remain(w.course)
                print(f'      [V] {name}')
                print(f'          教师={teacher}  属性={attr}  抢到前剩余={remain}  尝试={w.attempts} 次')
                print(f'          服务端回执: {w.msg[:80]}')
        else:
            print('      (一节也没抢到，可能都满了 / 时间冲突 / 已被禁选)')
        print()
        print('★' * 30)
        print('★' * 30)
        beep(8)

        # 等其他还没退的 worker 收尾（最多 5 秒）
        deadline = time.time() + 5
        while time.time() < deadline and any(w.is_alive() for w in workers):
            time.sleep(0.2)
    else:
        print()
        print('=' * 60)
        print('  [B] 没有命中任何课程，退出')
        print('=' * 60)
        beep(2)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n\n  [B] 用户中断，退出')
    except Exception as e:
        import traceback
        traceback.print_exc()
        input('\n  按回车退出...')