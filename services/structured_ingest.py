"""
结构化数据直接入库 — Excel / CSV 无需 LLM 抽取，行列直接映射为实体和关系

规则:
  - 每一行 → 一个核心实体（以第一列或 name/姓名 列为实体名）
  - 其余列 → 作为该实体的属性或关联关系
  - 列名包含 "公司/组织/单位" → BELONGS_TO
  - 列名包含 "技术/技能"   → USES
  - 其余列 → RELATED_TO
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RowEntity:
    name: str
    type: str = "Entity"
    attributes: dict[str, Any] = field(default_factory=dict)
    relations: list[tuple[str, str, str]] = field(default_factory=list)  # (head, relation, tail)


# ── 列名语义映射 ──────────────────────────────────────────

COLUMN_RELATION_MAP: dict[str, str] = {
    "公司": "BELONGS_TO", "单位": "BELONGS_TO", "组织": "BELONGS_TO",
    "企业": "BELONGS_TO", "机构": "BELONGS_TO", "学校": "BELONGS_TO",
    "学院": "BELONGS_TO", "部门": "BELONGS_TO", "院系": "BELONGS_TO",

    "技术": "USES", "技能": "USES", "技术栈": "USES", "擅长": "USES",
    "工具": "USES", "框架": "USES", "语言": "USES", "平台": "USES",

    "城市": "LOCATED_IN", "地点": "LOCATED_IN", "地址": "LOCATED_IN",
    "位置": "LOCATED_IN", "所在地": "LOCATED_IN",
}


def guess_relation(col_name: str) -> str:
    """根据列名猜测关系类型"""
    col_lower = col_name.lower().strip()
    for keyword, rel in COLUMN_RELATION_MAP.items():
        if keyword in col_lower:
            return rel
    return "RELATED_TO"


def find_name_column(headers: list[str]) -> int:
    """找到实体名所在的列（优先 name / 姓名 / 名称）"""
    for i, h in enumerate(headers):
        hl = h.lower().strip()
        if hl in ("name", "姓名", "名称", "名字", "编号", "id", "代码", "学号"):
            return i
    return 0  # 默认第一列


def parse_structured_data(
    headers: list[str],
    rows: list[list[Any]],
    name_col: int | None = None,
) -> list[RowEntity]:
    """
    将表格数据直接转换为实体列表，零 LLM 调用

    headers: 表头
    rows:    数据行（每行是 list）
    """
    if name_col is None:
        name_col = find_name_column(headers)

    entities: list[RowEntity] = []
    seen_names: set[str] = set()

    for row in rows:
        if not row or all(v is None or str(v).strip() == "" for v in row):
            continue

        # 实体名
        raw_name = str(row[name_col]) if name_col < len(row) else ""
        name = raw_name.strip()
        if not name or name.lower() in ("none", "null", "nan", ""):
            continue
        if name in seen_names:
            name = f"{name}_{len(seen_names)}"
        seen_names.add(name)

        entity = RowEntity(name=name)
        for i, h in enumerate(headers):
            if i >= len(row) or i == name_col:
                continue
            value = row[i]
            if value is None or str(value).strip() in ("", "None", "null", "nan"):
                continue

            str_val = str(value).strip()
            entity.attributes[h] = str_val

            # 值可以作为独立实体时，建立关系
            tail = str_val[:80]  # 截断过长的值
            rel = guess_relation(h)
            entity.relations.append((name, rel, tail))

        entities.append(entity)

    return entities
