"""Shared configuration for the data pipeline.

Keep query definitions and enum mappings here so fetch/build/eval scripts
use one source of truth. Field names follow data/spec/data_contract_v0.1.md.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw" / "openalex"
MANIFEST_DIR = DATA_DIR / "manifests"
PROCESSED_DIR = DATA_DIR / "processed"
SAMPLE_DIR = DATA_DIR / "samples"
EVAL_DIR = DATA_DIR / "eval"
SPEC_DIR = DATA_DIR / "spec"

OPENALEX_API = "https://api.openalex.org/works"
OPENALEX_SELECT = ",".join(
    [
        "id",
        "doi",
        "title",
        "display_name",
        "publication_year",
        "publication_date",
        "language",
        "type",
        "abstract_inverted_index",
        "authorships",
        "primary_location",
        "open_access",
        "topics",
        "keywords",
        "cited_by_count",
        "ids",
    ]
)

# One primary query per subfield for the thin slice. The keyword filters below
# do the precision work; add more queries when scaling to the full 400 records.
SUBFIELD_SPECS = {
    "cathode": {
        "label": "正极材料",
        "tech_field": "cathode_material",
        "queries": [
            "cathode material",
            "lithium iron phosphate cathode",
            "high-voltage cathode",
            "lithium cobalt oxide cathode",
        ],
        "context_keywords": ["battery", "lithium", "li-ion", "sodium", "na-ion", "cell"],
        "topic_keywords": [
            "cathode",
            "positive electrode",
            "ncm",
            "nca",
            "lfp",
            "lithium iron phosphate",
            "high-nickel",
            "ni-rich",
            "cobalt-free",
            "layered oxide",
            "sodium-ion cathode",
        ],
        "exclude_keywords": [
            "fuel cell",
            "solid oxide fuel cell",
            "solar cell",
            "photovoltaic",
            "electrocatalyst",
            "water splitting",
            "microbial fuel cell",
        ],
        "target": 15,
    },
    "anode": {
        "label": "负极材料",
        "tech_field": "anode_material",
        "queries": ["anode material", "silicon anode", "hard carbon anode", "graphite anode"],
        "context_keywords": ["battery", "lithium", "li-ion", "sodium", "na-ion", "cell"],
        "topic_keywords": [
            "anode",
            "negative electrode",
            "silicon anode",
            "silicon-carbon",
            "si-c",
            "siox",
            "graphite",
            "hard carbon",
            "lithium metal",
            "lithium titanate",
            "sodium-ion anode",
        ],
        "exclude_keywords": [
            "fuel cell",
            "solid oxide fuel cell",
            "solar cell",
            "photovoltaic",
            "electrocatalyst",
            "water splitting",
            "microbial fuel cell",
        ],
        "target": 15,
    },
    "electrolyte": {
        "label": "电解质",
        "tech_field": "electrolyte",
        "queries": ["solid electrolyte", "sulfide solid electrolyte", "oxide solid electrolyte"],
        "context_keywords": ["battery", "lithium", "sodium", "cell", "solid-state"],
        "topic_keywords": [
            "solid electrolyte",
            "solid-state electrolyte",
            "sulfide electrolyte",
            "oxide electrolyte",
            "polymer electrolyte",
            "halide electrolyte",
            "ionic conductivity",
            "li6ps5cl",
            "llzo",
            "argyrodite",
            "composite electrolyte",
        ],
        "exclude_keywords": [
            "fuel cell",
            "solid oxide fuel cell",
            "solar cell",
            "photovoltaic",
            "electrocatalyst",
            "water splitting",
            "microbial fuel cell",
        ],
        "target": 15,
    },
    "separator": {
        "label": "隔膜",
        "tech_field": "separator",
        "queries": ["battery separator", "ceramic-coated separator"],
        "context_keywords": ["battery", "lithium", "cell", "lithium-ion"],
        "topic_keywords": [
            "separator",
            "membrane",
            "ceramic coating",
            "ceramic-coated",
            "coated separator",
            "porous membrane",
            "polyethylene",
            "polypropylene",
            "pvdf coating",
            "pmma coating",
        ],
        "exclude_keywords": [
            "fuel cell",
            "solid oxide fuel cell",
            "solar cell",
            "photovoltaic",
            "water splitting",
            "microbial fuel cell",
            "gas separation",
            "water treatment",
        ],
        "target": 15,
    },
    "cell_system": {
        "label": "电芯与系统",
        "tech_field": "cell_system",
        "queries": ["battery thermal management", "battery thermal runaway"],
        "context_keywords": ["battery", "cell", "pack", "lithium-ion"],
        "topic_keywords": [
            "thermal management",
            "thermal runaway",
            "thermal propagation",
            "battery pack",
            "battery module",
            "cell design",
            "battery safety",
            "battery management system",
            "bms",
            "fast charging",
        ],
        "exclude_keywords": [
            "fuel cell",
            "solid oxide fuel cell",
            "solar cell",
            "photovoltaic",
            "water splitting",
            "microbial fuel cell",
        ],
        "target": 15,
    },
    "recycling": {
        "label": "回收与梯次利用",
        "tech_field": "recycling",
        "queries": ["battery recycling", "direct regeneration cathode"],
        "context_keywords": ["battery", "lithium", "spent", "retired", "lithium-ion"],
        "topic_keywords": [
            "recycling",
            "recycle",
            "regeneration",
            "recovery",
            "hydrometallurgy",
            "pyrometallurgy",
            "direct regeneration",
            "second-life",
            "second life",
            "echelon",
            "cascade utilization",
            "black mass",
        ],
        "exclude_keywords": [
            "fuel cell",
            "solid oxide fuel cell",
            "solar cell",
            "photovoltaic",
            "water splitting",
            "microbial fuel cell",
        ],
        "target": 15,
    },
    "flow": {
        "label": "液流电池（辅领域）",
        "tech_field": "flow_battery",
        "queries": ["flow battery", "vanadium redox flow battery"],
        "context_keywords": ["battery", "flow", "redox"],
        "topic_keywords": [
            "flow battery",
            "redox flow",
            "vanadium flow",
            "vrb",
            "all-vanadium",
            "iron-chromium",
            "zinc-based flow",
            "organic flow",
        ],
        "exclude_keywords": [
            "fuel cell",
            "solid oxide fuel cell",
            "solar cell",
            "photovoltaic",
            "water splitting",
            "microbial fuel cell",
        ],
        "target": 5,
    },
    "supercap": {
        "label": "超级电容（辅领域）",
        "tech_field": "supercapacitor",
        "queries": ["supercapacitor", "supercapacitor electrode"],
        "context_keywords": ["supercapacitor", "ultracapacitor", "capacitor", "electrode"],
        "topic_keywords": [
            "supercapacitor",
            "ultracapacitor",
            "electric double-layer",
            "edlc",
            "pseudocapacitor",
            "energy storage",
            "power density",
        ],
        "exclude_keywords": [
            "fuel cell",
            "solid oxide fuel cell",
            "solar cell",
            "photovoltaic",
            "water splitting",
            "microbial fuel cell",
        ],
        "target": 5,
    },
}

TECH_FIELD_TO_QUERY_TAG = {
    spec["tech_field"]: tag for tag, spec in SUBFIELD_SPECS.items()
}

# Optional diversity quotas inside a subfield. Without these, "high-nickel"
# reviews dominate the cathode bucket and "hard carbon" dominates the anode
# bucket, which weakens the evaluation queries. Rules are (keywords, quota).
SUBTHEME_RULES = {
    "cathode": {
        "lfp": (["lfp", "lithium iron phosphate", "lifepo4"], 3),
        "ni_rich": (["ni-rich", "high-nickel", "ncm", "nca", "nickel-rich"], 4),
        "sodium": (["sodium-ion", "na-ion", "sodium ion"], 2),
        "cobalt_free": (["cobalt-free", "cobalt free"], 1),
        "cobaltate": (["lithium cobalt oxide", "licoo2", "cobalt oxide", "licoo₂"], 1),
        "high_voltage": (
            ["high-voltage", "high voltage", "4.5 v", "single-crystal", "single crystal"],
            2,
        ),
    },
    "anode": {
        "hard_carbon": (["hard carbon"], 6),
        "silicon": (["silicon", "si-c", "silicon-carbon", "siox"], 4),
        "graphite": (["graphite"], 2),
    },
}

# 20 retrieval queries for the thin-slice evaluation set. Candidate lists are
# filled by make_eval_templates.py; relevance labels are intentionally blank.
EVAL_QUERIES = [
    {
        "query_id": "q01",
        "query_text": "我们需要硫化物固态电解质，室温离子电导率≥10 mS/cm，能适应卷对卷生产，最好已完成中试。",
        "query_language": "zh",
        "query_type": "zh_business",
        "target_tags": ["electrolyte"],
        "notes": "需求 dem_005 的业务语言版本；重点看电导率、工艺、TRL。",
    },
    {
        "query_id": "q02",
        "query_text": "寻找高镍单晶三元正极材料，克容量≥210 mAh/g，循环1000次容量保持率≥90%。",
        "query_language": "zh",
        "query_type": "zh_business",
        "target_tags": ["cathode"],
        "notes": "需求 dem_001 的业务语言版本。",
    },
    {
        "query_id": "q03",
        "query_text": "硅碳负极首效≥90%，膨胀率≤20%，面向高能量密度动力电池。",
        "query_language": "zh",
        "query_type": "zh_business",
        "target_tags": ["anode"],
        "notes": "需求 dem_003 的业务语言版本。",
    },
    {
        "query_id": "q04",
        "query_text": "陶瓷涂覆隔膜，厚度≤12 μm，150℃热收缩≤3%，用于高安全动力电芯。",
        "query_language": "zh",
        "query_type": "zh_business",
        "target_tags": ["separator"],
        "notes": "需求 dem_007 的业务语言版本。",
    },
    {
        "query_id": "q05",
        "query_text": "动力电池包热失控防护，要求热失控后30分钟不起火不爆炸。",
        "query_language": "zh",
        "query_type": "zh_business",
        "target_tags": ["cell_system"],
        "notes": "需求 dem_009 的业务语言版本。",
    },
    {
        "query_id": "q06",
        "query_text": "退役磷酸铁锂电池直接再生，容量保持率≥95%，成本低于湿法冶金。",
        "query_language": "zh",
        "query_type": "zh_business",
        "target_tags": ["recycling"],
        "notes": "需求 dem_011 的业务语言版本。",
    },
    {
        "query_id": "q07",
        "query_text": "全钒液流电池用电解质和膜材料，目标成本≤1.5元/Wh，循环寿命≥15000次。",
        "query_language": "zh",
        "query_type": "zh_business",
        "target_tags": ["flow"],
        "notes": "需求 dem_014 的业务语言版本。",
    },
    {
        "query_id": "q08",
        "query_text": "超级电容器电极材料，功率密度≥10 kW/kg，循环寿命≥50万次。",
        "query_language": "zh",
        "query_type": "zh_business",
        "target_tags": ["supercap"],
        "notes": "需求 dem_016 的业务语言版本。",
    },
    {
        "query_id": "q09",
        "query_text": "钠离子电池硬碳负极，克容量≥300 mAh/g，首效≥90%。",
        "query_language": "zh",
        "query_type": "zh_business",
        "target_tags": ["anode"],
        "notes": "需求 dem_004 的业务语言版本；钠电与锂电字面相似，注意 hard negative。",
    },
    {
        "query_id": "q10",
        "query_text": "固态电池界面工程，降低堆叠压力至5 MPa以下，兼容锂金属负极。",
        "query_language": "zh",
        "query_type": "zh_business",
        "target_tags": ["electrolyte"],
        "notes": "需求 dem_018 的业务语言版本；跨电解质/负极，主标签为电解质。",
    },
    {
        "query_id": "q11",
        "query_text": "solid-state electrolyte with high ionic conductivity and air stability for sulfide-based all-solid-state batteries",
        "query_language": "en",
        "query_type": "en_academic",
        "target_tags": ["electrolyte"],
        "notes": "英文学术查询；与 q01 语义相近，检验跨语言一致性。",
    },
    {
        "query_id": "q12",
        "query_text": "single-crystal high-nickel layered oxide cathode with long cycle life",
        "query_language": "en",
        "query_type": "en_academic",
        "target_tags": ["cathode"],
        "notes": "英文学术查询；与 q02 语义相近。",
    },
    {
        "query_id": "q13",
        "query_text": "silicon-carbon composite anode with high initial Coulombic efficiency and low expansion",
        "query_language": "en",
        "query_type": "en_academic",
        "target_tags": ["anode"],
        "notes": "英文学术查询；与 q03 语义相近。",
    },
    {
        "query_id": "q14",
        "query_text": "ceramic-coated separator with thermal stability and low thermal shrinkage for lithium-ion batteries",
        "query_language": "en",
        "query_type": "en_academic",
        "target_tags": ["separator"],
        "notes": "英文学术查询；与 q04 语义相近。",
    },
    {
        "query_id": "q15",
        "query_text": "battery thermal runaway propagation prevention at pack level",
        "query_language": "en",
        "query_type": "en_academic",
        "target_tags": ["cell_system"],
        "notes": "英文学术查询；与 q05 语义相近。",
    },
    {
        "query_id": "q16",
        "query_text": "direct regeneration of spent lithium-ion battery cathode materials with high capacity retention",
        "query_language": "en",
        "query_type": "en_academic",
        "target_tags": ["recycling"],
        "notes": "英文学术查询；与 q06 语义相近。",
    },
    {
        "query_id": "q17",
        "query_text": "vanadium redox flow battery electrolyte and membrane with low cost and long cycle life",
        "query_language": "en",
        "query_type": "en_academic",
        "target_tags": ["flow"],
        "notes": "英文学术查询；与 q07 语义相近。",
    },
    {
        "query_id": "q18",
        "query_text": "high-power supercapacitor electrode materials with long cycle life",
        "query_language": "en",
        "query_type": "en_academic",
        "target_tags": ["supercap"],
        "notes": "英文学术查询；与 q08 语义相近。",
    },
    {
        "query_id": "q19",
        "query_text": "有没有能做到400 Wh/kg、循环800次以上的高镍正极+硅碳负极体系？",
        "query_language": "zh",
        "query_type": "cross_lingual",
        "target_tags": ["cathode", "anode"],
        "notes": "跨两个子方向；检验多标签候选与跨语言召回。",
    },
    {
        "query_id": "q20",
        "query_text": "cost-effective sodium-ion battery materials for grid storage",
        "query_language": "en",
        "query_type": "cross_lingual",
        "target_tags": ["anode", "cathode"],
        "notes": "跨正极/负极、应用为电网储能；检验场景约束与字面陷阱。",
    },
]

# Acceptable values for the canonical enums (kept in sync with taxonomy_v0.1.md).
TECH_FIELDS = set(TECH_FIELD_TO_QUERY_TAG.keys())
APPLICATION_SCENARIOS = {
    "ev_power",
    "grid_storage",
    "cni_storage",
    "residential_storage",
    "consumer_electronics",
    "e_tool_two_wheeler",
    "special",
    "recycling_industry",
}
COOPERATION_MODES = {"transfer", "license", "joint_rd", "joint_lab", "tech_service"}
IP_STATUSES = {"granted", "pending", "published", "unknown"}
LANGUAGES = {"en", "zh", "mixed", "unknown"}
WORK_TYPES = {"article", "review", "preprint", "patent", "other"}

TARGET_TOTAL = 100
MIN_ABSTRACT_CHARS = 200
YEAR_FROM = 2020
YEAR_TO = 2026
