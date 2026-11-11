# Atlas Web

Next.js 16 + React 19 + TypeScript 学习工作台。完整启动、配置和部署方式见 [根目录 README](../README.md)。

```bash
npm ci
npm run dev
npm run typecheck
npm run build
```

默认将 `/api` 同源代理到 `http://127.0.0.1:8000/api`。修改后端地址使用 `API_URL`；生产构建时需设置该值。浏览器不读取任何模型密钥。
