"""
RAG 知识库管理模块

负责：
- MES 领域知识文档的加载与分块
- 向量嵌入 (Embedding) 生成
- 向量存储与检索
- 相关知识片段的召回
"""
import os
import json
from typing import List, Dict, Any, Optional
from pathlib import Path

from core.expert_system.config import settings


class KnowledgeBase:
    """MES 生产专家知识库"""
    
    def __init__(self):
        self.vector_store_path = Path(settings.VECTOR_STORE_PATH)
        self.documents = []
        self.chunks = []
        self.embeddings = []
        self.is_loaded = False
        
    async def load(self):
        """
        加载知识库
        
        从以下来源加载 MES 领域知识：
        1. 项目文档 (API 设计、ERD、部署文档等)
        2. 业务规则定义
        3. SOP 标准作业程序
        4. 历史故障案例库
        """
        # 创建向量存储目录
        self.vector_store_path.mkdir(parents=True, exist_ok=True)
        
        # 加载项目文档作为初始知识源
        await self._load_project_docs()
        
        # TODO: 加载外部知识库
        # - MES 最佳实践
        # - 设备手册
        # - 质量标准 (ISO 等)
        
        self.is_loaded = True
        
    async def _load_project_docs(self):
        """加载项目现有文档"""
        docs_dir = Path("/workspace/docs")
        root_docs = Path("/workspace")
        
        doc_patterns = [
            "*.md",
        ]
        
        for pattern in doc_patterns:
            for doc_file in list(root_docs.glob(pattern)) + list(docs_dir.glob(pattern)):
                if doc_file.name.startswith("0_") or "DESIGN" in doc_file.name or "SUMMARY" in doc_file.name:
                    await self._ingest_document(doc_file)
                    
    async def _ingest_document(self, file_path: Path):
        """
        处理单个文档
        
        1. 读取内容
        2. 分块 (Chunking)
        3. 生成 Embedding (调用网关)
        4. 存储到向量库
        """
        try:
            content = file_path.read_text(encoding="utf-8")
            
            # 简单分块策略 (后续可优化为语义分块)
            chunks = self._chunk_text(content, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP)
            
            for chunk in chunks:
                self.chunks.append({
                    "content": chunk,
                    "source": str(file_path),
                    "metadata": {
                        "filename": file_path.name,
                        "type": "doc"
                    }
                })
                
        except Exception as e:
            print(f"Error loading document {file_path}: {e}")
            
    def _chunk_text(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        """文本分块"""
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            
            # 尝试在句子边界切分
            if end < len(text):
                last_period = chunk.rfind(".")
                last_newline = chunk.rfind("\n")
                split_point = max(last_period, last_newline)
                
                if split_point > chunk_size // 2:
                    chunk = chunk[:split_point + 1]
                    end = start + split_point + 1
                    
            chunks.append(chunk.strip())
            start = end - overlap
            
        return chunks
        
    async def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        检索相关知识片段
        
        Args:
            query: 查询文本
            top_k: 返回最相关的 K 个结果
            
        Returns:
            相关知识片段列表
        """
        # TODO: 实现向量相似度搜索
        # 1. 生成 query 的 embedding
        # 2. 计算余弦相似度
        # 3. 返回 top_k 结果
        
        # 临时实现：关键词匹配
        results = []
        query_lower = query.lower()
        
        for chunk in self.chunks:
            score = self._keyword_match_score(query_lower, chunk["content"].lower())
            if score > 0:
                results.append({
                    "content": chunk["content"],
                    "source": chunk["source"],
                    "score": score,
                    **chunk["metadata"]
                })
                
        # 按分数排序
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]
        
    def _keyword_match_score(self, query: str, content: str) -> float:
        """简单的关键词匹配评分"""
        query_words = set(query.split())
        content_words = set(content.split())
        
        if not query_words:
            return 0.0
            
        intersection = query_words & content_words
        return len(intersection) / len(query_words)
        
    async def add_document(self, content: str, metadata: Dict[str, Any] = None):
        """动态添加新知识"""
        chunks = self._chunk_text(content, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP)
        
        for chunk in chunks:
            self.chunks.append({
                "content": chunk,
                "source": "dynamic",
                "metadata": metadata or {}
            })
