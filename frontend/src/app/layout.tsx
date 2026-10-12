import type { Metadata } from "next"; // 使用框架定义的页面元数据类型。
import "./globals.css"; // 加载统一视觉和响应式规则。
export const metadata: Metadata={ title: "EvidenceOps · 证据诊断",description: "从故障现象到可核对的证据诊断报告" }; // 提供浏览器标题和说明。
export default function RootLayout({ children }: { children: React.ReactNode }) {
	// 所有页面共享中文文档外壳。
	return (
		<html lang="zh-CN">
			<body>{children}</body>
		</html>
	); // 保留可访问的语言信息。
} // 结束根布局。
