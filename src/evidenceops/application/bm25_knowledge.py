"""固定候选集合上的确定性BM25；不负责权限、版本发布或查询改写。"""
from dataclasses import replace
from collections import Counter
import math
import re

from evidenceops.application.knowledge_retrieval import KnowledgeMatch
from evidenceops.domain.knowledge import KnowledgeChunk


def tokenize(text:str)->tuple[str,...]:
	if not isinstance(text,str): raise TypeError("文本必须是字符串")
	return tuple(re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]",text.lower()))


class BM25KnowledgeRetriever:
	def __init__(self,k1:float=1.2,b:float=0.75)->None:
		if type(k1) not in (float,int) or type(b) not in (float,int): raise ValueError("BM25参数必须为数值")
		if not math.isfinite(k1) or k1<=0 or not math.isfinite(b) or not 0<=b<=1: raise ValueError("BM25参数无效")
		self.k1=k1
		self.b=b

	def search(self,chunks:tuple[KnowledgeChunk,...],query:str,top_k:int=5)->tuple[KnowledgeMatch,...]:
		if not isinstance(chunks,tuple): raise TypeError("chunks必须是元组")
		if len({chunk.chunk_id for chunk in chunks})!=len(chunks): raise ValueError("候选片段不能重复")
		if not isinstance(query,str) or not query.strip(): raise ValueError("query不能为空")
		if type(top_k) is not int or not 1<=top_k<=50: raise ValueError("top_k必须在1到50之间")
		doc_tokens=[]
		for chunk in chunks:
			text=" ".join(chunk.heading_path)+" "+chunk.content
			doc_tokens.append(tokenize(text))
		lengths=tuple(len(tokens) for tokens in doc_tokens)
		average_length=sum(lengths)/len(lengths) if lengths else 0
		# 查询词只计一次，文档词频必须保留重复，才能实现频率饱和。
		query_terms=tuple(dict.fromkeys(tokenize(query)))
		if not query_terms or not doc_tokens or average_length==0: return ()
		# 每片段只统计一次词频；避免对每个查询词重新扫描整段正文。
		frequencies=tuple(Counter(tokens) for tokens in doc_tokens)
		document_frequency={term:sum(term in counts for counts in frequencies) for term in query_terms}
		inverse_frequency={term:math.log(1+(len(doc_tokens)-count+0.5)/(count+0.5)) for term,count in document_frequency.items()}
		results=[]
		for index,(chunk,counts) in enumerate(zip(chunks,frequencies)):
			score=0.0
			for term in query_terms:
				frequency=counts[term]
				if not frequency: continue
				idf=inverse_frequency[term]
				normalizer=frequency+self.k1*(1-self.b+self.b*lengths[index]/average_length)
				score+=idf*(frequency*(self.k1+1)/normalizer)
			if score>0: results.append((score,chunk))
		results.sort(key=lambda item:(-item[0],item[1].chunk_id))
		return tuple(KnowledgeMatch(chunk,score,rank,"bm25-v1",retrieval_details={"score_kind":"bm25","k1":self.k1,"b":self.b,"tokenizer":"word-or-han-char-v1"})
			for rank,(score,chunk) in enumerate(results[:top_k],1))


def bm25_ranking(matches:tuple[KnowledgeMatch,...],query:str,candidate_k:int,k1:float=1.2,b:float=0.75)->tuple[KnowledgeMatch,...]:
	if type(candidate_k) is not int or not 1<=candidate_k<=50: raise ValueError("每路候选必须在1到50之间")
	if len({match.chunk.chunk_id for match in matches})!=len(matches): raise ValueError("候选片段不能重复")
	by_id={match.chunk.chunk_id:match for match in matches}
	found=BM25KnowledgeRetriever(k1,b).search(tuple(match.chunk for match in matches),query,candidate_k)
	return tuple(replace(by_id[match.chunk.chunk_id],score=match.score,rank=rank,retrieval_method="bm25-v1",retrieval_details=match.retrieval_details)
		for rank,match in enumerate(found,1))
