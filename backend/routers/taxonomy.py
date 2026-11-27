
# ============================================================
# 标签体系与枚举查询 API（S-11 / BE1）
#
# 功能说明：
# 1. 返回技术领域、应用场景、TRL 等完整枚举
# 2. 支持按照 dimension 查询单个枚举维度
# 3. 保留统一的 code、中文 label 和固定展示顺序
# 4. 返回 taxonomy_version，供前端识别版本变化
# 5. 未知维度返回 HTTP 400
# 6. 不修改数据库中的已有标签
#
# 数据依据：data/spec/taxonomy_v0.1.md
# 接口：
#   GET /api/v1/taxonomy
#
# 关联任务：S-11
# ============================================================

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


router = APIRouter(
    prefix="/api/v1",
    tags=["Taxonomy"],
)

TAXONOMY_VERSION = "v0.1"


def values(*pairs):
    return [
        {"code": code, "label": label}
        for code, label in pairs
    ]


def dimension(name, label, kind, applies_to, options):
    return {
        "dimension": name,
        "label": label,
        "type": kind,
        "applies_to": applies_to,
        "values": options,
    }


# 顺序与 v0.1 标签体系及 API 契约一致。
DIMENSIONS = [

    dimension(
        "tech_field",
        "技术领域",
        "enum",
        ["achievement", "demand"],
        values(
            ("cathode_material", "正极材料"),
            ("anode_material", "负极材料"),
            ("electrolyte", "电解质"),
            ("separator", "隔膜"),
            ("cell_system", "电芯与系统"),
            ("recycling", "回收与梯次利用"),
            ("flow_battery", "液流电池"),
            ("supercapacitor", "超级电容器"),
        ),
    ),

    dimension(
        "application_scenario",
        "应用场景",
        "enum",
        ["achievement", "demand"],
        values(
            ("ev_power", "动力电池"),
            ("grid_storage", "电网储能"),
            ("cni_storage", "工商业储能"),
            ("residential_storage", "户用储能"),
            ("consumer_electronics", "消费电子"),
            ("e_tool_two_wheeler", "电动工具/两轮车"),
            ("special", "特种应用"),
            ("recycling_industry", "回收产业"),
        ),
    ),

    dimension(
        "cooperation_mode",
        "合作模式",
        "enum",
        ["achievement", "demand"],
        values(
            ("transfer", "技术转让"),
            ("license", "技术许可"),
            ("joint_rd", "联合研发"),
            ("joint_lab", "共建实验室"),
            ("tech_service", "技术服务/咨询"),
        ),
    ),

    dimension(
        "ip_status",
        "知识产权状态",
        "enum",
        ["achievement"],
        values(
            ("granted", "已授权"),
            ("pending", "申请中"),
            ("published", "已公开"),
            ("unknown", "未知/不适用"),
        ),
    ),

    dimension(
        "region",
        "意向地区",
        "enum",
        ["demand", "enterprise"],
        values(
            ("yangtze_delta", "长三角"),
            ("pearl_river_delta", "珠三角"),
            ("beijing_tianjin_hebei", "京津冀"),
            ("chengdu_chongqing", "成渝"),
            ("other", "其他"),
            ("any", "不限"),
        ),
    ),

    dimension(
        "industry",
        "企业行业",
        "enum",
        ["demand", "enterprise"],
        values(
            ("battery_manufacturing", "电池制造"),
            ("material_manufacturing", "材料制造"),
            ("ev_oem", "整车"),
            ("ess_integrator", "储能系统"),
            ("recycling", "回收"),
            ("other", "其他"),
        ),
    ),

    dimension(
        "enterprise_size",
        "企业规模",
        "enum",
        ["enterprise", "demand"],
        values(
            ("large", "大型"),
            ("medium", "中型"),
            ("small", "小型"),
        ),
    ),

    dimension(
        "status",
        "需求状态",
        "enum",
        ["demand"],
        values(
            ("draft", "草稿"),
            ("active", "生效"),
            ("expired", "已过期"),
            ("closed", "已关闭"),
        ),
    ),

    dimension(
        "language",
        "语言",
        "enum",
        ["achievement"],
        values(
            ("en", "英文"),
            ("zh", "中文"),
            ("mixed", "中英混合"),
            ("unknown", "未知"),
        ),
    ),

    dimension(
        "type",
        "成果类型",
        "enum",
        ["achievement"],
        values(
            ("article", "期刊论文"),
            ("review", "综述"),
            ("preprint", "预印本"),
            ("patent", "专利"),
            ("other", "其他"),
        ),
    ),

    dimension(
        "trl",
        "技术成熟度",
        "ordinal",
        ["achievement", "demand"],
        values(
            ("1", "1 基本原理"),
            ("2", "2 技术概念"),
            ("3", "3 实验室验证"),
            ("4", "4 实验室器件"),
            ("5", "5 相关环境验证/中试"),
            ("6", "6 原型演示"),
            ("7", "7 实际环境演示"),
            ("8", "8 系统定型"),
            ("9", "9 商业运行"),
        ),
    ),
]


# ---------- Response models ----------

class TaxonomyValue(BaseModel):
    code: str
    label: str


class TaxonomyDimension(BaseModel):
    dimension: str
    label: str
    type: Literal["enum", "ordinal"]
    applies_to: list[str]
    values: list[TaxonomyValue]


class TaxonomyData(BaseModel):
    taxonomy_version: str
    dimensions: list[TaxonomyDimension] = Field(
        default_factory=list
    )


class TaxonomyResponse(BaseModel):
    code: Literal[0] = 0
    message: str = "success"
    data: TaxonomyData


# ---------- GET /api/v1/taxonomy ----------

@router.get(
    "/taxonomy",
    response_model=TaxonomyResponse,
    summary="Get taxonomy dimensions and labels",
)
def get_taxonomy(
    dimension: str | None = None,
):
    if dimension is not None:
        selected = [
            item for item in DIMENSIONS
            if item["dimension"] == dimension
        ]

        if not selected:
            raise HTTPException(
                status_code=400,
                detail="Unknown taxonomy dimension",
            )

    else:
        selected = DIMENSIONS

    return {
        "code": 0,
        "message": "success",
        "data": {
            "taxonomy_version": TAXONOMY_VERSION,
            "dimensions": selected,
        },
    }
