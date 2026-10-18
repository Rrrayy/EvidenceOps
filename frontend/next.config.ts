import type { NextConfig } from "next"; // 约束配置为当前 Next.js 支持的选项。
const next_config:NextConfig={poweredByHeader:false,reactStrictMode:true,outputFileTracingRoot:process.cwd(),distDir:process.env.EVIDENCEOPS_NEXT_DIST_DIR??".next"}; // 隔离验收使用独立构建目录，常规构建保持 .next。
export default next_config; // 交给 Next.js 加载配置。
