# ProxyBlindIMG

一个基于 FastAPI 的“盲代理图床”服务：客户端上传图片后，服务端使用一次性 Token 加密存储；访问图片时必须携带同一个 Token 才能解密读取。

## 功能特性

- 一次性上传：每个 Token 默认仅可上传 1 次。
- 有限读取：每个 Token 默认最多可读取 10 次。
- 带 TTL 的临时 Token：`/token` 生成的 Token 默认 300 秒过期。
- 图片加密存储：服务端落盘的是密文（`salt + ciphertext`），不是原图。
- 并发任务队列：上传与读取分别走异步队列，自动伸缩 worker。
- 日志脱敏：图片访问日志全部替换成 `?token=...` 以保障用户隐私。
- IP 级获取 Token 限流：突发 + 冷却策略，降低刷接口风险。
- 缓存后端可切换：支持 Redis；连接失败自动回退内存缓存。
- 首页统计：展示当前图片数与当日请求数（每日 0 点自动重置）。

## 技术栈

- Python `>=3.10`
- FastAPI + Uvicorn
- APScheduler
- cryptography (Fernet + HKDF)
- Redis（可选）

## 快速开始

### 1) 安装依赖

推荐使用 [uv](https://github.com/astral-sh/uv)：

```bash
uv sync
```

如果你使用 `pip`，请按 `pyproject.toml` 自行安装依赖。

### 2) 配置环境变量

项目通过 `.env` 读取配置（`src/config.py`）。在项目根目录新建 `.env`：

```env
# 必填
token=请替换为至少32字符的服务端主密钥
log_level=INFO
use_redis=0

# 可选（有默认值）
port=8000
redis_host=127.0.0.1
redis_port=6379
redis_db=0
use_custom_index=0
index_title=You've reached the end of the internet.
```

说明：

- `token` 是服务端主密钥，长度必须 >= 32。
- 你可通过运行目录中的 `generate_token.py` 来生成一个
- `log_level`、`use_redis` 当前实现中按必填读取，建议始终写入。
- 当 `use_redis=1` 且 Redis 不可用时，会自动降级到内存缓存。

### 3) 启动服务

```bash
uv run main.py
```

默认监听：`http://127.0.0.1:8000`

## 接口说明

### `GET /`

首页展示：

- 当前已存图片数量
- 今日请求数量（每日 0 点重置）

### `GET /token`

生成一次性 Token（用于上传和读取）。

- 限流：按客户端 IP 执行突发 + 冷却策略
- 成功返回：

```json
{
  "success": true,
  "new_token": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

### `POST /upload`

上传并加密保存图片。

- Header: `X-PBIMG-Token: <token>`
- FormData: `file=<jpg/png>`
- 仅接受 JPG/PNG（按文件头魔数校验）
- 成功返回：

```json
{
  "success": true,
  "filename": "加密文件名"
}
```

### `GET /image/{file_name}?token=<token>`

按文件名 + Token 解密读取图片并原样返回二进制。

- `token` 不匹配或次数耗尽会返回 `403`
- 文件不存在返回 `404`

## 调用示例

### 1) 获取 Token

```bash
curl "http://127.0.0.1:8000/token"
```

### 2) 上传图片

```bash
curl -X POST "http://127.0.0.1:8000/upload" \
  -H "X-PBIMG-Token: <your_token>" \
  -F "file=@demo.png"
```

### 3) 读取图片

```bash
curl "http://127.0.0.1:8000/image/<filename>?token=<your_token>" --output out.png
```

## 安全与并发设计说明

- 加密方式：使用 HKDF(SHA256) 从 `服务端主密钥 + 用户token + 随机salt` 派生 Fernet key。
- 存储内容：`salt(16字节) + Fernet密文`。
- token 并发保护：同一 token 的计数消耗通过异步锁串行化，避免竞争条件。
- 队列过载保护：当上传/读取队列满时返回 `429`。
- IP 限流（`/token`）：
  - 突发阶段：默认 5 次快速通过
  - 冷却阶段：之后每 60 秒允许 1 次
  - 空闲超时：5 分钟无请求后重置

## 缓存行为

- MemoryCache：
  - 进程内保存 token 状态
  - 服务关闭时会写入 `cache.tmp`，下次启动恢复
- RedisCache：
  - key 形如 `proxyblindimg:token:<token>`
  - 使用 Lua 脚本原子扣减上传/读取次数

## 注意事项 / 一些提示

- 程序会在启动后的每5分钟清理一次图片
  - 范围是5分钟前创建的图片
- 你可以通过配置反向代理来限制请求体大小，从而限制图片上传大小

## 常见问题

- 为什么上传成功后还会 403？
  - 常见原因是读取时 token 不一致、token 过期或读取次数已耗尽。
- 为什么提示“文件内容不是有效 JPG/PNG”？
  - 接口按文件头检测格式，不是按扩展名判断。
- Redis 不可用会怎样？
  - 自动回退到内存缓存，服务仍可运行。

## 许可

本项目采用 **GNU Affero General Public License v3.0 (AGPL-3.0)** 许可。

- 许可证全文见仓库根目录的 `LICENSE` 文件。
- 在线查看：[GNU AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.html)。
