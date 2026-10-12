import type { NextConfig } from "next"; // 约束配置为当前 Next.js 支持的选项。
const next_config:NextConfig={poweredByHeader:false,reactStrictMode:true,outputFileTracingRoot:process.cwd()}; // 追踪范围固定为前端，避免扫描后端虚拟环境。
export default next_config; // 交给 Next.js 加载配置。
