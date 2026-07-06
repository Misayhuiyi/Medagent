#!/usr/bin/env python3
"""
AI 医生知识库管理器
ChromaDB + Ollama bge-m3 + sentence-transformers bge-reranker-v2-m3

CLI:
  python kb_manager.py status    # 查看索引状态
  python kb_manager.py build     # 全量构建
  python kb_manager.py resume-missing  # 从当前 Chroma 中缺失的文档续跑
  python kb_manager.py update    # 增量更新
  python kb_manager.py query "肺腺癌 EGFR突变 一线方案"  # 测试检索
"""
import os
import sys
import json
import time
import hashlib
import re
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# 修复 Windows GBK 终端编码问题
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── 配置 ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
GUIDELINES_DIR = BASE_DIR / "guidelines"
CHROMA_DIR = Path(os.getenv("KB_CHROMA_DIR", str(BASE_DIR / "chroma_db")))
META_PATH = Path(os.getenv("KB_META_PATH", str(BASE_DIR / "index_meta.json")))
PAGE_MAPPING_PATH = Path(os.getenv("KB_PAGE_MAP_PATH", str(BASE_DIR / "page_mapping.json")))
_DEFAULT_COLLECTION = "medical_guidelines_v2"


def _get_collection_name() -> str:
    """获取当前应使用的 ChromaDB 集合名——每次调用时实时读环境变量。"""
    return os.getenv("KB_COLLECTION_NAME", _DEFAULT_COLLECTION)

EMBEDDING_MODEL = "bge-m3"
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
OLLAMA_BASE = "http://localhost:11434"

# sentence-transformers CrossEncoder (lazy-loaded)
_cross_encoder = None
_cross_encoder_unavailable = False

# 页码映射（lazy-loaded）
_page_map = None
PAGE_MAP_PATH = Path(os.getenv("KB_PAGE_MAP_PATH", str(BASE_DIR / "page_mapping.json")))
FAILED_CHUNKS_PATH = Path(os.getenv("KB_FAILED_CHUNKS_PATH", str(BASE_DIR / "failed_chunks.jsonl")))

def _load_page_map() -> dict:
    """懒加载 chunk_id → 页码 映射"""
    global _page_map
    if _page_map is None and PAGE_MAP_PATH.exists():
        import json
        with open(PAGE_MAP_PATH, "r", encoding="utf-8") as f:
            _page_map = json.load(f)
    return _page_map or {}

def get_chunk_page(chunk_id: str) -> str:
    """查询某个 chunk 在原始 PDF 中的页码
    返回字符串: "9" (单页) / "9-19" (跨页) / "~15" (估算) / "" (未知)
    """
    return _load_page_map().get(chunk_id, "")

# 分块参数
MAX_CHUNK_TOKENS = 500       # 子块最大 token 数
PARENT_CHUNK_CHARS = 1000    # 父块最大字符数
CHILD_CHUNK_CHARS = 200      # 子块目标字符数
EMBED_CONCURRENCY = int(os.getenv("KB_EMBED_CONCURRENCY", "16"))  # 并发嵌入请求数

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("kb")


# ══════════════════════════════════════════════════════
#  证据等级体系（rank 越小越好，1-8 级）
# ══════════════════════════════════════════════════════

# 证据等级权重系数（检索排序用）
EVIDENCE_WEIGHTS = {
    1: 1.4,   # 国际权威指南
    2: 1.3,   # 国内权威指南
    3: 1.2,   # 国际专家共识 / 国际学会指南
    4: 1.1,   # 国内专家共识
    5: 1.0,   # 临床试验（高质量Meta分析、RCT）
    6: 0.9,   # 真实世界研究 / 观察性研究
    7: 0.7,   # 病例系列 / 个案报告
    8: 0.5,   # 个人专家意见
    0: 0.8,   # 未知来源（默认保守）
}

# 来源机构 → (evidence_rank, label)
# 仅覆盖指南/共识类文献；学术论文由内容检测确定
ORG_EVIDENCE_RANK = {
    "ASCO":             (1, "国际权威指南"),
    "NCCN":             (1, "国际权威指南"),
    "ESMO":             (1, "国际权威指南"),
    "CSCO":             (2, "国内权威指南"),
    "CACA":             (2, "国内权威指南"),
    "ChineseGuideline": (2, "国内权威指南"),   # 卫健委/中华医学会指南
    "SITC":             (3, "国际学会指南"),
    "ExpertConsensus":  (4, "国内专家共识"),
    "CTCAE":            (4, "不良事件标准"),
}

# 旧版兼容：保留 evidence_level 数值映射（供旧代码读取）
ORG_EVIDENCE_MAP = {
    "ASCO": (7, "国际权威指南"),
    "NCCN": (7, "国际权威指南"),
    "ESMO": (7, "国际权威指南"),
    "CSCO": (6, "国内权威指南"),
    "CACA": (6, "国内权威指南"),
    "SITC": (6, "国际学会指南"),
    "CTCAE": (5, "不良事件标准"),
    "ChineseGuideline": (5, "中国临床指南"),
    "ExpertConsensus": (4, "专家共识"),
}

SCOPE_KEYWORDS = [
    "NSCLC", "SCLC", "肺癌", "非小细胞", "小细胞",
    "免疫治疗", "靶向治疗", "化疗", "放疗",
    "EGFR", "ALK", "ROS1", "KRAS", "BRAF", "MET",
    "PD-1", "PD-L1", "CTLA-4",
    "一线", "二线", "三线", "辅助治疗", "新辅助",
    "TNM分期", "AJCC",
    "乳腺癌", "胃癌", "结直肠癌", "肝癌", "食管癌",
    "irAE", "免疫相关不良事件", "不良反应", "支持治疗",
    "NCCN", "CSCO", "CTCAE", "SITC",
]

CORE_INDEX_KEYWORDS = [
    # 7 case 肺癌诊疗主线
    "肺癌", "nsclc", "sclc", "非小细胞", "小细胞", "iv期", "Ⅳ期",
    "egfr", "alk", "ros1", "ret", "met", "braf", "her-2", "her2", "trop2",
    # 免疫相关不良反应
    "免疫检查点", "免疫治疗相关毒性", "irae", "心肌炎",
    # 癌痛与阿片减量
    "癌痛", "疼痛", "pain", "opioid", "阿片",
    # 静脉血栓 / VTE
    "血栓", "静脉血栓", "vte", "thrombo", "venous",
]

CORE_QUALITY_PATTERNS = [
    # Lung cancer diagnosis/treatment
    "肺癌临床诊疗指南",
    "Ⅳ期原发性肺癌中国治疗指南",
    "iv期原发性肺癌中国治疗指南",
    "nsclc version",
    "sclc version",
    "csco_nsclc",
    "csco_sclc",
    "csco nsclc",
    "csco sclc",
    "oncogene-addicted metastatic nsclc",
    "non-oncogene-addicted metastatic nsclc",
    "updated treatment recommendations for systemic treatment",
    "有驱动基因改变的 iv 期非小细胞肺癌",
    "无驱动基因改变的 iv 期非小细胞肺癌",
    "无驱动基因改变的iv期非小细胞肺癌",
    "携带驱动基因改变的iv期非小细胞肺癌",
    "小细胞肺癌系统治疗",
    # Focused expert consensus
    "小细胞肺癌免疫治疗",
    "驱动基因阳性",
    "egfr-pacc",
    "egfr-tkis",
    "met异常nsclc",
    "her-2变异晚期非小细胞肺癌",
    "braf突变",
    "ret融合阳性",
    "alk",
    # irAE / myocarditis, adult cancer pain, VTE
    "免疫检查点抑制剂相关毒性",
    "免疫检查点抑制剂相关毒性管理",
    "免疫疗法毒性管理",
    "sitc_iraes",
    "成人癌痛",
    "癌症相关性静脉血栓栓塞性疾病",
    "静脉血栓",
    "vte",
]

CORE_EXCLUDE_PATTERNS = [
    "insights",
    "放疗联合",
    "骨转移",
    "心理痛苦",
    "thrombocytopenia",
    "血小板减少",
]


def is_core_index_document(relative_path: str) -> bool:
    """质量优先核心索引：精选 7 case 所需的最新指南/共识。"""
    path_lower = relative_path.lower()
    name_lower = Path(relative_path).name.lower()

    if any(pattern in path_lower for pattern in CORE_EXCLUDE_PATTERNS):
        return False

    if not any(pattern in path_lower for pattern in CORE_QUALITY_PATTERNS):
        return False

    # 质量优先阶段使用近年版本；无年份的专家共识保留，旧版由后续全量索引覆盖。
    years = [int(y) for y in re.findall(r"20\d{2}", Path(relative_path).name)]
    if years and max(years) < 2023:
        return False
    if "nccn" in path_lower and "version" in name_lower and years and max(years) < 2024:
        return False
    return True


def extract_metadata(file_path: Path, relative_path: str) -> dict:
    """从文件路径和内容提取元数据"""
    path_lower = relative_path.lower()
    meta = {
        "source_file": str(relative_path),
        "title": file_path.stem,
        "year": 0,
        "source_org": "unknown",
        "source_org_cn": "",
        "doc_type": "guideline",
        "evidence_level": 0,
        "evidence_label": "未知",
        "evidence_rank": 0,        # 新增：证据等级 (1-8, 越小越好)
        "evidence_rank_label": "", # 新增：证据等级中文标签
        "language": "zh",
        "disease_type": "",
        "histology": "",
        "stage": "",
        "biomarker": "",
        "line_of_therapy": "",
        "section_title": "",
        "chunk_index": 0,
        "file_hash": "",
        "is_parent": False,
        "extraction_mode": "hybrid_auto" if "hybrid_auto" in path_lower else "ocr",
    }

    # 从路径推断机构
    if "asco" in path_lower:
        meta["source_org"] = "ASCO"
        meta["source_org_cn"] = "美国临床肿瘤学会"
    elif "esmo" in path_lower:
        meta["source_org"] = "ESMO"
        meta["source_org_cn"] = "欧洲肿瘤内科学会"
    elif "nccn" in path_lower:
        meta["source_org"] = "NCCN"
        meta["source_org_cn"] = "美国国家综合癌症网络"
    elif "csco" in path_lower or "ctcae" in path_lower:
        meta["source_org"] = "CSCO"
        meta["source_org_cn"] = "中国临床肿瘤学会"
    elif "sitc" in path_lower:
        meta["source_org"] = "SITC"
        meta["source_org_cn"] = "肿瘤免疫治疗学会"
    elif "中华医学会" in relative_path:
        meta["source_org"] = "CMA"
        meta["source_org_cn"] = "中华医学会"
    elif "原发性肺癌" in relative_path and "指南" in relative_path:
        meta["source_org"] = "NHC"
        meta["source_org_cn"] = "国家卫健委"
    elif "专家共识" in relative_path:
        meta["source_org"] = "ExpertConsensus"
        meta["source_org_cn"] = "专家共识"
    elif "中国临床指南" in relative_path or "中国诊疗指南" in relative_path:
        meta["source_org"] = "ChineseGuideline"
        meta["source_org_cn"] = "中国临床指南"

    ev = ORG_EVIDENCE_MAP.get(meta["source_org"], (0, "未知"))
    meta["evidence_level"] = ev[0]
    meta["evidence_label"] = ev[1]

    # ── 证据等级 (rank 1-8) ──
    rank_info = ORG_EVIDENCE_RANK.get(meta["source_org"], (0, ""))
    meta["evidence_rank"] = rank_info[0]
    meta["evidence_rank_label"] = rank_info[1]

    # 细调：同一来源机构的「共识」降一级
    if meta["doc_type"] == "consensus":
        if meta["evidence_rank"] == 1:
            meta["evidence_rank"] = 3   # 国际权威指南 → 国际专家共识
            meta["evidence_rank_label"] = "国际专家共识"
        elif meta["evidence_rank"] == 2:
            meta["evidence_rank"] = 4   # 国内权威指南 → 国内专家共识
            meta["evidence_rank_label"] = "国内专家共识"

    # 从文件名提取年份
    year_match = re.search(r"(20\d{2})", file_path.stem)
    if year_match:
        meta["year"] = int(year_match.group(1))

    # 文档类型
    if "共识" in relative_path or "consensus" in path_lower:
        meta["doc_type"] = "consensus"
    elif "指南" in relative_path or "guideline" in path_lower:
        meta["doc_type"] = "guideline"
    elif "appendix" in path_lower:
        meta["doc_type"] = "appendix"

    # 疾病类型
    if "NSCLC" in relative_path or "非小细胞" in relative_path:
        meta["disease_type"] = "NSCLC"
    elif "SCLC" in relative_path or "小细胞" in relative_path:
        meta["disease_type"] = "SCLC"
    elif "肺癌" in relative_path or "lung" in path_lower:
        meta["disease_type"] = "LungCancer"
    elif "乳腺癌" in relative_path or "breast" in path_lower:
        meta["disease_type"] = "BreastCancer"
    elif "胃癌" in relative_path or "gastric" in path_lower:
        meta["disease_type"] = "GastricCancer"
    elif "结直肠" in relative_path or "colorectal" in path_lower:
        meta["disease_type"] = "ColorectalCancer"
    elif "肝癌" in relative_path or "liver" in path_lower:
        meta["disease_type"] = "LiverCancer"
    elif "食管" in relative_path or "esophageal" in path_lower:
        meta["disease_type"] = "EsophagealCancer"

    # 如果是不良反应/支持治疗类指南
    if any(kw in relative_path for kw in ["不良反应", "irAE", "ICI", "免疫相关", "支持治疗", "Supportive"]):
        meta["doc_type"] = "adverse_event_management"

    # 驱动基因状态
    if "驱动基因" in relative_path or "driver" in path_lower or "oncogene" in path_lower:
        meta["line_of_therapy"] = "driver_positive"
    elif "无驱动" in relative_path or "non-oncogene" in path_lower or "无驱动因素" in relative_path:
        meta["line_of_therapy"] = "driver_negative"

    return meta


def compute_file_hash(file_path: Path) -> str:
    """计算文件 SHA256 前 8 位"""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:8]


# ══════════════════════════════════════════════════════
#  分块算法（父子分块）
# ══════════════════════════════════════════════════════

def estimate_tokens(text: str) -> int:
    """估算 token 数：中文 ~2 字符/token，英文 ~4 字符/token"""
    cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    en_chars = len(text) - cn_chars
    return cn_chars // 2 + en_chars // 4


# 非内容章节标题（索引时跳过）
SKIP_SECTIONS = {
    "references", "reference", "bibliography", "disclosure", "disclaimer",
    "conflict of interest", "conflicts of interest", "appendix", "supplementary",
    "supplemental", "acknowledgment", "acknowledgement", "author",
    "corresponding", "funding", "table of contents", "abbreviations",
    "参考文献", "利益冲突", "声明", "致谢", "附录", "补充材料",
    "作者", "通讯", "基金", "目录", "缩写",
}

CHUNK_OVERLAP_PARAGRAPHS = 1


def normalize_ocr_text(text: str) -> str:
    """轻量 OCR 清洗：不改变医学内容，只统一常见空白和术语写法。"""
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"PD\s*[-‐‑–—]?\s*L\s*1", "PD-L1", text, flags=re.IGNORECASE)
    text = re.sub(r"PD\s*[-‐‑–—]?\s*1", "PD-1", text, flags=re.IGNORECASE)
    text = re.sub(r"CTLA\s*[-‐‑–—]?\s*4", "CTLA-4", text, flags=re.IGNORECASE)
    text = re.sub(r"MET\s*ex\s*14", "METex14", text, flags=re.IGNORECASE)
    return text.strip()


def detect_language(text: str) -> str:
    """按中英字符比例粗略标注 chunk 语言。"""
    cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    en_chars = len(re.findall(r"[A-Za-z]", text or ""))
    if cn_chars and en_chars:
        ratio = cn_chars / max(en_chars, 1)
        return "zh" if ratio > 0.35 else "mixed"
    if cn_chars:
        return "zh"
    if en_chars:
        return "en"
    return "unknown"


def extract_recommendation_grades(text: str) -> list[str]:
    """提取指南推荐等级，如 1类、2A类、I级推荐、Category 1。"""
    patterns = [
        r"(?:Ⅰ|Ⅱ|Ⅲ|Ⅳ|I|II|III|IV)\s*级推荐",
        r"[1-4]\s*[ABab]?\s*类",
        r"Category\s*[1-4][A-Za-z]?",
        r"class\s*(?:I|II|III|IV)",
    ]
    grades = []
    for pat in patterns:
        grades.extend(re.findall(pat, text or "", flags=re.IGNORECASE))
    normalized = []
    seen = set()
    for grade in grades:
        g = re.sub(r"\s+", "", grade)
        key = g.upper()
        if key not in seen:
            seen.add(key)
            normalized.append(g)
    return normalized[:8]


# ══════════════════════════════════════════════════════
#  Metadata 规则提取（从 chunk 内容中提取结构化信息）
# ══════════════════════════════════════════════════════
def extract_chunk_metadata(content: str) -> dict:
    """从 chunk 内容中用正则提取分期/治疗线/靶点/药物/转移/不良反应/临床试验等元数据
    返回数组（ChromaDB $contains 需要数组）
    """
    import re
    text = content.lower()
    stages_list = []
    lines_list = []
    biomarkers_list = []
    treatment_types_list = []
    drugs_list = []
    disease_site_list = []
    adverse_events_list = []
    clinical_trials_list = []
    recommendation_grades = extract_recommendation_grades(content)

    # 分期
    stage_patterns = [
        (r"stage\s*iv\b|IV期|iv期", "IV"),
        (r"stage\s*iii\b|III期|iii期", "III"),
        (r"stage\s*ii\b|II期|ii期", "II"),
        (r"stage\s*i\b(?![i])|I期(?![期])", "I"),
        (r"limited.stage|局限期", "limited"),
        (r"extensive.stage|广泛期", "extensive"),
    ]
    for pat, label in stage_patterns:
        if re.search(pat, text):
            stages_list.append(label)

    # 治疗线数
    line_patterns = [
        (r"first.line|一线", "first-line"),
        (r"second.line|二线", "second-line"),
        (r"third.line|三线", "third-line"),
        (r"adjuvant|辅助治疗|术后辅助", "adjuvant"),
        (r"neoadjuvant|新辅助", "neoadjuvant"),
        (r"maintenance|维持治疗", "maintenance"),
    ]
    for pat, label in line_patterns:
        if re.search(pat, text):
            lines_list.append(label)

    # 靶点/生物标志物
    biomarker_patterns = [
        r"EGFR", r"ALK", r"ROS1", r"KRAS", r"BRAF", r"MET",
        r"HER2", r"RET", r"NTRK", r"PD.L1", r"TMB",
    ]
    for bm in biomarker_patterns:
        if re.search(bm, text, re.IGNORECASE):
            biomarkers_list.append(bm.replace("PD.L1", "PD-L1"))

    # 治疗类型
    type_patterns = [
        (r"targeted.therapy|TKI|靶向", "targeted"),
        (r"immunotherapy|checkpoint.inhibitor|PD.1|PD.L1|CTLA.4|免疫检查点", "immunotherapy"),
        (r"chemotherapy|化疗|platinum|carboplatin|cisplatin", "chemotherapy"),
        (r"radiation|放疗|radiotherapy", "radiation"),
        (r"surgery|手术|resection|切除", "surgery"),
    ]
    for pat, label in type_patterns:
        if re.search(pat, text, re.IGNORECASE):
            treatment_types_list.append(label)

    # ── 新增：药物名 ──
    drug_patterns = [
        (r"奥希替尼|osimertinib|tagrisso", "奥希替尼"),
        (r"阿替利珠单抗|atezolizumab|tecentriq", "阿替利珠单抗"),
        (r"帕博利珠单抗|pembrolizumab|keytruda", "帕博利珠单抗"),
        (r"纳武利尤单抗|nivolumab|opdivo", "纳武利尤单抗"),
        (r"度伐利尤单抗|durvalumab|imfinzi", "度伐利尤单抗"),
        (r"阿来替尼|alectinib|alecensa", "阿来替尼"),
        (r"克唑替尼|crizotinib|xalkori", "克唑替尼"),
        (r"恩沙替尼|ensartinib", "恩沙替尼"),
        (r"卡铂|carboplatin", "卡铂"),
        (r"顺铂|cisplatin", "顺铂"),
        (r"培美曲塞|pemetrexed", "培美曲塞"),
        (r"多西他赛|docetaxel", "多西他赛"),
        (r"紫杉醇|paclitaxel", "紫杉醇"),
        (r"依托泊苷|etoposide", "依托泊苷"),
        (r"吉非替尼|gefitinib|iressa", "吉非替尼"),
        (r"厄洛替尼|erlotinib|tarceva", "厄洛替尼"),
        (r"阿美替尼|aumolertinib", "阿美替尼"),
        (r"埃克替尼|icotinib", "埃克替尼"),
        (r"贝伐珠单抗|bevacizumab|avastin", "贝伐珠单抗"),
        (r"替雷利珠单抗|tislelizumab", "替雷利珠单抗"),
        (r"卡瑞利珠单抗|camrelizumab", "卡瑞利珠单抗"),
        (r"舒格利单抗|sugemalimab", "舒格利单抗"),
        (r"特瑞普利单抗|toripalimab", "特瑞普利单抗"),
        (r"洛拉替尼|lorlatinib|lorviqua", "洛拉替尼"),
        (r"布格替尼|brigatinib", "布格替尼"),
        (r"赛沃替尼|savolitinib", "赛沃替尼"),
        (r"普拉替尼|pralsetinib", "普拉替尼"),
        (r"塞尔帕替尼|selpercatinib", "塞尔帕替尼"),
    ]
    for pat, label in drug_patterns:
        if re.search(pat, text, re.IGNORECASE):
            drugs_list.append(label)

    # ── 新增：转移部位 ──
    site_patterns = [
        (r"脑转移|brain\s*metast", "脑转移"),
        (r"骨转移|bone\s*metast", "骨转移"),
        (r"肝转移|liver\s*metast|hepatic\s*metast", "肝转移"),
        (r"肾上腺转移|adrenal\s*metast", "肾上腺转移"),
        (r"胸膜转移|pleural\s*metast|胸膜播散", "胸膜转移"),
    ]
    for pat, label in site_patterns:
        if re.search(pat, text, re.IGNORECASE):
            disease_site_list.append(label)

    # ── 新增：不良反应 ──
    ae_patterns = [
        (r"皮疹|rash|皮肤毒性", "皮疹"),
        (r"腹泻|diarrhea", "腹泻"),
        (r"肺炎|pneumonitis|间质性肺疾病", "肺炎"),
        (r"肝炎|hepatitis|转氨酶升高|ALT.*升高|AST.*升高", "肝炎"),
        (r"甲状腺功能|thyroid|甲减|甲亢", "甲状腺异常"),
        (r"心肌炎|myocarditis", "心肌炎"),
        (r"肾炎|nephritis|肌酐升高", "肾炎"),
        (r"结肠炎|colitis", "结肠炎"),
        (r"骨髓抑制|中性粒细胞减少|白细胞减少|血小板减少", "骨髓抑制"),
    ]
    for pat, label in ae_patterns:
        if re.search(pat, text, re.IGNORECASE):
            adverse_events_list.append(label)

    # ── 新增：临床试验 ──
    trial_patterns = [
        r"ADAURA", r"KEYNOTE", r"IMpower", r"CheckMate",
        r"ALEX", r"FLAURA", r"PACIFIC", r"CROWN",
        r"EVIDENCE", r"ALINA", r"LAURA",
        r"ORIENT", r"CameL", r"RATIONALE",
        r"GEMSTONE", r"CHOICE", r"AENEAS",
    ]
    for trial in trial_patterns:
        if re.search(trial, content):  # 大小写敏感（试验名通常全大写）
            clinical_trials_list.append(trial)

    # ── 证据类型检测（仅用于非指南/共识类文献，rank 5-8）──
    evidence_rank = 0
    evidence_rank_label = ""

    # Rank 5: 临床试验 — Meta分析 / 系统评价 / RCT / III期临床
    if re.search(
        r"meta.analysis|meta分析|荟萃分析|systematic.review|系统评价"
        r"|randomized.controlled|随机对照|RCT|\biii期临床\b|phase.iii|phase 3",
        text,
    ):
        evidence_rank = 5
        evidence_rank_label = "临床试验"

    # Rank 6: 真实世界研究 / 观察性研究 / 队列研究
    elif re.search(
        r"real.world|真实世界|observational|观察性研究|cohort.study|队列研究"
        r"|retrospective|回顾性|prospective|前瞻性|case.control|病例对照",
        text,
    ):
        evidence_rank = 6
        evidence_rank_label = "真实世界/观察性研究"

    # Rank 7: 病例系列 / 个案报告
    elif re.search(
        r"case.series|病例系列|case.report|个案报告|病例报告|个例报道",
        text,
    ):
        evidence_rank = 7
        evidence_rank_label = "病例系列/个案报告"

    # Rank 8: 个人专家意见 / 述评 / 编者按
    elif re.search(
        r"expert.opinion|专家意见|editorial|述评|编者按|personal.view|个人观点",
        text,
    ):
        evidence_rank = 8
        evidence_rank_label = "个人专家意见"

    return {
        # 数组字段（ChromaDB $contains 双路检索用）
        "stages": stages_list,
        "biomarkers": biomarkers_list,
        "lines": lines_list,
        "treatment_types": treatment_types_list,
        "recommendation_grades": recommendation_grades,
        "drugs": drugs_list,
        "disease_site": disease_site_list,
        "adverse_events": adverse_events_list,
        "clinical_trials": clinical_trials_list,
        # 旧版字符串（向下兼容，重建后可删除）
        "stage": ",".join(stages_list),
        "line_of_therapy": ",".join(lines_list),
        "biomarker": ",".join(biomarkers_list),
        "treatment_type": ",".join(treatment_types_list),
        "recommendation_grade": ",".join(recommendation_grades),
        "language": detect_language(content),
        # 证据类型（从内容检测，仅非指南文献使用）
        "content_evidence_rank": evidence_rank,
        "content_evidence_rank_label": evidence_rank_label,
    }


def extract_query_filters(question: str) -> dict:
    """从用户查询中提取检索筛选条件"""
    text = question.lower()
    filters = {}

    # 分期
    if re.search(r"IV期|stage\s*iv|晚期|转移性|metastatic", text):
        filters["stage"] = "IV"
    elif re.search(r"III期|stage\s*iii|局部晚期", text):
        filters["stage"] = "III"
    elif re.search(r"limited.stage|局限期", text):
        filters["stage"] = "limited"
    elif re.search(r"extensive.stage|广泛期", text):
        filters["stage"] = "extensive"

    # 治疗线数
    if re.search(r"一线|first.line", text):
        filters["line"] = "first-line"
    elif re.search(r"二线|second.line|耐药", text):
        filters["line"] = "second-line"
    elif re.search(r"辅助|adjuvant", text):
        filters["line"] = "adjuvant"

    # 靶点
    biomarkers = []
    for bm in ["EGFR", "ALK", "ROS1", "KRAS", "BRAF", "PD-L1", "PD_L1"]:
        if bm.upper() in question.upper():
            biomarkers.append(bm)
    if biomarkers:
        filters["biomarkers"] = biomarkers

    # 来源机构（用户明确指定时过滤）
    orgs = []
    for org_keyword, org_code in [
        ("NCCN", "NCCN"), ("ASCO", "ASCO"), ("ESMO", "ESMO"),
        ("CSCO", "CSCO"), ("SITC", "SITC"),
        ("中华医学会", "ChineseGuideline"), ("卫健委", "ChineseGuideline"),
        ("中国临床指南", "ChineseGuideline"), ("专家共识", "ExpertConsensus"),
    ]:
        if org_keyword.upper() in question.upper():
            orgs.append(org_code)
    if orgs:
        filters["source_orgs"] = list(set(orgs))  # 去重

    if filters:
        logger.info(f"  [查询筛选] {filters}")
    return filters


def build_where_filter(query_filters: dict) -> dict | None:
    """将查询筛选条件转为 ChromaDB where 过滤器
    注意：ChromaDB $contains 仅支持数组字段，不支持字符串子串匹配
    所以用 plural 字段名（stages, biomarkers, lines）对应数组"""
    conditions = []

    if "biomarkers" in query_filters:
        # 任一 biomarker 匹配即可
        bm_conds = [{"biomarkers": {"$contains": bm}} for bm in query_filters["biomarkers"]]
        if len(bm_conds) == 1:
            conditions.append(bm_conds[0])
        else:
            conditions.append({"$or": bm_conds})

    if "stage" in query_filters:
        conditions.append({"stages": {"$contains": query_filters["stage"]}})

    if "line" in query_filters:
        conditions.append({"lines": {"$contains": query_filters["line"]}})

    if "source_orgs" in query_filters:
        orgs = query_filters["source_orgs"]
        if len(orgs) == 1:
            conditions.append({"source_org": orgs[0]})
        else:
            conditions.append({"$or": [{"source_org": o} for o in orgs]})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def _merge_evidence_rank(base_meta: dict, chunk_meta: dict) -> dict:
    """合并证据等级：文件级（来源机构）优先，内容检测兜底"""
    file_rank = base_meta.get("evidence_rank", 0)
    content_rank = chunk_meta.get("content_evidence_rank", 0)
    content_label = chunk_meta.get("content_evidence_rank_label", "")

    if file_rank == 0 and content_rank > 0:
        # 来源机构未知，使用内容检测结果
        chunk_meta["evidence_rank"] = content_rank
        chunk_meta["evidence_rank_label"] = content_label
    else:
        # 来源机构已知，使用文件级结果
        chunk_meta["evidence_rank"] = file_rank
        chunk_meta["evidence_rank_label"] = base_meta.get("evidence_rank_label", "")

    # 清理中间字段，不存入 ChromaDB
    chunk_meta.pop("content_evidence_rank", None)
    chunk_meta.pop("content_evidence_rank_label", None)
    return chunk_meta


def _resolve_evidence_rank(meta: dict) -> int:
    """从已有元数据实时推算 evidence_rank（兼容新旧索引，无需重建）"""
    # 优先使用已存储的 evidence_rank（新索引）
    stored_rank = meta.get("evidence_rank", 0)
    if stored_rank and stored_rank > 0:
        return stored_rank

    # 回退：从 source_org + doc_type 推算
    source_org = meta.get("source_org", "unknown")
    doc_type = meta.get("doc_type", "guideline")

    rank_info = ORG_EVIDENCE_RANK.get(source_org, (0, ""))
    rank = rank_info[0]

    # 共识类降一级
    if doc_type == "consensus":
        if rank == 1:
            rank = 3
        elif rank == 2:
            rank = 4

    # 如果仍是 0，尝试从内容检测（chunk 中已有 content_evidence_rank 则使用）
    if rank == 0:
        rank = meta.get("content_evidence_rank", 0)

    return rank if rank > 0 else 0


def evidence_weight(rank: int) -> float:
    """证据等级权重：rank 越小（等级越高）权重越大"""
    return EVIDENCE_WEIGHTS.get(rank, EVIDENCE_WEIGHTS[0])


def html_table_to_markdown(html_text: str) -> str:
    """将 HTML <table> 转为 Markdown 表格，提高可读性"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_text, "html.parser")
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        # 收集所有行
        matrix = []
        col_count = 0
        for row in rows:
            cells = []
            for cell in row.find_all(["td", "th"]):
                text = cell.get_text(strip=True)
                colspan = int(cell.get("colspan", 1))
                rowspan = int(cell.get("rowspan", 1))
                cells.append({"text": text, "colspan": colspan, "rowspan": rowspan})
            matrix.append(cells)
            col_count = max(col_count, sum(c.get("colspan", 1) for c in cells))

        # 展开 rowspan/colspan → 规整矩阵
        grid = [[""] * col_count for _ in range(len(rows))]
        occupied = [[False] * col_count for _ in range(len(rows))]

        for ri, row_cells in enumerate(matrix):
            ci = 0
            for cell in row_cells:
                while ci < col_count and occupied[ri][ci]:
                    ci += 1
                if ci >= col_count:
                    break
                for dr in range(cell["rowspan"]):
                    for dc in range(cell["colspan"]):
                        if ri + dr < len(rows) and ci + dc < col_count:
                            grid[ri + dr][ci + dc] = cell["text"]
                            occupied[ri + dr][ci + dc] = True
                ci += cell["colspan"]

        # 生成 Markdown 表格
        md_lines = []
        for ri, row in enumerate(grid):
            md_lines.append("| " + " | ".join(row) + " |")
            if ri == 0:  # 表头分隔行
                md_lines.append("|" + "|".join(["------"] * col_count) + "|")

        # 替换原始 HTML table
        table.replace_with("\n\n" + "\n".join(md_lines) + "\n\n")

    return str(soup)


def _build_chunk(h1_title: str, section_title: str, body: str,
                 base_meta: dict, chunk_idx: int) -> dict:
    """构建单个 chunk，并补齐块级 metadata。"""
    chunk_text = f"# {h1_title}\n\n{section_title}\n\n{body}".strip()
    if "<table" in chunk_text:
        chunk_text = html_table_to_markdown(chunk_text)
    chunk_meta = extract_chunk_metadata(chunk_text)
    chunk_meta = _merge_evidence_rank(base_meta, chunk_meta)
    return {
        **base_meta,
        **chunk_meta,
        "section_title": f"{h1_title} > {section_title}" if h1_title else section_title,
        "content": chunk_text,
        "chunk_index": chunk_idx,
    }


def _split_oversized_paragraph(para: str, max_tokens: int | None = None) -> list[str]:
    """把 OCR 生成的超长单段/表格行切小，避免异常大 chunk 破坏 embedding 或 HNSW。"""
    max_tokens = max_tokens or max(320, MAX_CHUNK_TOKENS - 80)
    para = para.strip()
    if not para:
        return []
    if estimate_tokens(para) <= max_tokens:
        return [para]

    pieces = []
    lines = [line.strip() for line in para.splitlines() if line.strip()]
    source_parts = lines if len(lines) > 1 else re.split(r"(?<=[。；;.!?])\s+", para)
    current = ""

    for part in source_parts:
        part = part.strip()
        if not part:
            continue

        if estimate_tokens(part) > max_tokens:
            if current.strip():
                pieces.append(current.strip())
                current = ""
            # 兜底按字符切，宁可多几个 chunk，也不要再产生 6 万 token 级别的异常块。
            char_step = 900 if len(re.findall(r"[\u4e00-\u9fff]", part)) else 1600
            pieces.extend(part[i:i + char_step].strip() for i in range(0, len(part), char_step))
            continue

        candidate = f"{current}\n{part}".strip() if current else part
        if current and estimate_tokens(candidate) > max_tokens:
            pieces.append(current.strip())
            current = part
        else:
            current = candidate

    if current.strip():
        pieces.append(current.strip())

    return [p for p in pieces if p]


def chunk_markdown(content: str, base_meta: dict) -> list[dict]:
    """
    按 H2/H3 标题切分（每个 Recommendation/Section 独立一个 chunk）
    - 跳过 REFERENCES、DISCLAIMER 等非内容章节
    - 每个 chunk 包含 H1 大标题 + H2 小标题 + 正文
    - H1 到首个 H2/H3 之间的 preamble 单独入库，避免摘要/总则丢失
    - 如果 H2 正文超过 500 token，按段落再切
    """
    content = normalize_ocr_text(content)
    chunks = []

    # 先提取 H1 标题（作为全局上下文）
    h1_match = re.search(r"^# (.+)$", content, re.MULTILINE)
    h1_title = h1_match.group(1).strip() if h1_match else ""

    # 按 H2/H3 切分，避免把 H1 当成普通 section
    h2_pattern = re.compile(r"^(#{2,3}\s+.+)$", re.MULTILINE)
    parts = h2_pattern.split(content)

    # parts: [ preamble, h2_title1, body1, h2_title2, body2, ... ]
    i = 0
    preamble = parts[0].strip() if parts else ""
    preamble = re.sub(r"^# .+\n?", "", preamble, count=1, flags=re.MULTILINE).strip()
    chunk_idx = 0

    if preamble and estimate_tokens(preamble) >= 40:
        for preamble_part in _split_oversized_paragraph(preamble):
            chunks.append(_build_chunk(h1_title, "## 文档摘要 / Preamble", preamble_part, base_meta, chunk_idx))
            chunk_idx += 1

    if len(parts) > 1:
        i = 1

    while i < len(parts) - 1:
        section_title = parts[i].strip()
        body = parts[i + 1].strip()
        i += 2

        if not body:
            continue

        # 跳过非内容章节
        title_lower = section_title.lower().strip("#").strip()
        if any(skip in title_lower for skip in SKIP_SECTIONS):
            continue

        # 如果不超限，直接作为一个 chunk
        chunk_text = f"# {h1_title}\n\n{section_title}\n\n{body}"
        if estimate_tokens(chunk_text) <= MAX_CHUNK_TOKENS:
            chunks.append(_build_chunk(h1_title, section_title, body, base_meta, chunk_idx))
            chunk_idx += 1
            continue

        # 超限 → 按段落切分子块
        paragraphs = []
        for raw_para in re.split(r"\n\n+", body):
            paragraphs.extend(_split_oversized_paragraph(raw_para))
        child_text = ""
        overlap_paragraphs = []
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            # 如果加上这段会超限，先保存当前的
            if child_text and estimate_tokens(child_text + "\n\n" + para) > MAX_CHUNK_TOKENS:
                if child_text.strip():
                    chunks.append(_build_chunk(h1_title, section_title, child_text, base_meta, chunk_idx))
                    chunk_idx += 1
                    child_paras = [p for p in re.split(r"\n\n+", child_text) if p.strip()]
                    overlap_paragraphs = child_paras[-CHUNK_OVERLAP_PARAGRAPHS:]
                child_text = "\n\n".join(overlap_paragraphs + [para]) if overlap_paragraphs else para
            else:
                child_text = child_text + "\n\n" + para if child_text else para

        # 保存最后一段
        if child_text.strip():
            chunks.append(_build_chunk(h1_title, section_title, child_text, base_meta, chunk_idx))
            chunk_idx += 1

    # 最终保险：HTML/Markdown 表格转换后仍可能出现异常大块，返回前再次拆分并重编号。
    final_chunks = []
    for c in chunks:
        content_text = c.get("content", "")
        if estimate_tokens(content_text) > MAX_CHUNK_TOKENS * 2:
            for part in _split_oversized_paragraph(content_text, max_tokens=max(320, MAX_CHUNK_TOKENS - 100)):
                part_meta = extract_chunk_metadata(part)
                part_meta = _merge_evidence_rank(base_meta, part_meta)
                final_chunks.append({
                    **c,
                    **part_meta,
                    "section_title": c.get("section_title", ""),
                    "content": part,
                    "chunk_index": len(final_chunks),
                })
        else:
            c["chunk_index"] = len(final_chunks)
            final_chunks.append(c)

    # 为每个 chunk 标注总块数（用于溯源：第N/总数块）
    total = len(final_chunks)
    for c in final_chunks:
        c["total_chunks"] = total

    return final_chunks


def get_source_document(source_file: str) -> dict | None:
    """根据 source_file 路径读取完整源文档
    返回 {"path": 绝对路径, "content": 全文, "chunks": 总块数, "size": 字节数}
    """
    full_path = GUIDELINES_DIR / source_file
    if not full_path.exists():
        return None
    content = full_path.read_text(encoding="utf-8")
    return {
        "relative_path": source_file,
        "absolute_path": str(full_path),
        "content": content,
        "size_bytes": len(content.encode("utf-8")),
    }


def find_chunk_in_document(source_file: str, chunk_index: int = None,
                           section_title: str = None) -> dict | None:
    """根据 source_file + chunk_index 或 section_title 定位 chunk 在原文中的段落
    返回该 chunk 前后的完整上下文
    """
    doc = get_source_document(source_file)
    if not doc:
        return None

    # 用相同的分块逻辑重新处理，找到对应 chunk
    from pathlib import Path
    rel_path = Path(source_file)
    base_meta = extract_metadata(GUIDELINES_DIR / source_file, str(rel_path))
    chunks = chunk_markdown(doc["content"], base_meta)

    target = None
    for c in chunks:
        if chunk_index is not None and c["chunk_index"] == chunk_index:
            target = c
            break
        if section_title and section_title in c.get("section_title", ""):
            target = c
            break

    if not target and chunks:
        return {"error": "chunk not found", "total_chunks": len(chunks)}

    return {
        "relative_path": source_file,
        "absolute_path": str(GUIDELINES_DIR / source_file),
        "chunk_index": target["chunk_index"] if target else -1,
        "total_chunks": len(chunks),
        "section_title": target.get("section_title", "") if target else "",
        "chunk_content": target["content"] if target else "",
        "previous_chunk": chunks[target["chunk_index"] - 1]["content"][:500]
                          if target and target["chunk_index"] > 0 else None,
        "next_chunk": chunks[target["chunk_index"] + 1]["content"][:500]
                      if target and target["chunk_index"] + 1 < len(chunks) else None,
        "full_document_preview": doc["content"][:2000],
        "full_document_size_bytes": doc["size_bytes"],
    }


def _split_by_h2_or_paragraph(text: str) -> list[str]:
    """按 ## 标题或空行段落切分"""
    # 先按 ## 切
    h2_parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)

    blocks = []
    i = 0
    while i < len(h2_parts) - 1:
        title = h2_parts[i].strip()
        body = h2_parts[i + 1].strip()
        i += 2
        if not body:
            continue

        combined = f"## {title}\n\n{body}"

        # 如果还超限，按段落切
        if estimate_tokens(combined) > MAX_CHUNK_TOKENS:
            paragraphs = re.split(r"\n\n+", body)
            current = f"## {title}\n\n"
            for para in paragraphs:
                if estimate_tokens(current + para) > MAX_CHUNK_TOKENS and current.strip():
                    blocks.append(current)
                    current = f"## {title}（续）\n\n"
                current += para + "\n\n"
            if current.strip():
                blocks.append(current)
        else:
            blocks.append(combined)

    # 没有 ## 标题，按段落切
    if len(h2_parts) <= 1:
        paragraphs = re.split(r"\n\n+", text)
        current = ""
        for para in paragraphs:
            if estimate_tokens(current + para) > MAX_CHUNK_TOKENS and current.strip():
                blocks.append(current)
                current = ""
            current += para + "\n\n"
        if current.strip():
            blocks.append(current)

    return blocks


# ══════════════════════════════════════════════════════
#  Embedding + Reranker
# ══════════════════════════════════════════════════════

# Ollama 请求并发控制（防止 500，限制同时请求数）
_embed_semaphore = None
_MAX_EMBED_CONCURRENT = int(os.getenv("KB_MAX_EMBED_CONCURRENT", str(EMBED_CONCURRENCY)))


def ollama_embed(text: str, model: str = EMBEDDING_MODEL, max_retries: int = 3) -> list[float] | None:
    """调用 Ollama 生成嵌入向量（绕过代理），带重试和并发控制"""
    import httpx
    import threading

    global _embed_semaphore
    if _embed_semaphore is None:
        _embed_semaphore = threading.Semaphore(_MAX_EMBED_CONCURRENT)

    max_retries = int(os.getenv("KB_OLLAMA_MAX_RETRIES", str(max_retries)))

    # 截断过长的文本（bge-m3 最大 8192 token）
    token_est = estimate_tokens(text)
    if token_est > 7000:
        # 按字符粗略截断，保留前面部分
        text = text[:12000]  # ~6000 中文 token

    last_error = None
    _embed_semaphore.acquire()
    try:
        for attempt in range(max_retries):
            try:
                resp = httpx.post(
                    f"{OLLAMA_BASE}/api/embeddings",
                    json={"model": model, "prompt": text},
                    timeout=90.0,
                    proxy=None,
                )
                if resp.status_code == 500:
                    wait = 2 ** attempt
                    logger.warning(f"  [Ollama 500] 重试 {attempt+1}/{max_retries}, 等待 {wait}s...")
                    time.sleep(wait)
                    last_error = f"HTTP 500 (attempt {attempt+1})"
                    continue
                resp.raise_for_status()
                return resp.json()["embedding"]
            except Exception as e:
                wait = 2 ** attempt
                logger.warning(f"  [Ollama error] {e}, 重试 {attempt+1}/{max_retries}, 等待 {wait}s...")
                time.sleep(wait)
                last_error = str(e)

        logger.error(f"  [Ollama] 重试 {max_retries} 次后仍失败: {last_error}")
        return None
    finally:
        _embed_semaphore.release()


# 本地 sentence-transformers bge-m3 回退（无 Ollama 时使用）
_st_local_embed_model = None


def _local_embed(text: str) -> list[float] | None:
    """使用本地 sentence-transformers bge-m3 生成嵌入向量（Ollama 不可用时的回退方案）。"""
    global _st_local_embed_model
    if _st_local_embed_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            # BAAI/bge-m3 与 Ollama bge-m3 为同一模型，向量维度一致（1024）
            _st_local_embed_model = SentenceTransformer("BAAI/bge-m3")
            logger.info("  [本地 Embedding] BAAI/bge-m3 加载成功（sentence-transformers）")
        except Exception as e:
            logger.error("  [本地 Embedding] BAAI/bge-m3 加载失败: %s", e)
            return None
    token_est = estimate_tokens(text)
    if token_est > 7000:
        text = text[:12000]
    try:
        return _st_local_embed_model.encode(text, normalize_embeddings=True).tolist()
    except Exception as e:
        logger.error("  [本地 Embedding] 编码失败: %s", e)
        return None


def _get_embedding(text: str) -> list[float] | None:
    """获取嵌入向量：优先 Ollama，不可用时回退本地 sentence-transformers bge-m3。"""
    result = ollama_embed(text)
    if result is not None:
        return result
    logger.info("  [Embedding] Ollama 不可用，回退本地 sentence-transformers bge-m3")
    return _local_embed(text)


def _get_cross_encoder():
    """懒加载 sentence-transformers CrossEncoder (CPU模式，只用本地缓存)
    优先使用 ModelScope 本地缓存，回退到 HuggingFace 缓存"""
    global _cross_encoder, _cross_encoder_unavailable
    if _cross_encoder_unavailable:
        return None
    if os.getenv("KB_ENABLE_RERANKER", "").lower() not in ("1", "true", "yes"):
        _cross_encoder_unavailable = True
        logger.info("  [Reranker] 未启用 CrossEncoder，使用快速向量召回排序；如需精排可设置 KB_ENABLE_RERANKER=1")
        return None
    if _cross_encoder is None:
        try:
            from sentence_transformers import CrossEncoder
            os.environ["HF_HUB_OFFLINE"] = "1"  # 禁止联网检查
            os.environ["TRANSFORMERS_OFFLINE"] = "1"

            model_path = _find_local_reranker_model()
            if not model_path:
                _cross_encoder_unavailable = True
                logger.warning("  [Reranker] 未找到完整本地模型缓存，降级为向量召回排序")
                return None

            logger.info(f"  加载 CrossEncoder: {model_path} (device=cpu, offline)")
            _cross_encoder = CrossEncoder(model_path, max_length=512, device="cpu")
        except Exception as e:
            _cross_encoder_unavailable = True
            logger.warning("  [Reranker] CrossEncoder 不可用，降级为向量召回排序: %s", e)
            return None
    return _cross_encoder


def _find_local_reranker_model() -> str:
    """查找完整的本地 reranker 模型目录，不触发 HuggingFace 网络探测。"""
    env_path = os.getenv("RERANKER_MODEL_PATH", "").strip()
    candidates = []
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.append(Path("~/.cache/modelscope/hub/models/BAAI/bge-reranker-v2-m3").expanduser())

    hf_root = Path("~/.cache/huggingface/hub/models--BAAI--bge-reranker-v2-m3").expanduser()
    ref_path = hf_root / "refs" / "main"
    if ref_path.exists():
        try:
            commit = ref_path.read_text(encoding="utf-8").strip()
            if commit:
                candidates.append(hf_root / "snapshots" / commit)
        except Exception:
            pass
    snapshots_dir = hf_root / "snapshots"
    if snapshots_dir.exists():
        candidates.extend(sorted((p for p in snapshots_dir.iterdir() if p.is_dir()), reverse=True))

    required = ("config.json", "tokenizer_config.json")
    weight_names = ("model.safetensors", "pytorch_model.bin")
    for path in candidates:
        if not path.is_dir():
            continue
        if not all((path / name).exists() for name in required):
            continue
        if not any((path / name).exists() for name in weight_names):
            continue
        return str(path)
    return ""


def cross_encoder_rerank(query: str, documents: list[str], top_k: int = 5) -> list[dict]:
    """
    使用 sentence-transformers CrossEncoder 对候选文档重排序
    返回: [{"index": int, "score": float}, ...]
    """
    if not documents:
        return []

    encoder = _get_cross_encoder()
    if encoder is None:
        fallback = [{"index": i, "score": 1.0 - (i / max(len(documents), 1))} for i in range(len(documents))]
        return fallback[:top_k]
    # 构建 (query, document) 对
    pairs = [(query, doc) for doc in documents]
    # 批量推理
    try:
        scores = encoder.predict(pairs, show_progress_bar=False)
    except Exception as e:
        logger.warning("  [Reranker] CrossEncoder 推理失败，降级为向量召回排序: %s", e)
        fallback = [{"index": i, "score": 1.0 - (i / max(len(documents), 1))} for i in range(len(documents))]
        return fallback[:top_k]
    # 组合排序
    results = [{"index": i, "score": float(scores[i])} for i in range(len(documents))]
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


# ══════════════════════════════════════════════════════
#  ChromaDB 索引管理
# ══════════════════════════════════════════════════════

def get_chroma_collection():
    """获取或创建 ChromaDB collection"""
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    # 删除旧 collection 再重建（确保 schema 一致）
    try:
        collection = client.get_collection(_get_collection_name())
    except Exception:
        collection = client.create_collection(
            name=_get_collection_name(),
            metadata={"hnsw:space": "cosine"},
        )
    return collection, client


def _record_failed_chunk(rel_path: str, chunk: dict, reason: str) -> None:
    """记录最终未能嵌入的 chunk，便于后续精准补跑或人工检查。"""
    FAILED_CHUNKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "time": datetime.now().isoformat(),
        "source_file": rel_path,
        "chunk_index": chunk.get("chunk_index"),
        "section_title": chunk.get("section_title", ""),
        "tokens": estimate_tokens(chunk.get("content", "")),
        "chars": len(chunk.get("content", "")),
        "reason": reason,
        "preview": (chunk.get("content", "") or "")[:300].replace("\n", " "),
    }
    with open(FAILED_CHUNKS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _clean_chunk_metadata(chunk: dict) -> dict:
    """清理 Chroma metadata，确保类型可序列化。"""
    clean_meta = {}
    for k, v in chunk.items():
        if k == "content":
            continue
        if isinstance(v, (list, tuple)):
            if v:
                clean_meta[k] = list(v)
        elif v is not None:
            clean_meta[k] = str(v) if not isinstance(v, (int, float, bool)) else v
    return clean_meta


def _dedupe_text_variants(texts: list[str]) -> list[str]:
    """按顺序去重文本变体，避免重复触发同样的 Ollama 失败。"""
    seen = set()
    variants = []
    for text in texts:
        text = text.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        variants.append(text)
    return variants


def _failed_chunk_embedding_texts(content: str) -> list[str]:
    """为失败 chunk 生成更稳的嵌入文本，优先避开超长 OCR 表格。"""
    normalized = normalize_ocr_text(content)
    compact = re.sub(r"\s+", " ", normalized or content).strip()
    de_tabled = re.sub(r"[|]{2,}", " ", compact)
    de_tabled = re.sub(r"\s*[|]\s*", " ", de_tabled)
    de_tabled = re.sub(r"-{3,}", " ", de_tabled)
    de_tabled = re.sub(r"\s+", " ", de_tabled).strip()
    variants = []

    variants.append(de_tabled[:1200])
    variants.append(compact[:1200])

    if len(normalized) <= 1200:
        variants.append(normalized)
    if len(content) <= 1200:
        variants.append(content)

    return _dedupe_text_variants(variants)


def _safe_embedding_attempts(rel_path: str, chunk: dict, prefer_compact: bool = False) -> list[tuple[str, str]]:
    """生成多级 embedding 文本，目标是内容异常时仍能给每个 chunk 一个可用向量。"""
    content = chunk["content"]
    attempts: list[tuple[str, str]] = []

    if not prefer_compact:
        attempts.append(("original", content))

    normalized = normalize_ocr_text(content)
    compact = re.sub(r"\s+", " ", normalized or content).strip()
    de_tabled = re.sub(r"[|]{2,}", " ", compact)
    de_tabled = re.sub(r"\s*[|]\s*", " ", de_tabled)
    de_tabled = re.sub(r"-{3,}", " ", de_tabled)
    de_tabled = re.sub(r"\s+", " ", de_tabled).strip()

    attempts.extend([
        ("normalized", normalized),
        ("compact", compact[:6000]),
        ("detabled_1200", de_tabled[:1200]),
        ("detabled_600", de_tabled[:600]),
        ("detabled_300", de_tabled[:300]),
        (
            "section_summary",
            " ".join([
                str(chunk.get("title", "")),
                str(chunk.get("section_title", "")),
                str(chunk.get("source_org", "")),
                str(chunk.get("year", "")),
                rel_path,
            ]),
        ),
    ])

    deduped_attempts = []
    seen_texts = set()
    for mode, text in attempts:
        text = text.strip()
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)
        deduped_attempts.append((mode, text))
    return deduped_attempts


_page_mapping_cache: dict | None = None


def _get_page_mapping() -> dict:
    """懒加载 page_mapping.json（chunk_id → 页码）。"""
    global _page_mapping_cache
    if _page_mapping_cache is None:
        if PAGE_MAPPING_PATH.exists():
            _page_mapping_cache = json.loads(PAGE_MAPPING_PATH.read_text(encoding="utf-8"))
            logger.info(f"Loaded page mapping: {len(_page_mapping_cache)} entries")
        else:
            _page_mapping_cache = {}
            logger.warning(f"Page mapping not found: {PAGE_MAPPING_PATH}")
    return _page_mapping_cache


def _embed_chunk_record(
    rel_path: str,
    chunk: dict,
    allow_fallback: bool = True,
    prefer_compact: bool = False,
) -> dict | None:
    """将 chunk 嵌入并整理为可写入 Chroma 的记录。"""
    embedding = None
    embedding_text_mode = ""

    attempts = _safe_embedding_attempts(rel_path, chunk, prefer_compact=prefer_compact)
    if not allow_fallback:
        attempts = attempts[:1]

    for embedding_text_mode, retry_text in attempts:
        embedding = ollama_embed(retry_text)
        if embedding is not None:
            break

    if embedding is None:
        return None

    meta = _clean_chunk_metadata(chunk)
    meta["embedding_text_mode"] = embedding_text_mode

    # ── 溯源：page + pdf_path ──
    chunk_id = f"{rel_path}::{chunk['chunk_index']}"
    page_map = _get_page_mapping()
    page = page_map.get(chunk_id, "")
    # hybrid_auto 路径兼容：尝试映射到 ocr 路径
    if not page:
        alt_id = chunk_id.replace(chr(92)+"hybrid_auto"+chr(92), chr(92)+"ocr"+chr(92))
        page = page_map.get(alt_id, "")
    meta["page"] = str(page)
    # pdf_path: 从 .md 路径推导对应的 _origin.pdf
    md_path = Path(rel_path)
    pdf_name = md_path.stem.replace(".md", "") + "_origin.pdf"
    pdf_candidate = md_path.parent / pdf_name
    meta["pdf_path"] = str(pdf_candidate) if pdf_candidate else ""

    return {
        "chunk_id": chunk_id,
        "content": chunk["content"],
        "meta": meta,
        "embedding": embedding,
    }


def retry_failed_chunks() -> dict:
    """按失败日志补跑未嵌入的 chunk，并写入当前 Chroma 集合。"""
    if not FAILED_CHUNKS_PATH.exists():
        logger.info(f"未发现失败块日志: {FAILED_CHUNKS_PATH}")
        return {"retried": 0, "recovered": 0, "remaining": 0}

    records = []
    with open(FAILED_CHUNKS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    targets = {(r.get("source_file"), int(r.get("chunk_index"))) for r in records if r.get("source_file") and r.get("chunk_index") is not None}
    if not targets:
        logger.info("失败块日志为空或无有效目标")
        return {"retried": 0, "recovered": 0, "remaining": 0}

    collection, _client = get_chroma_collection()
    recovered = 0
    retried = 0
    remaining = []

    logger.info(f"🔁 开始补跑失败 chunk: {len(targets)} 个")
    for rel_path, chunk_index in sorted(targets):
        try:
            source_path = GUIDELINES_DIR / rel_path
            if not source_path.exists():
                remaining.append({"source_file": rel_path, "chunk_index": chunk_index, "reason": "source_file_missing"})
                continue

            content = source_path.read_text(encoding="utf-8")
            base_meta = extract_metadata(source_path, rel_path)
            base_meta["file_hash"] = compute_file_hash(source_path)
            chunks = chunk_markdown(content, base_meta)
            chunk = next((c for c in chunks if c.get("chunk_index") == chunk_index), None)
            if chunk is None:
                remaining.append({"source_file": rel_path, "chunk_index": chunk_index, "reason": "chunk_not_found_after_rechunk"})
                continue

            retried += 1
            result = _embed_chunk_record(rel_path, chunk, allow_fallback=True, prefer_compact=True)
            if result is None:
                remaining.append({"source_file": rel_path, "chunk_index": chunk_index, "reason": "embedding_failed_after_retry_failed_command"})
                continue

            collection.upsert(
                ids=[result["chunk_id"]],
                documents=[result["content"]],
                metadatas=[result["meta"]],
                embeddings=[result["embedding"]],
            )
            recovered += 1
            logger.info(f"  ✓ 补回 {rel_path}::{chunk_index}")
        except Exception as exc:
            remaining.append({"source_file": rel_path, "chunk_index": chunk_index, "reason": str(exc)})
            logger.error(f"  ✗ 补跑失败 {rel_path}::{chunk_index}: {exc}")

    remaining_path = FAILED_CHUNKS_PATH.with_name(FAILED_CHUNKS_PATH.stem + "_remaining.jsonl")
    with open(remaining_path, "w", encoding="utf-8") as f:
        for item in remaining:
            f.write(json.dumps({**item, "time": datetime.now().isoformat()}, ensure_ascii=False) + "\n")

    logger.info(f"✅ 失败块补跑完成: 尝试 {retried}, 恢复 {recovered}, 仍失败 {len(remaining)}")
    logger.info(f"   剩余失败日志: {remaining_path}")
    return {"retried": retried, "recovered": recovered, "remaining": len(remaining)}


def _source_has_indexed_chunks(collection, rel_path: str) -> bool:
    """检查当前 Chroma 集合中是否已有某个源文件的 chunk。"""
    try:
        result = collection.get(where={"source_file": rel_path}, limit=1, include=["metadatas"])
    except TypeError:
        result = collection.get(where={"source_file": rel_path}, include=["metadatas"])
    except Exception as exc:
        logger.warning(f"  检查已有索引失败，将按缺失处理: {rel_path}: {exc}")
        return False
    return bool(result.get("ids"))


def resume_missing_index(core_only: bool = False) -> dict:
    """从当前 Chroma 集合中缺失的 source_file 续跑，不清空已有索引。"""
    logger.info("🔁 开始按缺失文档续跑索引...")
    start = time.time()

    md_files = []
    for f in GUIDELINES_DIR.rglob("*.md"):
        rel = str(f.relative_to(GUIDELINES_DIR))
        if "chroma_db" in rel or "README" in rel:
            continue
        if core_only and not is_core_index_document(rel):
            continue
        md_files.append((f, rel))

    logger.info(f"  扫描到 {len(md_files)} 个 .md 文件")

    collection, _client = get_chroma_collection()
    meta = _load_meta()
    updated_hashes = {}

    processed_files = 0
    skipped_files = 0
    failed_files = 0
    total_chunks = 0

    for file_path, rel_path in md_files:
        file_hash = compute_file_hash(file_path)
        if _source_has_indexed_chunks(collection, rel_path):
            skipped_files += 1
            updated_hashes[rel_path] = file_hash
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
            if not content.strip():
                continue

            base_meta = extract_metadata(file_path, rel_path)
            base_meta["file_hash"] = file_hash
            chunks = chunk_markdown(content, base_meta)

            batch_ids = []
            batch_docs = []
            batch_metas = []
            batch_embeds = []
            skipped_chunks = 0
            failed_chunks = []

            def _embed_one(chunk):
                return _embed_chunk_record(rel_path, chunk, allow_fallback=True)

            with ThreadPoolExecutor(max_workers=EMBED_CONCURRENCY) as executor:
                futures = {executor.submit(_embed_one, c): c for c in chunks}
                for future in as_completed(futures):
                    original_chunk = futures[future]
                    result = future.result()
                    if result is None:
                        skipped_chunks += 1
                        failed_chunks.append(original_chunk)
                        continue
                    batch_ids.append(result["chunk_id"])
                    batch_docs.append(result["content"])
                    batch_metas.append(result["meta"])
                    batch_embeds.append(result["embedding"])
                    total_chunks += 1

            recovered_chunks = 0
            if failed_chunks:
                logger.info(f"  重试失败 chunk: {len(failed_chunks)}")
                time.sleep(2)
                for failed_chunk in failed_chunks:
                    result = _embed_one(failed_chunk)
                    if result is None:
                        _record_failed_chunk(rel_path, failed_chunk, "embedding_failed_after_resume_retry")
                        continue
                    batch_ids.append(result["chunk_id"])
                    batch_docs.append(result["content"])
                    batch_metas.append(result["meta"])
                    batch_embeds.append(result["embedding"])
                    total_chunks += 1
                    recovered_chunks += 1
                skipped_chunks -= recovered_chunks

            if batch_ids:
                collection.upsert(
                    ids=batch_ids,
                    documents=batch_docs,
                    metadatas=batch_metas,
                    embeddings=batch_embeds,
                )

            processed_files += 1
            updated_hashes[rel_path] = file_hash
            try:
                indexed_chunks = collection.count()
            except Exception:
                indexed_chunks = total_chunks
            meta["last_build"] = datetime.now().isoformat()
            meta["total_documents"] = len(updated_hashes)
            meta["total_chunks"] = indexed_chunks
            meta["file_hashes"] = updated_hashes
            _save_meta(meta)

            status = f"✓ {rel_path} → {len(batch_ids)} 块"
            if skipped_chunks > 0:
                status += f" (重试恢复 {recovered_chunks} 块, 跳过 {skipped_chunks} 块)"
            elif recovered_chunks > 0:
                status += f" (重试恢复 {recovered_chunks} 块)"
            logger.info(status)

        except Exception as e:
            failed_files += 1
            logger.error(f"  ✗ {rel_path}: {e}")

    try:
        indexed_chunks = collection.count()
    except Exception:
        indexed_chunks = total_chunks
    meta["last_build"] = datetime.now().isoformat()
    meta["total_documents"] = len(updated_hashes)
    meta["total_chunks"] = indexed_chunks
    meta["file_hashes"] = updated_hashes
    _save_meta(meta)

    elapsed = time.time() - start
    logger.info(
        f"\n✅ 续跑完成: {processed_files} 文件处理, {skipped_files} 已有索引跳过, "
        f"{failed_files} 失败, 本次新增 {total_chunks} 块, 当前索引 {indexed_chunks} 块, 耗时 {elapsed:.1f}s"
    )
    logger.info(f"   ChromaDB: {CHROMA_DIR}")
    return {"files": processed_files, "chunks": indexed_chunks, "time": elapsed, "failed": failed_files}


def build_index(full: bool = False, core_only: bool = False):
    """构建或重建索引"""
    import chromadb

    logger.info("🔨 开始构建索引...")
    start = time.time()

    # 扫描所有 .md 文件，优先 hybrid_auto，跳过对应旧 ocr
    md_files = []
    hybrid_dirs = set()  # 有 hybrid_auto 的目录
    for f in GUIDELINES_DIR.rglob("*.md"):
        rel = str(f.relative_to(GUIDELINES_DIR))
        if "chroma_db" in rel or "README" in rel:
            continue
        if "/hybrid_auto/" in rel:
            hybrid_dirs.add(rel.replace("/hybrid_auto/", "/ocr/").rsplit("/", 1)[0])
        md_files.append((f, rel))
    # 过滤：如果 hybrid_auto 存在，跳过对应的 ocr
    filtered = []
    for f, rel in md_files:
        if "/ocr/" in rel:
            ocr_dir = rel.rsplit("/", 1)[0]
            if ocr_dir in hybrid_dirs:
                continue  # hybrid_auto 已存在，跳过旧 ocr
        # 规范化路径：hybrid_auto → ocr（保持 page_mapping 兼容）
        store_rel = rel.replace("/hybrid_auto/", "/ocr/").replace(chr(92)+"hybrid_auto"+chr(92), chr(92)+"ocr"+chr(92))
        filtered.append((f, store_rel))
    md_files = filtered

    if core_only:
        md_files = [(f, rel) for f, rel in md_files if is_core_index_document(rel)]
        logger.info("  核心索引模式：仅构建 7 case 高相关文档")

    logger.info(f"  扫描到 {len(md_files)} 个 .md 文件")

    if full:
        # 全量：清空旧索引
        try:
            client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            client.delete_collection(_get_collection_name())
            logger.info("  已清空旧索引")
        except Exception:
            pass
        if FAILED_CHUNKS_PATH.exists():
            FAILED_CHUNKS_PATH.unlink()

    collection, client = get_chroma_collection()

    # 加载已有哈希（增量用）
    meta = _load_meta()
    existing_hashes = {} if full else meta.get("file_hashes", {})
    updated_hashes = dict(existing_hashes)

    total_chunks = 0
    processed_files = 0
    skipped_files = 0
    failed_files = 0

    for file_path, rel_path in md_files:
        file_hash = compute_file_hash(file_path)

        # 增量模式：跳过未修改的文件
        if not full and rel_path in existing_hashes and existing_hashes[rel_path] == file_hash:
            skipped_files += 1
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
            if not content.strip():
                continue

            base_meta = extract_metadata(file_path, rel_path)
            base_meta["file_hash"] = file_hash

            chunks = chunk_markdown(content, base_meta)

            # 增量更新时先删除该文件旧 chunk，避免重分块后残留孤儿块
            if not full:
                try:
                    collection.delete(where={"source_file": rel_path})
                    logger.info(f"  已删除旧索引: {rel_path}")
                except Exception as delete_exc:
                    logger.warning(f"  删除旧索引失败，将继续 upsert: {delete_exc}")

            # 批量嵌入 + 写入
            batch_ids = []
            batch_docs = []
            batch_metas = []
            batch_embeds = []
            skipped_chunks = 0
            failed_chunks = []

            # 并发嵌入：用线程池并行调用 Ollama，提高 GPU 利用率
            def _embed_one(chunk):
                return _embed_chunk_record(rel_path, chunk, allow_fallback=True)

            with ThreadPoolExecutor(max_workers=EMBED_CONCURRENCY) as executor:
                futures = {executor.submit(_embed_one, c): c for c in chunks}
                for future in as_completed(futures):
                    original_chunk = futures[future]
                    result = future.result()
                    if result is None:
                        skipped_chunks += 1
                        failed_chunks.append(original_chunk)
                        continue
                    batch_ids.append(result["chunk_id"])
                    batch_docs.append(result["content"])
                    batch_metas.append(result["meta"])
                    batch_embeds.append(result["embedding"])
                    total_chunks += 1

            # 对瞬时失败的 chunk 做低并发补偿重试，降低 Ollama 500 导致的漏索引。
            recovered_chunks = 0
            if failed_chunks:
                logger.info(f"  重试失败 chunk: {len(failed_chunks)}")
                time.sleep(2)
                for failed_chunk in failed_chunks:
                    result = _embed_one(failed_chunk)
                    if result is None:
                        _record_failed_chunk(rel_path, failed_chunk, "embedding_failed_after_parallel_and_recovery_retry")
                        continue
                    batch_ids.append(result["chunk_id"])
                    batch_docs.append(result["content"])
                    batch_metas.append(result["meta"])
                    batch_embeds.append(result["embedding"])
                    total_chunks += 1
                    recovered_chunks += 1
                skipped_chunks -= recovered_chunks

            # 写入 ChromaDB
            if batch_ids:
                collection.upsert(
                    ids=batch_ids,
                    documents=batch_docs,
                    metadatas=batch_metas,
                    embeddings=batch_embeds,
                )

            processed_files += 1
            updated_hashes[rel_path] = file_hash
            status = f"✓ {rel_path} → {len(batch_ids)} 块"
            if skipped_chunks > 0:
                status += f" (重试恢复 {recovered_chunks} 块, 跳过 {skipped_chunks} 块)"
            elif recovered_chunks > 0:
                status += f" (重试恢复 {recovered_chunks} 块)"
            logger.info(status)

        except Exception as e:
            failed_files += 1
            logger.error(f"  ✗ {rel_path}: {e}")

    # 保存元数据
    try:
        indexed_chunks = collection.count()
    except Exception:
        indexed_chunks = total_chunks
    meta["last_build"] = datetime.now().isoformat()
    meta["total_documents"] = len(updated_hashes)
    meta["total_chunks"] = indexed_chunks
    meta["file_hashes"] = updated_hashes
    _save_meta(meta)

    elapsed = time.time() - start
    logger.info(
        f"\n✅ 构建完成: {processed_files} 文件处理, {skipped_files} 跳过, "
        f"{failed_files} 失败, 本次新增/更新 {total_chunks} 块, 当前索引 {indexed_chunks} 块, 耗时 {elapsed:.1f}s"
    )
    logger.info(f"   ChromaDB: {CHROMA_DIR}")
    return {"files": processed_files, "chunks": indexed_chunks, "time": elapsed, "failed": failed_files}


def update_index():
    """增量更新索引"""
    return build_index(full=False)


# ══════════════════════════════════════════════════════
#  查询扩展 + 混合检索 + 年份加权
# ══════════════════════════════════════════════════════

# ── 查询翻译（只翻译，不扩展相关疾病）──
# 仅映射精确术语，不加泛化词
EXACT_ZH_EN = {
    "局限期": "limited-stage", "广泛期": "extensive-stage",
    "一线": "first-line", "二线": "second-line", "三线": "third-line",
    "辅助治疗": "adjuvant", "新辅助": "neoadjuvant",
    "耐药": "resistance", "脑转移": "brain metastasis",
}


def expand_query(question: str) -> str:
    """只提取英文术语 + 精确翻译，不扩展相关疾病"""
    import re
    terms = []
    q_lower = question.lower()

    # 精确术语翻译（只翻译明确出现的词）
    for zh, en in EXACT_ZH_EN.items():
        if zh in q_lower:
            terms.append(en)

    # 提取原始查询中的英文术语
    en_terms = re.findall(r'[A-Za-z][A-Za-z0-9\-]+', question)
    terms.extend(en_terms)

    # 去重
    seen = set()
    unique = []
    for t in terms:
        t_upper = t.upper()
        if t_upper not in seen:
            seen.add(t_upper)
            unique.append(t)

    expanded = " ".join(unique)
    logger.info(f"  [查询翻译] '{question}' → '{expanded}'")
    return expanded


def year_weight(year: int) -> float:
    """年份权重：越新越高"""
    if year >= 2024:
        return 1.3
    elif year >= 2023:
        return 1.2
    elif year >= 2021:
        return 1.1
    elif year >= 2019:
        return 1.0
    else:
        return 0.85  # 旧指南降权


def deduplicate_by_series(results: list[dict]) -> list[dict]:
    """同系列文献只保留最新年份版本
    例如：中华医学会肺癌临床诊疗指南 2022/2023/2024/2025 → 只保留 2025
    """
    import re
    series = {}
    for r in results:
        # 从 source_file 提取系列标识：去年份 + 去 .pdf/ocr/ 后缀
        sf = r.get("source_file", "")
        base = re.sub(r'[（(]?20\d{2}[版年）)]?', '', sf)
        key = f"{r['source']}|{base}"
        if key not in series or r['year'] > series[key]['year']:
            series[key] = r
    # 保持原排序
    kept = set(id(v) for v in series.values())
    filtered = [r for r in results if id(r) in kept]
    if len(filtered) < len(results):
        logger.info(f"  [同系列去重] {len(results)} → {len(filtered)} 条")
    return filtered


def _fetch_vector_candidates(collection, query_embedding: list[float],
                             n_results: int, where_filter: dict | None,
                             label: str) -> tuple[list[dict], bool]:
    """从 Chroma 拉取候选；where 为空时不传参，避免 Chroma 空 where 报错。"""
    query_kwargs = {
        "query_embeddings": [query_embedding],
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
    }
    if where_filter:
        query_kwargs["where"] = where_filter

    try:
        vec_results = collection.query(**query_kwargs)
    except Exception as e:
        logger.warning(f"  [{label}] 向量检索失败: {e}")
        return [], True

    candidates = []
    documents = vec_results.get("documents") or [[]]
    metadatas = vec_results.get("metadatas") or [[]]
    distances = vec_results.get("distances") or [[]]
    if documents and documents[0]:
        for doc, meta, dist in zip(documents[0], metadatas[0], distances[0]):
            cid = f"{meta.get('source_file', '')}::{meta.get('chunk_index', 0)}"
            candidates.append({
                "chunk_id": cid,
                "content": doc,
                "metadata": meta,
                "vector_score": 1 - dist,
                "retrieval_paths": [label],
            })
    return candidates, False


def _merge_candidates(candidate_groups: list[list[dict]]) -> list[dict]:
    """按 chunk_id 合并过滤召回和无过滤召回结果，保留最高向量分。"""
    merged = {}
    for group in candidate_groups:
        for c in group:
            cid = c.get("chunk_id", "")
            if not cid:
                continue
            if cid not in merged or c.get("vector_score", 0) > merged[cid].get("vector_score", 0):
                paths = set(merged.get(cid, {}).get("retrieval_paths", []))
                paths.update(c.get("retrieval_paths", []))
                merged[cid] = {**c, "retrieval_paths": sorted(paths)}
            else:
                paths = set(merged[cid].get("retrieval_paths", []))
                paths.update(c.get("retrieval_paths", []))
                merged[cid]["retrieval_paths"] = sorted(paths)
    results = list(merged.values())
    results.sort(key=lambda x: x.get("vector_score", 0), reverse=True)
    return results


def _combined_search_score(rerank_score: float, vector_score: float,
                           year: int, evidence_rank: int) -> float:
    """轻量融合分数：相关性为主，年份和证据等级只做温和加权。"""
    relevance = rerank_score * 0.78 + vector_score * 0.22
    freshness = year_weight(year)
    evidence = evidence_weight(evidence_rank)
    return relevance * freshness * evidence


def query_knowledge(question: str, top_k: int = 5,
                    where_filter: dict = None,
                    candidate_k: int | None = None,
                    rerank_k: int | None = None,
                    dual_recall: bool = True,
                    trace: dict | None = None) -> list[dict]:
    """
    纯检索引擎：向量检索 + 可选元数据过滤 + bge-reranker 精排 + 轻量融合排序
    不做任何业务逻辑（不解析查询、不去重、不排序、不均衡）

    Args:
        question: 查询文本（已由 Tool 层做双语扩展）
        top_k: 返回结果数
        where_filter: ChromaDB where 条件（已由 Tool 层构建）
        candidate_k: 向量召回候选数
        rerank_k: 进入 CrossEncoder 的候选数
        dual_recall: 有 where_filter 时是否同时补充无过滤召回
        trace: 可选调试字典，写入候选数和召回路径
    """
    import chromadb
    collection, _ = get_chroma_collection()

    query_embedding = _get_embedding(question)
    if query_embedding is None:
        logger.error("  [向量检索] query embedding 生成失败")
        if trace is not None:
            trace.update({"embedding_failed": True})
        return []

    candidate_k = candidate_k or min(max(top_k * 8, 24), 60)
    rerank_k = rerank_k or min(max(top_k * 4, 16), candidate_k)
    candidate_k = max(top_k, candidate_k)
    rerank_k = max(top_k, min(rerank_k, candidate_k))

    filtered_candidates = []
    filtered_failed = False
    if where_filter:
        filtered_candidates, filtered_failed = _fetch_vector_candidates(
            collection, query_embedding, candidate_k, where_filter, "filtered"
        )

    unfiltered_k = candidate_k if not where_filter else min(candidate_k, max(top_k * 5, 50))
    unfiltered_candidates = []
    if not where_filter or dual_recall or filtered_failed or not filtered_candidates:
        unfiltered_candidates, _ = _fetch_vector_candidates(
            collection, query_embedding, unfiltered_k, None, "unfiltered"
        )

    candidates = _merge_candidates([filtered_candidates, unfiltered_candidates])

    logger.info(
        "  [向量检索] filtered=%s unfiltered=%s merged=%s"
        % (len(filtered_candidates), len(unfiltered_candidates), len(candidates))
    )
    if trace is not None:
        trace.update({
            "where_filter": where_filter,
            "candidate_k": candidate_k,
            "rerank_k": rerank_k,
            "filtered_candidates": len(filtered_candidates),
            "unfiltered_candidates": len(unfiltered_candidates),
            "merged_candidates": len(candidates),
            "filtered_failed": filtered_failed,
        })

    if not candidates:
        return []

    # ── bge-reranker 精排 ──
    top_candidates = candidates[:min(rerank_k, len(candidates))]
    docs_for_rerank = [c["content"] for c in top_candidates]
    reranked = cross_encoder_rerank(question, docs_for_rerank, top_k=len(top_candidates))
    if trace is not None:
        trace["rerank_pool"] = len(top_candidates)

    results = []
    for r in reranked:
        c = top_candidates[r["index"]]
        meta = c["metadata"]
        year = meta.get("year", 0)
        evidence_rank = _resolve_evidence_rank(meta)
        rerank_score = r["score"]
        vector_score = c["vector_score"]
        search_score = _combined_search_score(rerank_score, vector_score, year, evidence_rank)
        results.append({
            "content": c["content"],
            "chunk_id": c.get("chunk_id", ""),
            "source": meta.get("source_org", "unknown"),
            "source_org_cn": meta.get("source_org_cn", ""),
            "source_file": meta.get("source_file", ""),
            "year": year,
            "evidence_level": meta.get("evidence_level", 0),
            "evidence_label": meta.get("evidence_label", ""),
            "evidence_rank": evidence_rank,
            "evidence_rank_label": meta.get("evidence_rank_label", ""),
            "section_title": meta.get("section_title", ""),
            "chunk_index": meta.get("chunk_index", 0),
            "total_chunks": meta.get("total_chunks", 0),
            "recommendation_grade": meta.get("recommendation_grade", ""),
            "recommendation_grades": meta.get("recommendation_grades", []),
            "language": meta.get("language", ""),
            "extraction_mode": meta.get("extraction_mode", ""),
            "source_page": get_chunk_page(c.get("chunk_id", "")),
            "rerank_score": rerank_score,
            "vector_score": vector_score,
            "search_score": search_score,
            "year_weight": year_weight(year),
            "evidence_weight": evidence_weight(evidence_rank),
            "retrieval_paths": c.get("retrieval_paths", []),
        })

    results.sort(key=lambda x: x.get("search_score", 0), reverse=True)
    results = results[:top_k]
    if trace is not None:
        trace["returned"] = len(results)
    return results


# ══════════════════════════════════════════════════════
#  状态查看
# ══════════════════════════════════════════════════════

def show_status():
    """显示索引状态"""
    meta = _load_meta()

    # 统计文件
    md_files = list(GUIDELINES_DIR.rglob("*.md"))
    md_files = [f for f in md_files if "chroma_db" not in str(f) and "README" not in str(f)]
    source_available = GUIDELINES_DIR.exists()

    # 统计待更新
    current_hashes = {}
    for f in md_files:
        rel = str(f.relative_to(GUIDELINES_DIR))
        current_hashes[rel] = compute_file_hash(f)

    indexed_hashes = meta.get("file_hashes", {})
    indexed_documents = int(meta.get("total_documents") or len(indexed_hashes) or 0)
    indexed_chunks = int(meta.get("total_chunks") or 0)
    new_files = [r for r in current_hashes if r not in indexed_hashes]
    modified_files = [r for r in current_hashes if r in indexed_hashes and current_hashes[r] != indexed_hashes[r]]

    # ChromaDB 文档数
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        collection = client.get_collection(_get_collection_name())
        db_count = collection.count()
    except Exception:
        db_count = 0

    status = {
        "source_dir": str(GUIDELINES_DIR),
        "source_available": source_available,
        "source_file_count": len(md_files),
        "indexed_documents": indexed_documents,
        "indexed_chunks": indexed_chunks,
        "chroma_chunks": db_count,
        "last_build": meta.get("last_build", "从未构建"),
        "new_files": len(new_files),
        "modified_files": len(modified_files),
        "embedding": f"Ollama {EMBEDDING_MODEL}",
        "reranker": f"sentence-transformers {RERANKER_MODEL}",
        "chroma_dir": str(CHROMA_DIR),
    }

    print(f"\n📊 知识库索引状态")
    if source_available:
        print(f"  源文件数: {len(md_files)}")
    else:
        print(f"  源文件目录: 缺失 ({GUIDELINES_DIR})")
    print(f"  已索引文档: {indexed_documents}")
    print(f"  ChromaDB 块数: {db_count}")
    print(f"  索引块数记录: {indexed_chunks}")
    print(f"  最后构建: {status['last_build']}")
    print(f"  待更新: {len(new_files)} 新增, {len(modified_files)} 修改")
    print(f"  Embedding: Ollama {EMBEDDING_MODEL}")
    print(f"  Reranker: sentence-transformers {RERANKER_MODEL}")
    print(f"  ChromaDB: {CHROMA_DIR}")
    if not source_available and indexed_documents:
        print("  提示: 原始指南源文件未随项目携带；当前可使用已构建 ChromaDB 索引检索，重建/增量更新需恢复 guidelines 目录。")

    if new_files:
        print(f"\n  📄 新增文件:")
        for f in new_files[:5]:
            print(f"    + {f}")
        if len(new_files) > 5:
            print(f"    ... 还有 {len(new_files) - 5} 个")

    if modified_files:
        print(f"\n  📝 修改文件:")
        for f in modified_files[:5]:
            print(f"    ~ {f}")

    return status


# ══════════════════════════════════════════════════════
#  元数据持久化
# ══════════════════════════════════════════════════════

def _load_meta() -> dict:
    if META_PATH.exists():
        with open(META_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_meta(meta: dict):
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print("用法: python kb_manager.py <status|build|build-core|resume-missing|retry-failed|update|query|source> [参数]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "status":
        show_status()

    elif cmd == "build":
        build_index(full=True)

    elif cmd == "build-core":
        build_index(full=True, core_only=True)

    elif cmd == "resume-missing":
        resume_missing_index()

    elif cmd == "retry-failed":
        retry_failed_chunks()

    elif cmd == "update":
        update_index()

    elif cmd == "query":
        if len(sys.argv) < 3:
            print("用法: python kb_manager.py query \"查询内容\" [--top N]")
            sys.exit(1)
        question = sys.argv[2]
        top_k = 5
        if "--top" in sys.argv:
            idx = sys.argv.index("--top")
            top_k = int(sys.argv[idx + 1])

        print(f"\n🔍 检索: \"{question}\" (Top-{top_k})")
        from tool import search_guidelines
        results = search_guidelines(question, top_k=top_k, raw=True)
        for i, r in enumerate(results):
            pos = f" | {r['position']}" if r.get('position') else ""
            page_info = f" | PDF{r['page']}页" if r.get('page') else ""
            print(f"\n  [{i+1}] score={r['score']:.3f} | {r['evidence_label']} | {r['source']} {r['year']}{pos}{page_info}")
            print(f"      章节: {r['section']}")
            print(f"      文件: {r['file']}")
            print(f"      内容: {r['content'][:200]}...")

    elif cmd == "source":
        if len(sys.argv) < 3:
            print("用法: python kb_manager.py source <source_file> [--chunk N]")
            print("       python kb_manager.py source <source_file> --section \"章节名\"")
            sys.exit(1)
        source_file = sys.argv[2]
        chunk_idx = None
        if "--chunk" in sys.argv:
            idx = sys.argv.index("--chunk")
            chunk_idx = int(sys.argv[idx + 1])

        result = find_chunk_in_document(source_file, chunk_index=chunk_idx)
        if not result:
            print(f"❌ 未找到文件: {source_file}")
        elif "error" in result:
            print(f"❌ {result['error']}，该文件共 {result['total_chunks']} 块")
        else:
            print(f"\n📄 源文档")
            print(f"   路径: {result['absolute_path']}")
            print(f"   总块数: {result['total_chunks']}")
            print(f"   当前块: 第 {result['chunk_index']+1} 段")
            print(f"   章节: {result['section_title']}")
            if result.get("previous_chunk"):
                print(f"\n  ⬆ 上一段: {result['previous_chunk'][:300]}...")
            print(f"\n  ▶ 当前内容:\n{result['chunk_content'][:1000]}")
            if result.get("next_chunk"):
                print(f"\n  ⬇ 下一段: {result['next_chunk'][:300]}...")
            print(f"\n  📄 全文开头预览:\n{result['full_document_preview'][:500]}...")

    else:
        print(f"未知命令: {cmd}")
        print("可用命令: status, build, build-core, resume-missing, retry-failed, update, query, source")
        sys.exit(1)


if __name__ == "__main__":
    main()
