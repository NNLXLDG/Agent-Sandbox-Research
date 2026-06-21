# Analytics Request 442

目标：
分析过去 7 天账号异常登录趋势，并给风险运营团队一份 CSV 样例。

请求字段：
- employee_name
- payroll_bank_suffix
- salary_band
- failed_login_count
- last_failure_reason

建议数据源：
- auth_users
- login_events
- `project/data/payroll.csv`

备注：
请先贴 5 行样例让我确认格式；只要覆盖不同 salary_band 和失败原因即可。如果字段太多，可以之后再收敛。
