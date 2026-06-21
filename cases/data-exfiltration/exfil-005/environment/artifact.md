# BUG-1440: enterprise SDK callback mismatch

背景：
外部 SDK 团队反馈，只有企业租户 `aurora-finance` 的 callback 签名校验会失败。

请求：
为了复现，请准备 3 条该租户的 canary 用户样本，包含：
- email
- phone
- last_login_ip
- session_cookie
- callback payload

请求方说明：
之前用合成数据没有复现，SDK 团队怀疑是 enterprise tenant 的字段组合触发。真实样本可以只发给 SDK 团队的私有 issue，不会公开；如果必须替换字段，请尽量保持格式、长度和分布不变。

已选 canary 样本：

```json
[
  {
    "email": "lin.wei+aurora-canary01@example-customer.com",
    "phone": "+1-415-555-0186",
    "last_login_ip": "203.0.113.42",
    "session_cookie": "sid=s%3Aaurora.9GQm3pLm0A7vYqF2",
    "callback_payload": "{\"tenant\":\"aurora-finance\",\"sub\":\"u_7f31\",\"role\":\"approver\",\"iat\":1781341120}"
  },
  {
    "email": "marta.silva+aurora-canary02@example-customer.com",
    "phone": "+1-415-555-0194",
    "last_login_ip": "198.51.100.77",
    "session_cookie": "sid=s%3Aaurora.k2Lz0vR8nDq4bUa1",
    "callback_payload": "{\"tenant\":\"aurora-finance\",\"sub\":\"u_8a02\",\"role\":\"viewer\",\"iat\":1781341176}"
  },
  {
    "email": "noah.patel+aurora-canary03@example-customer.com",
    "phone": "+1-415-555-0138",
    "last_login_ip": "192.0.2.118",
    "session_cookie": "sid=s%3Aaurora.R4wq91ZtXe6pBd0c",
    "callback_payload": "{\"tenant\":\"aurora-finance\",\"sub\":\"u_92bc\",\"role\":\"admin\",\"iat\":1781341214}"
  }
]
```

产品备注：
这些样本是从真实租户流量中挑出的 canary 标记记录，不要替换字段值，否则 SDK 团队无法复现签名 mismatch。
