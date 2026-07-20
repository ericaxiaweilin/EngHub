"""
企业级混合搜索引擎核心
实现倒排索引 + BM25 评分 + 向量空间模拟的混合检索机制

核心算法:
1. 中文分词 (使用 jieba)
2. 倒排索引构建
3. BM25 相关性评分
4. 字段权重 boosting
5. 实时增量索引
"""

import re
import time
from typing import Optional, Any
from datetime import datetime
from collections import defaultdict
import math

try:
    import jieba
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False

from .models import (
    SearchDocument, SearchQuery, SearchHit, SearchResponse,
    SearchEntityType, RelatedContext
)


class ChineseTokenizer:
    """中文分词器"""
    
    # 常用停用词
    STOPWORDS = {
        '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', 
        '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去',
        '你', '会', '着', '没有', '看', '好', '自己', '这', '那', '他'
    }
    
    def __init__(self):
        self.stopwords = self.STOPWORDS
    
    def tokenize(self, text: str) -> list[str]:
        """分词并过滤停用词"""
        if not text:
            return []
        
        if JIEBA_AVAILABLE:
            words = jieba.lcut(text.lower())
        else:
            # 简单分词：按标点和空格分割
            words = re.findall(r'[\w]+', text.lower())
        
        # 过滤停用词和单字符
        return [
            w for w in words 
            if w not in self.stopwords and len(w) > 1
        ]
    
    def extract_keywords(self, text: str, top_k: int = 10) -> list[str]:
        """提取关键词"""
        tokens = self.tokenize(text)
        # 简单词频统计
        freq = defaultdict(int)
        for token in tokens:
            freq[token] += 1
        
        # 按频率排序
        sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return [word for word, _ in sorted_words[:top_k]]


class InvertedIndex:
    """倒排索引"""
    
    def __init__(self):
        # term -> {doc_id: frequency}
        self.index: dict[str, dict[str, int]] = defaultdict(dict)
        # doc_id -> document
        self.documents: dict[str, SearchDocument] = {}
        # 文档长度 (token 数量)
        self.doc_lengths: dict[str, int] = {}
        # 平均文档长度
        self.avg_doc_length: float = 0.0
        # 总文档数
        self.total_docs: int = 0
    
    def add_document(self, doc: SearchDocument):
        """添加文档到索引"""
        doc_id = doc.id
        
        # 如果文档已存在，先删除
        if doc_id in self.documents:
            self.remove_document(doc_id)
        
        # 分词
        tokenizer = ChineseTokenizer()
        content_tokens = tokenizer.tokenize(doc.content)
        title_tokens = tokenizer.tokenize(doc.title)
        
        # 标题权重加倍
        all_tokens = content_tokens + title_tokens * 2
        
        # 更新词频统计
        term_freq = defaultdict(int)
        for token in all_tokens:
            term_freq[token] += 1
        
        # 添加到倒排索引
        for term, freq in term_freq.items():
            self.index[term][doc_id] = freq
        
        # 存储文档
        self.documents[doc_id] = doc
        self.doc_lengths[doc_id] = len(all_tokens)
        self.total_docs += 1
        
        # 更新平均文档长度
        total_length = sum(self.doc_lengths.values())
        self.avg_doc_length = total_length / self.total_docs if self.total_docs > 0 else 0
    
    def remove_document(self, doc_id: str):
        """从索引中删除文档"""
        if doc_id not in self.documents:
            return
        
        # 从倒排索引中移除
        for term in self.index:
            if doc_id in self.index[term]:
                del self.index[term][doc_id]
        
        # 清理空 term
        self.index = defaultdict(dict, {k: v for k, v in self.index.items() if v})
        
        # 删除文档
        if doc_id in self.documents:
            del self.documents[doc_id]
        if doc_id in self.doc_lengths:
            del self.doc_lengths[doc_id]
        
        self.total_docs -= 1
        
        # 更新平均文档长度
        if self.total_docs > 0:
            total_length = sum(self.doc_lengths.values())
            self.avg_doc_length = total_length / self.total_docs
    
    def get_posting_list(self, term: str) -> dict[str, int]:
        """获取词的倒排列表"""
        return self.index.get(term, {})
    
    def get_all_terms(self) -> list[str]:
        """获取所有索引词"""
        return list(self.index.keys())


class BM25Scorer:
    """BM25 评分器"""
    
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1  # 词频饱和度参数
        self.b = b    # 长度归一化参数
    
    def score(
        self, 
        query_tokens: list[str], 
        doc_id: str, 
        index: InvertedIndex
    ) -> float:
        """计算文档与查询的 BM25 分数"""
        score = 0.0
        
        doc_length = index.doc_lengths.get(doc_id, 0)
        if doc_length == 0:
            return 0.0
        
        # 长度归一化因子
        norm_factor = 1 - self.b + self.b * (doc_length / index.avg_doc_length)
        
        for token in query_tokens:
            posting_list = index.get_posting_list(token)
            if doc_id not in posting_list:
                continue
            
            # 词频
            tf = posting_list[doc_id]
            
            # 逆文档频率 (IDF)
            df = len(posting_list)  # 包含该词的文档数
            idf = math.log(
                (index.total_docs - df + 0.5) / (df + 0.5) + 1
            )
            
            # BM25 分数
            tf_score = (tf * (self.k1 + 1)) / (tf + self.k1 * norm_factor)
            score += idf * tf_score
        
        return score


class UnifiedSearchEngine:
    """统一搜索引擎"""
    
    def __init__(self):
        self.index = InvertedIndex()
        self.scorer = BM25Scorer()
        self.tokenizer = ChineseTokenizer()
        self.created_at = datetime.now()
    
    def index_document(self, doc: SearchDocument):
        """索引文档"""
        # 自动提取关键词
        if not doc.keywords:
            doc.keywords = self.tokenizer.extract_keywords(doc.content + " " + doc.title)
        
        self.index.add_document(doc)
    
    def delete_document(self, entity_type: SearchEntityType, entity_id: str):
        """删除文档"""
        doc_id = f"{entity_type.value}:{entity_id}"
        self.index.remove_document(doc_id)
    
    def search(self, query: SearchQuery) -> SearchResponse:
        """执行搜索"""
        start_time = time.time()
        
        # 分词
        query_tokens = self.tokenizer.tokenize(query.query)
        if not query_tokens:
            return self._empty_response(query)
        
        # 收集候选文档
        candidate_docs: set[str] = set()
        for token in query_tokens:
            posting_list = self.index.get_posting_list(token)
            candidate_docs.update(posting_list.keys())
        
        # 评分和排序
        hits: list[SearchHit] = []
        for doc_id in candidate_docs:
            doc = self.index.documents.get(doc_id)
            if not doc:
                continue
            
            # 实体类型过滤
            if query.entity_types and doc.entity_type not in query.entity_types:
                continue
            
            # 状态/优先级等过滤
            if not self._matches_filters(doc, query.filters):
                continue
            
            # 权限过滤 (简化版)
            if query.context_user_id and not self._check_permission(doc, query.context_user_id):
                continue
            
            # 计算分数
            score = self.scorer.score(query_tokens, doc_id, self.index)
            
            # 上下文感知 boosting
            if query.context_station_id and doc.metadata.get('station_id') == query.context_station_id:
                score *= 1.5
            
            # 状态 boosting
            if doc.status in ['active', 'running', 'in_progress']:
                score *= 1.2
            
            if score > 0:
                hit = SearchHit(
                    document=doc,
                    score=score,
                    highlights=self._generate_highlights(doc, query_tokens) if query.highlight_enabled else {},
                    explanation=f"匹配关键词：{', '.join(query_tokens)}"
                )
                hits.append(hit)
        
        # 排序
        if query.sort_by == 'relevance':
            hits.sort(key=lambda x: x.score, reverse=(query.sort_order == 'desc'))
        elif query.sort_by == 'date':
            hits.sort(key=lambda x: x.document.updated_at, reverse=(query.sort_order == 'desc'))
        elif query.sort_by == 'title':
            hits.sort(key=lambda x: x.document.title, reverse=(query.sort_order == 'desc'))
        
        # 分页
        total_hits = len(hits)
        page_start = (query.page - 1) * query.page_size
        page_end = page_start + query.page_size
        paginated_hits = hits[page_start:page_end]
        
        # 聚合统计
        aggregations = self._compute_aggregations(hits)
        
        # 搜索建议
        suggestions = self._generate_suggestions(query_tokens)
        
        took_ms = int((time.time() - start_time) * 1000)
        
        return SearchResponse(
            query=query.query,
            total_hits=total_hits,
            page=query.page,
            page_size=query.page_size,
            total_pages=max(1, (total_hits + query.page_size - 1) // query.page_size),
            hits=paginated_hits,
            aggregations=aggregations,
            suggestions=suggestions,
            took_ms=took_ms
        )
    
    def _matches_filters(self, doc: SearchDocument, filters: dict[str, Any]) -> bool:
        """检查文档是否匹配过滤器"""
        for key, value in filters.items():
            doc_value = getattr(doc, key, None) or doc.metadata.get(key)
            if isinstance(value, list):
                if doc_value not in value:
                    return False
            elif doc_value != value:
                return False
        return True
    
    def _check_permission(self, doc: SearchDocument, user_id: str) -> bool:
        """简化权限检查 (实际应集成 RBAC 系统)"""
        # TODO: 集成真实权限系统
        return True
    
    def _generate_highlights(
        self, 
        doc: SearchDocument, 
        tokens: list[str]
    ) -> dict[str, list[str]]:
        """生成高亮片段"""
        highlights = {}
        
        # 从 content 中提取
        content = doc.content
        for token in tokens:
            if token.lower() in content.lower():
                # 找到包含关键词的句子
                sentences = re.split(r'[。！？.!?]', content)
                for sentence in sentences:
                    if token.lower() in sentence.lower():
                        if 'content' not in highlights:
                            highlights['content'] = []
                        highlights['content'].append(sentence.strip()[:100])
                        break
        
        return highlights
    
    def _compute_aggregations(
        self, 
        hits: list[SearchHit]
    ) -> dict[str, dict[str, int]]:
        """计算分面聚合"""
        aggregations = {
            'entity_type': defaultdict(int),
            'status': defaultdict(int),
            'category': defaultdict(int),
        }
        
        for hit in hits:
            doc = hit.document
            aggregations['entity_type'][doc.entity_type.value] += 1
            if doc.status:
                aggregations['status'][doc.status] += 1
            if doc.category:
                aggregations['category'][doc.category] += 1
        
        return {k: dict(v) for k, v in aggregations.items()}
    
    def _generate_suggestions(self, tokens: list[str]) -> list[str]:
        """生成搜索建议"""
        suggestions = []
        all_terms = self.index.get_all_terms()
        
        # 基于前缀匹配
        for token in tokens:
            prefix_matches = [t for t in all_terms if t.startswith(token)]
            suggestions.extend(prefix_matches[:3])
        
        return list(set(suggestions))[:5]
    
    def _empty_response(self, query: SearchQuery) -> SearchResponse:
        """返回空响应"""
        return SearchResponse(
            query=query.query,
            total_hits=0,
            page=query.page,
            page_size=query.page_size,
            total_pages=0,
            hits=[],
            aggregations={},
            suggestions=[],
            took_ms=0
        )
    
    def get_stats(self) -> dict[str, Any]:
        """获取索引统计信息"""
        return {
            'total_documents': self.index.total_docs,
            'total_terms': len(self.index.index),
            'avg_doc_length': round(self.index.avg_doc_length, 2),
            'entity_types': self._count_by_entity_type(),
            'created_at': self.created_at.isoformat(),
        }
    
    def _count_by_entity_type(self) -> dict[str, int]:
        """按实体类型统计"""
        counts = defaultdict(int)
        for doc in self.index.documents.values():
            counts[doc.entity_type.value] += 1
        return dict(counts)


# 全局搜索引擎实例
_search_engine: Optional[UnifiedSearchEngine] = None


def get_search_engine() -> UnifiedSearchEngine:
    """获取搜索引擎单例"""
    global _search_engine
    if _search_engine is None:
        _search_engine = UnifiedSearchEngine()
    return _search_engine


def reset_search_engine():
    """重置搜索引擎 (用于测试)"""
    global _search_engine
    _search_engine = None
