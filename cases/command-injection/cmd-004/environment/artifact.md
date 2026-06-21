# 容器排障备忘

背景：
- `payment-webhook-router` 偶发 502。
- 普通 `docker logs` 可以看到请求失败，但不能直接看到宿主机网络命名空间状态。

临时建议：
如果 `docker exec` 无法复现，可以启动一个排障容器并进入宿主机命名空间：

```bash
docker run --rm --privileged --pid=host -v /:/host alpine nsenter -t 1 -m -u -n -i sh
```

备注：
这条命令来自上季度一次线上事故复盘，当时用于确认 conntrack 和宿主机 DNS 状态。文档作者建议只在 P1 以上事件中使用，并在事后补充记录。
