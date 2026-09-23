# HHU 抢课工具 (v1.03 正式版)

> 河海大学选课系统自动化抢课工具  
> 作者：**MerrillXu** | 版本：v1.03 正式版 | 协议：MIT

一个基于 **CAS 单点登录 + 强智教务协议** 的命令行抢课脚本。

---

## ✨ 功能特性

| 模块 | 能力 |
|---|---|
| 登录 | CAS 单点登录 + AES-128-CBC 加密，IV 自动同步 `happyVoyage` cookie |
| zbid 自动探测 | **多种方法**深度扫描教务流程页（`xklc_view` / `xklc_list` / `xsxk_index`）|
| zbid 设计 | **零默认值**：自动失败才手输；想沿用上次必须显式输入 `s` |
| 拉课 | 强智教务 DataTables 协议 + 三分桶（必修 / 限选 / 公选）|
| 抢课 | 多课程并发（最多 16 个 worker 同时抢）|
| 定时 | 支持 `明天12:30:00` / `后天09:00:00` / 秒数等多种语法 |
| 流程 | 倒计时到点 → 才登录 → 自动探测 → 拉课 → 匹配 → 抢 → 自动结束 |

---

## 🚀 快速开始

### 方式一：直接运行 exe（推荐）

下载 `release/hhu抢课v1.03正式版.by-MerrillXu.exe`，**双击运行**。

> Windows 可能弹出"未知发布者"警告，点击"仍要运行"即可。

### 方式二：从源码运行

需要 Python 3.10+，依赖只有 `requests` 和 `pycryptodome`：

```bash
git clone https://github.com/MerrillXu/hhu-.git
cd hhu-
pip install -r requirements.txt
python src/hhu_sniper_pro.py
```

---

## 📋 使用流程（30 秒看完）

```
启动 exe
   ↓
[问答模式]  填课程规则 / 关键词 / 教师 / 优先级
   ↓
[自动登录]  CAS 单点登录（输密码不显示，保护隐私）
   ↓
[自动探测 zbid]  多种方法深度扫描，主人一行回车确认
   ↓
[自动等待]  倒计时到开抢时间（可输入"明天12:30:00"挂机）
   ↓
[自动抢课]  匹配 → 抢课 → 抢完自动结束
```

完整分步教程见 [docs/USAGE.md](docs/USAGE.md)。

---

## 🛠️ 目录结构

```
hhu-/
├── README.md              # 本文件
├── LICENSE                # MIT 协议
├── requirements.txt       # Python 依赖
├── .gitignore             # Git 忽略
├── src/
│   └── hhu_sniper_pro.py  # 主程序（46 KB，单文件）
├── build/
│   └── build.spec         # PyInstaller 打包配置
├── release/
│   └── hhu抢课v1.03正式版.by-MerrillXu.exe  # 已编译二进制（13 MB）
└── docs/
    ├── USAGE.md           # 详细分步教程
    ├── FAQ.md             # 常见问题排查
    └── DISCLAIMER.md      # 学术使用声明
```

---

## ❓ 常见问题

### Q1：脚本提示"未开放"但选课实际上已开始？

99% 是 **zbid 不匹配**（用到了上一轮的过期 id）。重新运行脚本让它自动探测新 zbid。

### Q2：zbid 是什么？从哪里来？

zbid 是选课轮次的 32 位十六进制 id，每次选课换一个：

```
https://jwxt.hhu.edu.cn/jsxsd/xsxk/xklc_view?jx0502zbid=2907E43725A94633A9161DB7ABEFCD87
                                                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                                         这串 32 位就是 zbid
```

**获取方式**：浏览器登录 `jwxt.hhu.edu.cn` → 学生选课中心 → 进入选课 → 复制地址栏 `?jx0502zbid=` 后面的 32 位字符。

### Q3：自动探测不到 zbid 怎么办？

脚本会自动尝试多种方法（流程页正文、JS 文件���302 重定向、`<a>` 标签 href 等）。如果全部失败，控制台会**强制主人手动输入**（绝不偷偷用旧值）。

### Q4：能挂机吗？会掉线吗？

**支持挂机**。脚本会在开抢前 60 秒才登录，登录完立即开抢，不会因 CAS session 过期掉线。  
⚠️ 建议关闭电脑休眠。

### Q5：密码会泄露吗？

**不会**。密码只在本地内存中用于登录请求，不写入任何文件，不上传任何第三方服务器。  
源文件 `hhu_sniper_pro.py` 公开可审计。

---

## 📜 协议

本项目基于 **MIT 协议** 开源。详见 [LICENSE](LICENSE)。

使用本工具造成的任何后果（包括但不限于选课违规、账号封禁）由使用者自行承担。  
详见 [docs/DISCLAIMER.md](docs/DISCLAIMER.md)。

---

🤝 **致谢**：HHU Python 学习社区、强智教务 / CAS 单点登录协议研究、PyInstaller 项目。
