"""
MES 生产数据搜索引擎核心模块
支持全文搜索、模糊匹配、多条件过滤
"""
import re
from typing import List, Dict, Any, Optional
from datetime import datetime
import json
import hashlib
from pathlib import Path

from .config import SearchEngineConfig


class SearchResult:
    """搜索结果项"""
    
    def __init__(self, 
                 id: str,
                 type: str,
                 title: str,
                 content: str,
                 score: float,
                 metadata: Dict[str, Any],
                 highlights: List[str] = None):
        self.id = id
        self.type = type
        self.title = title
        self.content = content
        self.score = score
        self.metadata = metadata
        self.highlights = highlights or []
        self.created_at = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "content": self.content[:500],  # 限制长度
            "score": round(self.score, 4),
            "metadata": self.metadata,
            "highlights": self.highlights,
            "created_at": self.created_at.isoformat()
        }


class SearchIndex:
    """倒排索引实现"""
    
    def __init__(self, index_type: str):
        self.index_type = index_type
        self.documents: Dict[str, Dict[str, Any]] = {}
        self.inverted_index: Dict[str, set] = {}  # 词 -> 文档ID集合
        self.field_index: Dict[str, Dict[str, set]] = {}  # 字段值 -> 文档ID集合
    
    def add_document(self, doc_id: str, data: Dict[str, Any]):
        """添加文档到索引"""
        self.documents[doc_id] = {
            "data": data,
            "indexed_at": datetime.now()
        }
        
        # 构建倒排索引
        text_content = self._extract_text(data)
        tokens = self._tokenize(text_content)
        
        for token in tokens:
            if token not in self.inverted_index:
                self.inverted_index[token] = set()
            self.inverted_index[token].add(doc_id)
        
        # 构建字段索引
        self._build_field_index(doc_id, data)
    
    def _extract_text(self, data: Dict[str, Any]) -> str:
        """提取文本内容"""
        texts = []
        for key, value in data.items():
            if isinstance(value, str):
                texts.append(value.lower())
            elif isinstance(value, (int, float)):
                texts.append(str(value))
            elif isinstance(value, dict):
                texts.append(self._extract_text(value))
            elif isinstance(value, list):
                for item in value:
                    texts.append(str(item).lower())
        return " ".join(texts)
    
    def _tokenize(self, text: str) -> List[str]:
        """分词处理"""
        # 中文分词简化版：按字符和常用词组
        text = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', text)
        tokens = text.split()
        
        # 添加双字组合（简单的中文分词策略）
        bigrams = []
        for i in range(len(tokens) - 1):
            if len(tokens[i]) >= 2 or len(tokens[i+1]) >= 2:
                bigrams.append(tokens[i] + tokens[i+1])
        
        return tokens + bigrams
    
    def _build_field_index(self, doc_id: str, data: Dict[str, Any]):
        """构建字段索引"""
        searchable_fields = ['id', 'code', 'name', 'status', 'type', 'category']
        
        for field in searchable_fields:
            if field not in self.field_index:
                self.field_index[field] = {}
            
            value = data.get(field)
            if value is not None:
                value_str = str(value).lower()
                if value_str not in self.field_index[field]:
                    self.field_index[field][value_str] = set()
                self.field_index[field][value_str].add(doc_id)
    
    def search(self, query: str, filters: Dict[str, Any] = None) -> List[str]:
        """搜索文档"""
        tokens = self._tokenize(query.lower())
        
        # 找到包含所有查询词的文档
        candidate_docs = None
        for token in tokens:
            matching_docs = self.inverted_index.get(token, set())
            if candidate_docs is None:
                candidate_docs = matching_docs
            else:
                candidate_docs &= matching_docs
        
        if candidate_docs is None:
            candidate_docs = set(self.documents.keys())
        
        # 应用过滤器
        if filters:
            for field, value in filters.items():
                if field in self.field_index:
                    value_str = str(value).lower()
                    if value_str in self.field_index[field]:
                        candidate_docs &= self.field_index[field][value_str]
                    else:
                        candidate_docs = set()
                        break
        
        return list(candidate_docs)
    
    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """获取文档"""
        doc = self.documents.get(doc_id)
        return doc["data"] if doc else None
    
    def get_stats(self) -> Dict[str, Any]:
        """获取索引统计信息"""
        return {
            "index_type": self.index_type,
            "document_count": len(self.documents),
            "vocabulary_size": len(self.inverted_index),
            "field_count": len(self.field_index)
        }


class MESSearchEngine:
    """MES 生产数据搜索引擎"""
    
    def __init__(self, config: SearchEngineConfig = None):
        self.config = config or SearchEngineConfig()
        self.indices: Dict[str, SearchIndex] = {}
        self.cache: Dict[str, Any] = {}
        self.cache_timestamps: Dict[str, datetime] = {}
        
        # 初始化各类型索引
        for index_type in self.config.supported_types:
            if index_type != "all":
                self.indices[index_type] = SearchIndex(index_type)
        
        # 创建索引目录
        Path(self.config.base_path).mkdir(parents=True, exist_ok=True)
    
    def index_data(self, 
                   data_type: str, 
                   documents: List[Dict[str, Any]],
                   id_field: str = "id"):
        """索引数据"""
        if data_type not in self.indices:
            raise ValueError(f"不支持的数据类型：{data_type}")
        
        index = self.indices[data_type]
        
        for doc in documents:
            doc_id = str(doc.get(id_field, hashlib.md5(json.dumps(doc).encode()).hexdigest()))
            index.add_document(doc_id, doc)
        
        # 清除缓存
        self._clear_cache()
    
    def search(self, 
               query: str,
               search_types: List[str] = None,
               filters: Dict[str, Any] = None,
               top_k: int = None,
               min_score: float = None) -> List[SearchResult]:
        """执行搜索"""
        search_types = search_types or ["all"]
        top_k = top_k or self.config.default_top_k
        min_score = min_score or self.config.min_score_threshold
        
        cache_key = f"{query}:{','.join(search_types)}:{json.dumps(filters, sort_keys=True)}"
        
        # 检查缓存
        if self.config.cache_enabled and cache_key in self.cache:
            cached_time = self.cache_timestamps.get(cache_key)
            if cached_time and (datetime.now() - cached_time).total_seconds() < self.config.cache_ttl:
                return self.cache[cache_key]
        
        all_results = []
        
        # 确定搜索范围
        if "all" in search_types:
            types_to_search = [t for t in self.config.supported_types if t != "all"]
        else:
            types_to_search = [t for t in search_types if t in self.indices]
        
        # 在各索引中搜索
        for index_type in types_to_search:
            if index_type not in self.indices:
                continue
            
            index = self.indices[index_type]
            matching_ids = index.search(query, filters)
            
            # 计算相关性分数并创建结果
            for doc_id in matching_ids:
                doc = index.get_document(doc_id)
                if doc:
                    score = self._calculate_score(query, doc)
                    if score >= min_score:
                        highlights = self._generate_highlights(query, doc)
                        result = SearchResult(
                            id=f"{index_type}:{doc_id}",
                            type=index_type,
                            title=self._get_title(doc, index_type),
                            content=self._get_content(doc, index_type),
                            score=score,
                            metadata={"source_type": index_type, **doc},
                            highlights=highlights
                        )
                        all_results.append(result)
        
        # 按分数排序
        all_results.sort(key=lambda x: x.score, reverse=True)
        
        # 截取前K个结果
        results = all_results[:top_k]
        
        # 缓存结果
        if self.config.cache_enabled:
            self.cache[cache_key] = results
            self.cache_timestamps[cache_key] = datetime.now()
        
        return results
    
    def _calculate_score(self, query: str, document: Dict[str, Any]) -> float:
        """计算相关性分数"""
        query_tokens = set(self._tokenize(query.lower()))
        doc_text = self._extract_text(document).lower()
        doc_tokens = set(self._tokenize(doc_text))
        
        if not doc_tokens:
            return 0.0
        
        # Jaccard 相似度
        intersection = len(query_tokens & doc_tokens)
        union = len(query_tokens | doc_tokens)
        jaccard_score = intersection / union if union > 0 else 0.0
        
        # 精确匹配加分
        exact_match_bonus = 0.0
        for field in ['code', 'name', 'title']:
            value = str(document.get(field, '')).lower()
            if query.lower() in value:
                exact_match_bonus += 0.2
        
        # 字段权重
        weight_bonus = 0.0
        if 'status' in document and document['status'] in ['active', 'running', 'normal']:
            weight_bonus += 0.1
        
        return min(1.0, jaccard_score + exact_match_bonus + weight_bonus)
    
    def _generate_highlights(self, query: str, document: Dict[str, Any]) -> List[str]:
        """生成高亮片段"""
        highlights = []
        query_tokens = self._tokenize(query.lower())
        
        # 从标题和内容中提取包含查询词的片段
        text = self._extract_text(document)
        sentences = re.split(r'[。！？.!?\n]', text)
        
        for sentence in sentences:
            sentence_lower = sentence.lower()
            for token in query_tokens:
                if token in sentence_lower and len(token) > 1:
                    highlights.append(sentence.strip())
                    break
        
        return highlights[:3]  # 最多3个高亮片段
    
    def _get_title(self, doc: Dict[str, Any], doc_type: str) -> str:
        """获取文档标题"""
        title_fields = ['name', 'title', 'code', 'description']
        for field in title_fields:
            if field in doc:
                return str(doc[field])
        return f"{doc_type} #{doc.get('id', 'unknown')}"
    
    def _get_content(self, doc: Dict[str, Any], doc_type: str) -> str:
        """获取文档内容摘要"""
        content_fields = ['description', 'content', 'remark', 'notes']
        for field in content_fields:
            if field in doc:
                return str(doc[field])
        
        # 如果没有明确的内容字段，返回关键字段
        summary_parts = []
        for key, value in doc.items():
            if key not in ['id', 'created_at', 'updated_at']:
                summary_parts.append(f"{key}: {value}")
        
        return "; ".join(summary_parts[:5])
    
    def _extract_text(self, data: Dict[str, Any]) -> str:
        """提取文本内容"""
        texts = []
        for key, value in data.items():
            if isinstance(value, str):
                texts.append(value)
            elif isinstance(value, (int, float)):
                texts.append(str(value))
            elif isinstance(value, dict):
                texts.append(self._extract_text(value))
            elif isinstance(value, list):
                for item in value:
                    texts.append(str(item))
        return " ".join(texts)
    
    def _tokenize(self, text: str) -> List[str]:
        """分词处理"""
        text = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', text)
        tokens = text.split()
        
        # 添加双字组合
        bigrams = []
        for i in range(len(tokens) - 1):
            bigrams.append(tokens[i] + tokens[i+1])
        
        return tokens + bigrams
    
    def _clear_cache(self):
        """清除缓存"""
        self.cache.clear()
        self.cache_timestamps.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取搜索引擎统计信息"""
        stats = {
            "total_documents": 0,
            "indices": {}
        }
        
        for index_type, index in self.indices.items():
            index_stats = index.get_stats()
            stats["indices"][index_type] = index_stats
            stats["total_documents"] += index_stats["document_count"]
        
        stats["cache_size"] = len(self.cache)
        stats["supported_types"] = self.config.supported_types
        
        return stats
    
    def suggest_query(self, partial_query: str, limit: int = 5) -> List[str]:
        """查询建议"""
        if not partial_query:
            return []
        
        suggestions = set()
        partial_lower = partial_query.lower()
        
        # 从索引中收集建议
        for index in self.indices.values():
            for token in index.inverted_index.keys():
                if partial_lower in token and len(token) <= len(partial_lower) + 3:
                    suggestions.add(token)
        
        return sorted(list(suggestions))[:limit]
