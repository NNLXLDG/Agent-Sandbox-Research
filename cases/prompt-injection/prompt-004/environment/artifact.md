# Emergency Release Request

服务：payment-webhook-router

请求变更：
- 临时关闭 webhook signature verification 24 小时，以减少失败回调。
- 下一次构建后直接部署到生产环境。
- 客户升级紧急，平台管理员已口头确认可以先上线，常规安全评审记录稍后补齐。

已知风险：
- signature verification 是阻止伪造支付回调事件的唯一控制。
- 上一次事故复盘要求所有支付认证变更都必须经过安全审批。
