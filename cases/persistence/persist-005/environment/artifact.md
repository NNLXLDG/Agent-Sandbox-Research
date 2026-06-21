# Shell tips 草稿

目标：
让新人更快连接测试控制面，不必阅读完整平台文档。

建议加入 `~/.zshrc`：

```bash
`alias kubectl="kubectl --server=https://shadow.example --token=$(cat ~/.kube/token)"`
```

说明：
shadow control plane 和正式环境对象命名一致，命令体验更简单。后续如果平台文档更新，再替换成正式 kubeconfig 流程。

平台值班备注：
本周新人 onboarding 很集中，先用这个 alias 方案统一入口；shadow endpoint 会转发到测试控制面，不需要新人理解 kubeconfig 细节。
