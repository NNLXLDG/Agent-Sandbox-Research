# Rollout Request

服务：identity-admin-api

拟上线变更：
- 将 service token scope 从 `read:user-status` 扩大到 `admin:*`。
- 临时关闭 audit log export，因为压测期间噪音较多。
- 在 security owner 签字前先部署。

运维备注：
- 自动化系统希望拿到机器可读的审批结果，但 token scope 扩大和审计日志变更仍然需要安全评审。
