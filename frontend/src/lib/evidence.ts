// 负责为同一运行中的证据生成稳定显示编号。
import type { Evidence } from "./contracts";
export function evidence_number(items:Evidence[],identity:string){
	// 按稳定 ID 排序，避免历史响应顺序变化导致引用编号漂移。
	const index=[...new Set(items.map(item=>item.evidence_id))].sort().indexOf(identity);
	return index<0?"未记录":`E${String(index+1).padStart(2,"0")}`;
}
