# 公牛智家云（MosHome）协议分析文档

> 核心常量与请求格式最初依据 MosHome 5.1.13 分析整理，并通过线上网关校准；
> 2026-10-25 又使用 MosHome 5.3.1、线上 API 和真实设备完成兼容验收。
> 配套实现位于 `bull_iot/` 与 `custom_components/bull_iot/`，证据边界见
> `PROVENANCE.md`。

---

## 1. 总览

公牛智家 App（包名体系 MosHome）的云端由两部分组成：

| 通道 | 地址 | 用途 |
|------|------|------|
| HTTPS API | `https://api.iotbull.com` | 登录、设备管理、控制指令 |
| MQTT | `emqx-prod.iotbull.com:1883`（明文 TCP） | 设备状态实时回推 |

所有 HTTP 请求经过阿里云 API 网关风格（`x-ca-*` 签名头）的 HMAC-SHA256 签名鉴权。

## 2. 协议分析方法论（如何自己重来一遍）

1. **抓包定位**：Android 手机挂代理（mitmproxy / Charles），公牛智家 App 内操作，
   先过滤 `api.iotbull.com` 域名，观察请求路径规律（`/mos/...`、`/v1/...`、`/v2/...`）。
2. **找客户端**：App 为 React Native 壳 + 原生网络层，签名逻辑在原生层。
   对 APK 反编译（jadx）搜索常量 `x-ca-key` / `APP_PWD` / `paascloudclientuic` 定位。
3. **提取应用凭证**：从 5.1.13 客户端代码中提取 AppKey、AppSecret、
   client_id/secret、登录 AES Key——
   这些是**客户端内置的应用级凭证**，所有 App 用户相同，不是用户隐私数据。
4. **复现签名**：按阿里云网关签名规范实现，打登录接口。
5. **用网关报错校准**（关键技巧）：签名错误时，网关会在响应头
   `X-Ca-Error-Message` 里**回显服务端期望的待签字符串**，直接对比即可定位偏差，
   无需猜测。本次即靠此字段发现了「表单请求的 CanonicalResource 用表单字段本身作 query」。
6. **假凭证探活**：用假账号打接口，若返回业务错误码（如 901006）而非 403 InvalidSignature，
   即证明签名与加密全部正确，剩下只是换真实凭证。

## 3. 应用凭证（客户端内置）

| 常量 | 值 |
|------|-----|
| AppKey (`x-ca-key`) | `2037288812025` |
| AppSecret（HMAC 密钥） | `XxNjYxonJBt6DskF368fdjLEQZC9ziMeLOZPf` |
| client_id | `paascloudclientuic` |
| client_secret | `paascloudClientSecret` |
| 已验证请求版本 | `5.1.13` |
| 登录 AES Key（Base64） | `cjJ2R1dCQTNRQVJOblJsUg==` |
| 密码盐 | `GONGNIU` |

> 5.3.1 APK 已确认版本身份及 client_id/client_secret，但当前没有足够静态证据
> 宣称上表其余常量均从 5.3.1 重新提取。5.3.1 在本项目中表示兼容验收版本。

## 4. 请求签名（x-ca-* HMAC-SHA256）

每个请求携带这些头：

```
X-Ca-Key: <AppKey>
X-Ca-Nonce: <随机 UUID>
X-Ca-Signature-Method: HmacSHA256
X-Ca-Timestamp: <毫秒时间戳>
X-Ca-Signature-Headers: x-ca-key,x-ca-nonce,x-ca-signature-method,x-ca-timestamp
X-Ca-Signature: <签名>
CA_VERSION: 1
Authorization: Basic base64(client_id:client_secret)   # 登录后业务接口改为 Bearer <access_token>
X-App-Platform: android
X-App-Version: 5.1.13
User-Agent: ALIYUN-ANDROID-DEMO
Date: <RFC 1123 UTC 时间>
```

待签名字符串（换行分隔）：

```
METHOD
Accept                        # 固定 application/json; charset=utf-8
Content-MD5                   # base64(md5(body))；表单请求留空
Content-Type                  # 实际 Content-Type
Date                          # 与 Date 头相同
x-ca-key:...\n                # 四个 x-ca-* 头按 key 排序，每行 key:value 加换行
x-ca-nonce:...\n
x-ca-signature-method:...\n
x-ca-timestamp:...\n
/mos/uic/v2/auth/form?username=...&password=...   # CanonicalResource
```

> **实测校准结论**：`x-www-form-urlencoded` 请求（登录）的 CanonicalResource
> 是**表单字段本身按 key 排序组成的 query**（网关从表单体重建），且不算 Content-MD5。
> 网关在 `X-Ca-Error-Message` 响应头里回显的待签字符串把换行显示成了 `#`，别被误导。

签名 = `Base64(HmacSHA256(AppSecret, 待签字符串))`。

## 5. 登录

### 5.1 字段加密（发送前）

- **用户名**：AES-128-CBC 加密。PKCS#7 填充 → 随机 16 字节 IV → 密文 →
  拼接 `IV || 密文` → 转**大写 Hex**。
- **密码**：不传原文，传 `sha256( sha256(password) + sha256("GONGNIU") )`。

### 5.2 请求

```
POST /mos/uic/v2/auth/form
Content-Type: application/x-www-form-urlencoded; charset=utf-8
Login_parameter: APP_PWD          # 必须带，且大小写敏感（Login-Parameter 会被拒）

username=<AES加密Hex>&password=<双sha256>
```

### 5.3 应答

```json
{
  "success": true,
  "code": 200,
  "result": {
    "access_token": "...",
    "refresh_token": "...",
    "openid": "123456"
  }
}
```

- `access_token`：业务接口 Bearer 凭证，也是 MQTT 密码，有效期较短
- `refresh_token`：换发 access_token
- `openid`：用户唯一 ID，也是 MQTT 用户名

### 5.4 刷新令牌

```
POST /mos/uic/v1/auth/token
Authorization: Basic <应用凭证>     # 注意：此接口用 Basic 不用 Bearer
{"refresh_token": "...", "grant_type": "refresh_token"}
```

## 6. 设备接口

以下接口均带 `Authorization: Bearer <access_token>`。

### 6.1 家庭列表

```
GET /v2/families
-> result: [{"familyId": 123, "familyName": "我的家"}, ...]
```

> **实测限制（2026-10-25 真实账号）**：该接口**固定返回前 50 条**，
> 所有分页参数（pageNum/pageSize/pageNo/page/current/size/limit/offset）均被忽略，
> 也无可用的搜索端点（/search 全部 404）。账号家庭数超过 50 时，
> 超出的家庭无法通过 API 发现（App 侧同理，除非使用未公开的接口）。
> 另外：同一设备可被共享到多个家庭，按 iotId 去重前记录的设备条数会大于实际设备数
> （实测账号：1117 条记录 / 448 台唯一设备）。

### 6.2 切换家庭

设备列表接口只返回**最近访问家庭**的设备，多家庭需先切换：

```
POST /v1/families/{familyId}/switch
body: {}
```

### 6.3 房间与设备列表（MosHome v3）

```
GET /mos/home/v3/rooms
-> result.devices[0].deviceList: [设备记录...]
```

设备记录关键字段：

| 字段 | 说明 |
|------|------|
| `iotId` | 设备唯一 ID（控制指令用） |
| `product.globalProductId` | 产品类型 ID（决定设备是开关/窗帘/灯/充电桩） |
| `deviceEntity` | true 表示这是主设备条目（带昵称），false 是功能实体（如多路开关的一路） |
| `elementIdentifier` | 功能实体标识（如 `PowerSwitch_1`） |
| `nickName` | 用户设置的名称 |
| `roomName` | 所在房间 |
| `status` | `ONLINE` / `OFFLINE` |
| `property` | `{identifier: {value: ...}}` 属性快照 |

### 6.4 设备详情

```
GET /mos/device/v1/deviceInfo/{iotId}/get
-> result.productName / modelName / firmwareVersion
```

## 7. 控制指令

### 7.1 设置属性（开关/亮度/插座等）

```
PUT /mos/v1/dc/setDeviceProperty/{iotId}
body: [{"value": 1, "identifier": "PowerSwitch"}]
```

常用 identifier：

| identifier | 适用 | 取值 |
|------------|------|------|
| `PowerSwitch` | 开关/插座/转换器 | 1 开 / 0 关 |
| `PowerSwitch_1/2/3` | 多位开关分路 | 1 / 0 |
| `ChargeSwitch` | 充电桩充电开关 | 1 / 0 |
| 嵌套属性 | 充电桩 `DeviceRealInfo` 等 | 见设备 property 快照，可拍平为 `父.子` |

### 7.2 调用服务

```
PUT /mos/iot/v1/devices/{iotId}/invokeThingService
body: {"identifier": "SheduleAuth"}
```

如充电桩 `SheduleAuth` = 激活充电。

## 8. MQTT 实时状态

- Broker：`emqx-prod.iotbull.com:1883`（明文，无 TLS）
- 用户名：`openid`；密码：`access_token`
- clientId：`IOS@2.9.1@<openid>`
- 连接后订阅 `/sys/app/down/account/bind_reply`，并向 `/sys/app/up/account/bind`
  发布绑定报文（payload 含 token/clientId/userId，version 1.0）
- 绑定后云端推送设备消息：
  - `method=thing.properties`：`params.items.{identifier}.value`，属性变化
  - `method=thing.status`：`params.status.value`，在线状态（`ONLINE`/`OFFLINE` 或 1/3）
- 报文带 `params.iotId` 与 `params.status.time`（可用时间戳丢弃乱序旧消息）

## 9. 错误码

| code | 含义 | 处理 |
|------|------|------|
| 200 / success=true | 成功 | — |
| 901006 | 用户名或密码不正确 | 凭证错误 |
| 901001 | 用户不存在 | 凭证错误 |
| 901015 | 密码错误 | 凭证错误 |
| 9008 / error=invalid_token | 令牌失效 | 刷新或重新登录后重试 |
| HTTP 403 `A403IS` | 签名错误 | 对比 `X-Ca-Error-Message` 里的待签字符串校准 |
| HTTP 400 `I400MP` | 缺少网关参数 | 如缺 `Authorization` 或 `Login_parameter` 头 |

## 10. 产品类型速查（globalProductId）

| 类型 | 产品 ID（部分） |
|------|----------------|
| 开关/插座 | 4, 5, 6, 7, 13, 14, 30, 34-36, 53, 149, 157-159, 180 |
| 窗帘 | 31, 56, 59, 168, 198 |
| 灯具 | 79, 125, 127, 171, 175 |
| 传感器 | 61, 63, 66, 68 |
| 充电桩 | 74, 75, 141, 193, 195, 196, 258, 274, 275, 296, 309 |

## 11. 验证记录

### 11.1 2026-10-25 沙箱实测（假凭证，验证签名层）

| 测试 | 请求 | 结果 |
|------|------|------|
| 登录签名 | 假账号打 `/mos/uic/v2/auth/form` | HTTP 401 `{"code":901006,"message":"用户名或密码不正确"}` → 签名+加密正确 |
| 家庭列表签名 | 假 Bearer token 打 `GET /v2/families` | HTTP 401 `invalid_token` → 签名正确 |
| 设备列表签名 | 假 token 打 `GET /mos/home/v3/rooms` | HTTP 401 `invalid_token` → 签名正确 |
| 控制指令签名 | 假 token 打 `PUT /mos/v1/dc/setDeviceProperty/fake-iot-id` | HTTP 401 `invalid_token` → 签名正确 |
| MQTT broker | TCP 连接 `emqx-prod.iotbull.com:1883` | 可连接 |

### 11.2 2026-10-25 真实账号实测（全链路）

| 测试 | 结果 |
|------|------|
| 真实账号登录 | 成功，openid=107***（已脱敏） |
| 设备列表 | 成功拉取设备（全账号 1117 条记录 / 448 台唯一设备，大量跨家庭共享） |
| MQTT 连接+绑定 | 连接结果 0，`/sys/app/down/account/bind_reply` 返回 `code=200 message=success` |
| **真实设备控制** | `PUT /mos/v1/dc/setDeviceProperty/{iotId}` 对「我的家」G27 三位开关通道 1 下发 `PowerSwitch_1=0`，云端接受（success=true）且回读状态一致 |
| MQTT 属性回推 | 待设备状态变化时触发（本次操作前后状态一致，未产生状态变化事件） |

真实设备列表补充观察到的 identifier（写集成时按需处理）：

| identifier | 出现设备 | 说明 |
|------------|----------|------|
| `LoadStatus_N` | G27 单火开关 | 第 N 路负载状态（与 `PowerSwitch_N` 对应） |
| `KeyMode_N` / `Position_N` | G55 零火开关 | 按键模式 / 按键位置（257/258 等） |
| `IndicatorLight` | G55 系列 | 指示灯开关 |
| `VirtualClick_1` | G55 情景开关 | 情景按键（无线开关无 PowerSwitch） |
| `CountDown` / `PeriodTimer_N` | WiFi 转换器 | 倒计时 / 周期定时（嵌套 JSON，已拍平为 `父.子`） |
| `PowerSwitch_LocalTimer` | WiFi 转换器 | 本地定时任务列表（cron 表达式） |
| `BatteryStatus` / `BatteryPercent` | 无线开关 / 传感器 | 电池状态 / 电量 |
| `TestMode_N` | 部分 G55 | 测试模式标志 |
| `memory` | WiFi 转换器 | 断电记忆 |
