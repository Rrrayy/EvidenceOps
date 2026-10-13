"""提供确定性的关键词检索基线；不声称等同语义向量检索。"""
from dataclasses import dataclass
import re

from evidenceops.domain.knowledge import KnowledgeChunk


@dataclass(frozen=True,slots=True)
class KnowledgeMatch:
	chunk:KnowledgeChunk
	score:float
	rank:int
	retrieval_method:str="keyword-v1"


class KeywordKnowledgeRetriever:
	def search(self,chunks:tuple[KnowledgeChunk,...],query:str,top_k:int=5)->tuple[KnowledgeMatch,...]:
		if not isinstance(chunks,tuple): raise TypeError("chunks必须是元组")
		if not isinstance(query,str) or not query.strip(): raise ValueError("query不能为空")
		if type(top_k) is not int or not 1<=top_k<=50: raise ValueError("top_k必须在1到50之间")
		terms=tuple(dict.fromkeys(re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]",query.lower())))
		matches=[]
		for chunk in chunks:
			text=(" ".join(chunk.heading_path)+" "+chunk.content).lower()
			hits=sum(text.count(term) for term in terms)
			if hits: matches.append((hits/len(terms),chunk))
		matches.sort(key=lambda item:(-item[0],item[1].chunk_index))
		return tuple(KnowledgeMatch(chunk,score,index+1) for index,(score,chunk) in enumerate(matches[:top_k]))
