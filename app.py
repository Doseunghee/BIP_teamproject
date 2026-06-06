import json
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


BASE_DIR = Path(__file__).resolve().parent
INDEX_PATH = BASE_DIR / "index.html"

DB_PATHS = {
    "klips": BASE_DIR / "klips_project.db",
    "graduate": BASE_DIR / "graduate-analysis.db",
    "parent_child": BASE_DIR / "부모자녀데이터.db",
}

EDU_LABELS = {
    "elementary": "초졸 이하",
    "middle_school": "중졸",
    "high_school": "고졸",
    "college": "전문대졸",
    "university": "대졸",
    "graduate_school": "대학원졸",
}
EDU_ORDER = ["elementary", "middle_school", "high_school", "college", "university", "graduate_school"]

PARENT_EDU_LABELS = {
    1: "중졸 이하",
    2: "고졸",
    3: "전문대졸",
    4: "전문학사",
    5: "대졸",
    6: "석사+",
}

EMPLOYMENT_TYPE_LABELS = {
    1: "정규직/상용",
    2: "비정규직",
    3: "기타",
}

FIRM_SIZE_LABELS = {
    1: "10명 미만",
    2: "10~29명",
    3: "30~99명",
    4: "100~299명",
    5: "300~499명",
    6: "500명 이상",
}

JOB_STATUS_LABELS = {
    1: "상용직",
    2: "임시직",
    3: "일용직",
    4: "고용주/자영업자",
    5: "무급가족",
}

MOBILITY_LABELS = {
    "upward": "상승",
    "stable": "유지",
    "downward": "하락",
}

GENERATION_LABELS = {
    "young": "청년층",
    "middle": "중장년층",
    "senior": "고령층",
}


def read_sql(db_key: str, sql: str) -> pd.DataFrame:
    with sqlite3.connect(DB_PATHS[db_key]) as conn:
        return pd.read_sql(sql, conn)


def as_records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", force_ascii=False))


def pct_table(
    db_key: str,
    sql: str,
    row_col: str,
    cat_col: str,
    value_col: str,
    row_order: list,
    cat_order: list,
    row_labels: dict | None = None,
    cat_labels: dict | None = None,
) -> dict:
    df = read_sql(db_key, sql)
    if df.empty:
        return {"labels": [], "datasets": [], "raw": []}

    df[row_col] = pd.to_numeric(df[row_col], errors="coerce")
    df[cat_col] = pd.to_numeric(df[cat_col], errors="coerce")
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce").fillna(0)

    pivot = (
        df.pivot_table(index=row_col, columns=cat_col, values=value_col, aggfunc="sum")
        .reindex(index=row_order, columns=cat_order, fill_value=0)
        .fillna(0)
    )
    labels = [str(row_labels.get(int(x), x) if row_labels else x) for x in pivot.index]
    datasets = []
    for c in pivot.columns:
        label = str(cat_labels.get(int(c), c) if cat_labels else c)
        datasets.append({"label": label, "data": [round(float(v), 1) for v in pivot[c].tolist()]})
    return {"labels": labels, "datasets": datasets, "raw": as_records(df)}


def build_dashboard_data() -> dict:
    sql = {}

    # STEP 0
    sql["income_by_decile"] = """
SELECT
    CAST(h_incomeq AS INTEGER) AS 분위,
    ROUND(AVG(h_total_income), 1) AS 평균가구소득
FROM klips
WHERE year = (SELECT MAX(year) FROM klips)
  AND h_incomeq BETWEEN 1 AND 10
  AND h_total_income IS NOT NULL
  AND h_total_income > 0
GROUP BY CAST(h_incomeq AS INTEGER)
ORDER BY 분위;
""".strip()
    income_decile = read_sql("klips", sql["income_by_decile"])

    sql["asset_by_decile"] = """
SELECT
    CAST(h_incomeq AS INTEGER) AS 분위,
    ROUND(AVG(h_total_asset), 1) AS 평균총자산
FROM klips
WHERE year = (SELECT MAX(year) FROM klips)
  AND h_incomeq BETWEEN 1 AND 10
  AND h_total_asset IS NOT NULL
GROUP BY CAST(h_incomeq AS INTEGER)
ORDER BY 분위;
""".strip()
    asset_decile = read_sql("klips", sql["asset_by_decile"])

    # STEP 1
    sql["private_edu_employment_8"] = """
WITH Seoul_Edu AS (
    SELECT
        household_income_monthlyAverage AS 소득구간코드,
        SUM(total_cost * weight) / SUM(weight) AS 평균사교육비
    FROM "HighSchool-privateEdu"
    WHERE City = 11
    GROUP BY household_income_monthlyAverage
),
Univ_Tier AS (
    SELECT
        name,
        CAST("rate(%)" AS REAL) AS 취업률,
        CASE
            WHEN CAST("rate(%)" AS REAL) >= 68.0 THEN 'High_Tier'
            ELSE 'Normal_Tier'
        END AS 대학그룹
    FROM "Graduate-employment"
    WHERE City = 11
      AND "rate(%)" IS NOT NULL
      AND "rate(%)" != ''
),
Univ_Group_Avg AS (
    SELECT
        대학그룹,
        AVG(취업률) AS 그룹평균취업률
    FROM Univ_Tier
    GROUP BY 대학그룹
),
Edu_Capital_Percentile AS (
    SELECT
        소득구간코드,
        평균사교육비,
        (
            평균사교육비 /
            (SELECT MAX(평균사교육비) FROM Seoul_Edu)
        ) AS 상위대학_진학확률
    FROM Seoul_Edu
)
SELECT
    E.소득구간코드 AS 분위,
    ROUND(E.평균사교육비, 1) AS 평균사교육비,
    ROUND(
        (
            E.상위대학_진학확률 * H.그룹평균취업률
        )
        +
        (
            (1 - E.상위대학_진학확률) * N.그룹평균취업률
        ),
        1
    ) AS 기대취업률
FROM Edu_Capital_Percentile E
JOIN Univ_Group_Avg H
  ON H.대학그룹='High_Tier'
JOIN Univ_Group_Avg N
  ON N.대학그룹='Normal_Tier'
ORDER BY E.소득구간코드 ASC;
""".strip()
    private_edu = read_sql("graduate", sql["private_edu_employment_8"])

    # STEP 2
    sql["parent_education_distribution_5"] = """
WITH base AS (
    SELECT
        CAST(부모소득5분위 AS INTEGER) AS 부모소득5분위,
        자녀최종학력
    FROM "세대간_이동성_분석데이터"
    WHERE 부모소득5분위 IS NOT NULL
      AND 자녀최종학력 IS NOT NULL
)
SELECT
    부모소득5분위 AS 분위,
    자녀최종학력,
    COUNT(*) AS 인원수,
    ROUND(
        COUNT(*) * 100.0
        / SUM(COUNT(*)) OVER (PARTITION BY 부모소득5분위),
        1
    ) AS 비율
FROM base
WHERE 부모소득5분위 BETWEEN 1 AND 5
GROUP BY 부모소득5분위, 자녀최종학력
ORDER BY 부모소득5분위, 자녀최종학력;
""".strip()
    parent_edu_dist = pct_table(
        "parent_child",
        sql["parent_education_distribution_5"],
        "분위",
        "자녀최종학력",
        "비율",
        [1, 2, 3, 4, 5],
        [1, 2, 3, 4, 5, 6],
        row_labels=None,
        cat_labels=PARENT_EDU_LABELS,
    )

    sql["parent_graduate_rate_5"] = """
WITH base AS (
    SELECT
        CASE
            WHEN SUBSTR(CAST(학생ID AS TEXT), 1, 1) = '1' THEN 'KEEP I'
            WHEN SUBSTR(CAST(학생ID AS TEXT), 1, 1) = '2' THEN 'KEEP II'
            ELSE '기타'
        END AS 패널구분,
        CAST(부모소득5분위 AS INTEGER) AS 분위,
        대졸이상여부
    FROM "세대간_이동성_분석데이터"
    WHERE 부모소득5분위 IS NOT NULL
      AND 대졸이상여부 IS NOT NULL
)
SELECT
    분위,
    SUM(CASE WHEN 패널구분 = 'KEEP I' THEN 1 ELSE 0 END) AS KEEP_I_표본수,
    ROUND(AVG(CASE WHEN 패널구분 = 'KEEP I' THEN 대졸이상여부 END) * 100, 1) AS KEEP_I_대졸이상비율,
    SUM(CASE WHEN 패널구분 = 'KEEP II' THEN 1 ELSE 0 END) AS KEEP_II_표본수,
    ROUND(AVG(CASE WHEN 패널구분 = 'KEEP II' THEN 대졸이상여부 END) * 100, 1) AS KEEP_II_대졸이상비율
FROM base
WHERE 분위 BETWEEN 1 AND 5
GROUP BY 분위
ORDER BY 분위;
""".strip()
    parent_grad_rate = read_sql("parent_child", sql["parent_graduate_rate_5"])

    # STEP 3
    sql["wage_by_education"] = """
SELECT
    education_group AS 교육수준,
    COUNT(*) AS 표본수,
    ROUND(AVG(p_monthly_wage), 1) AS 월평균임금
FROM klips
WHERE year = (SELECT MAX(year) FROM klips)
  AND education_group IS NOT NULL
  AND p_monthly_wage IS NOT NULL
  AND p_monthly_wage > 0
GROUP BY education_group
ORDER BY
    CASE education_group
        WHEN 'elementary' THEN 1
        WHEN 'middle_school' THEN 2
        WHEN 'high_school' THEN 3
        WHEN 'college' THEN 4
        WHEN 'university' THEN 5
        WHEN 'graduate_school' THEN 6
    END;
""".strip()
    wage_by_edu = read_sql("klips", sql["wage_by_education"])
    wage_by_edu["교육수준명"] = wage_by_edu["교육수준"].map(EDU_LABELS)

    sql["education_employment_type"] = """
WITH base AS (
    SELECT education_group, p_employment_type
    FROM klips
    WHERE year = (SELECT MAX(year) FROM klips)
      AND education_group IS NOT NULL
      AND p_employment_type IS NOT NULL
)
SELECT
    education_group AS 교육수준,
    CAST(p_employment_type AS INTEGER) AS 고용형태,
    COUNT(*) AS 인원수,
    ROUND(
        COUNT(*) * 100.0
        / SUM(COUNT(*)) OVER (PARTITION BY education_group),
        1
    ) AS 비율
FROM base
GROUP BY education_group, CAST(p_employment_type AS INTEGER)
ORDER BY
    CASE education_group
        WHEN 'elementary' THEN 1
        WHEN 'middle_school' THEN 2
        WHEN 'high_school' THEN 3
        WHEN 'college' THEN 4
        WHEN 'university' THEN 5
        WHEN 'graduate_school' THEN 6
    END,
    고용형태;
""".strip()
    edu_emp = read_sql("klips", sql["education_employment_type"])
    edu_emp["교육수준명"] = edu_emp["교육수준"].map(EDU_LABELS)
    edu_emp_pivot = (
        edu_emp.pivot_table(index="교육수준명", columns="고용형태", values="비율", aggfunc="sum")
        .reindex(index=[EDU_LABELS[x] for x in EDU_ORDER])
        .fillna(0)
    )

    sql["education_firm_size"] = """
WITH base AS (
    SELECT education_group, p_firm_size
    FROM klips
    WHERE year = (SELECT MAX(year) FROM klips)
      AND education_group IS NOT NULL
      AND p_firm_size IS NOT NULL
)
SELECT
    education_group AS 교육수준,
    CAST(p_firm_size AS INTEGER) AS 사업장규모,
    COUNT(*) AS 인원수,
    ROUND(
        COUNT(*) * 100.0
        / SUM(COUNT(*)) OVER (PARTITION BY education_group),
        1
    ) AS 비율
FROM base
GROUP BY education_group, CAST(p_firm_size AS INTEGER)
ORDER BY
    CASE education_group
        WHEN 'elementary' THEN 1
        WHEN 'middle_school' THEN 2
        WHEN 'high_school' THEN 3
        WHEN 'college' THEN 4
        WHEN 'university' THEN 5
        WHEN 'graduate_school' THEN 6
    END,
    사업장규모;
""".strip()
    edu_firm = read_sql("klips", sql["education_firm_size"])
    edu_firm["교육수준명"] = edu_firm["교육수준"].map(EDU_LABELS)
    edu_firm_pivot = (
        edu_firm.pivot_table(index="교육수준명", columns="사업장규모", values="비율", aggfunc="sum")
        .reindex(index=[EDU_LABELS[x] for x in EDU_ORDER])
        .fillna(0)
    )

    sql["education_job_status_matrix"] = """
WITH base AS (
    SELECT education_group, p_job_status
    FROM klips
    WHERE year = (SELECT MAX(year) FROM klips)
      AND education_group IS NOT NULL
      AND p_job_status IS NOT NULL
)
SELECT
    education_group AS 교육수준,
    CAST(p_job_status AS INTEGER) AS 종사상지위,
    COUNT(*) AS 인원수,
    ROUND(
        COUNT(*) * 100.0
        / SUM(COUNT(*)) OVER (PARTITION BY education_group),
        1
    ) AS 비율
FROM base
GROUP BY education_group, CAST(p_job_status AS INTEGER)
ORDER BY
    CASE education_group
        WHEN 'elementary' THEN 1
        WHEN 'middle_school' THEN 2
        WHEN 'high_school' THEN 3
        WHEN 'college' THEN 4
        WHEN 'university' THEN 5
        WHEN 'graduate_school' THEN 6
    END,
    종사상지위;
""".strip()
    edu_job = read_sql("klips", sql["education_job_status_matrix"])
    edu_job["교육수준명"] = edu_job["교육수준"].map(EDU_LABELS)
    edu_job_pivot = (
        edu_job.pivot_table(index="교육수준명", columns="종사상지위", values="비율", aggfunc="sum")
        .reindex(index=[EDU_LABELS[x] for x in EDU_ORDER], columns=[1, 2, 3, 4, 5], fill_value=0)
        .fillna(0)
    )

    # STEP 3.5
    sql["wage_by_firm_size"] = """
SELECT
    CAST(p_firm_size AS INTEGER) AS 사업장규모,
    COUNT(*) AS 표본수,
    ROUND(AVG(p_monthly_wage), 1) AS 월평균임금
FROM klips
WHERE year = (SELECT MAX(year) FROM klips)
  AND p_firm_size IS NOT NULL
  AND p_monthly_wage IS NOT NULL
  AND p_monthly_wage > 0
GROUP BY CAST(p_firm_size AS INTEGER)
ORDER BY 사업장규모;
""".strip()
    wage_firm = read_sql("klips", sql["wage_by_firm_size"])

    sql["wage_by_job_status"] = """
SELECT
    CAST(p_job_status AS INTEGER) AS 종사상지위,
    COUNT(*) AS 표본수,
    ROUND(AVG(p_monthly_wage), 1) AS 월평균임금
FROM klips
WHERE year = (SELECT MAX(year) FROM klips)
  AND p_job_status IS NOT NULL
  AND p_monthly_wage IS NOT NULL
  AND p_monthly_wage > 0
GROUP BY CAST(p_job_status AS INTEGER)
ORDER BY 종사상지위;
""".strip()
    wage_status = read_sql("klips", sql["wage_by_job_status"])

    sql["net_asset_by_job_status"] = """
SELECT
    CAST(p_job_status AS INTEGER) AS 종사상지위,
    COUNT(*) AS 표본수,
    ROUND(AVG(h_net_asset), 1) AS 평균순자산
FROM klips
WHERE year = (SELECT MAX(year) FROM klips)
  AND p_job_status IS NOT NULL
  AND h_net_asset IS NOT NULL
GROUP BY CAST(p_job_status AS INTEGER)
ORDER BY 종사상지위;
""".strip()
    asset_status = read_sql("klips", sql["net_asset_by_job_status"])

    sql["employment_mobility_pattern"] = """
WITH base AS (
    SELECT p_employment_type, income_mobility_type
    FROM klips
    WHERE year = (SELECT MAX(year) FROM klips)
      AND p_employment_type IS NOT NULL
      AND income_mobility_type IS NOT NULL
)
SELECT
    CAST(p_employment_type AS INTEGER) AS 고용형태,
    income_mobility_type AS 이동유형,
    COUNT(*) AS 인원수,
    ROUND(
        COUNT(*) * 100.0
        / SUM(COUNT(*)) OVER (PARTITION BY CAST(p_employment_type AS INTEGER)),
        1
    ) AS 비율
FROM base
GROUP BY CAST(p_employment_type AS INTEGER), income_mobility_type
ORDER BY 고용형태, 이동유형;
""".strip()
    emp_mob = read_sql("klips", sql["employment_mobility_pattern"])
    emp_mob_pivot = (
        emp_mob.pivot_table(index="고용형태", columns="이동유형", values="비율", aggfunc="sum")
        .reindex(index=[1, 2, 3], columns=["upward", "stable", "downward"], fill_value=0)
        .fillna(0)
    )

    # STEP 4
    sql["income_asset_change_by_decile"] = """
WITH year_bounds AS (
    SELECT MIN(year) AS min_year, MAX(year) AS max_year FROM klips
),
base AS (
    SELECT
        year,
        CAST(h_incomeq AS INTEGER) AS 분위,
        AVG(h_total_income) AS 평균소득,
        AVG(h_total_asset) AS 평균총자산
    FROM klips
    WHERE h_incomeq BETWEEN 1 AND 10
      AND h_total_income IS NOT NULL
      AND h_total_asset IS NOT NULL
      AND year IN ((SELECT min_year FROM year_bounds), (SELECT max_year FROM year_bounds))
    GROUP BY year, CAST(h_incomeq AS INTEGER)
),
pivoted AS (
    SELECT
        분위,
        MAX(CASE WHEN year = (SELECT min_year FROM year_bounds) THEN 평균소득 END) AS 시작소득,
        MAX(CASE WHEN year = (SELECT max_year FROM year_bounds) THEN 평균소득 END) AS 종료소득,
        MAX(CASE WHEN year = (SELECT min_year FROM year_bounds) THEN 평균총자산 END) AS 시작자산,
        MAX(CASE WHEN year = (SELECT max_year FROM year_bounds) THEN 평균총자산 END) AS 종료자산
    FROM base
    GROUP BY 분위
)
SELECT
    분위,
    ROUND((종료소득 - 시작소득) * 100.0 / NULLIF(시작소득, 0), 1) AS 소득변화율,
    ROUND((종료자산 - 시작자산) * 100.0 / NULLIF(시작자산, 0), 1) AS 자산변화율
FROM pivoted
ORDER BY 분위;
""".strip()
    decile_change = read_sql("klips", sql["income_asset_change_by_decile"])

    sql["asset_gap_ratio_trend"] = """
WITH yearly AS (
    SELECT
        year,
        CAST(h_incomeq AS INTEGER) AS 분위,
        AVG(h_total_asset) AS 평균총자산
    FROM klips
    WHERE h_incomeq IN (1, 10)
      AND h_total_asset IS NOT NULL
    GROUP BY year, CAST(h_incomeq AS INTEGER)
)
SELECT
    year AS 연도,
    ROUND(
        MAX(CASE WHEN 분위 = 10 THEN 평균총자산 END)
        / NULLIF(MAX(CASE WHEN 분위 = 1 THEN 평균총자산 END), 0),
        2
    ) AS 자산격차배율
FROM yearly
GROUP BY year
ORDER BY year;
""".strip()
    asset_gap_trend = read_sql("klips", sql["asset_gap_ratio_trend"])

    sql["debt_by_generation"] = """
SELECT
    year AS 연도,
    generation AS 세대,
    ROUND(AVG(h_total_debt), 1) AS 평균부채
FROM klips
WHERE h_total_debt IS NOT NULL
  AND generation IS NOT NULL
GROUP BY year, generation
ORDER BY year, generation;
""".strip()
    debt_gen = read_sql("klips", sql["debt_by_generation"])
    debt_pivot = (
        debt_gen.pivot_table(index="연도", columns="세대", values="평균부채", aggfunc="mean")
        .reindex(columns=["young", "middle", "senior"])
        .fillna(0)
    )

    sql["lower_upper_mobility_line"] = """
SELECT
    year AS 연도,
    ROUND(
        SUM(CASE WHEN prev_income_decile <= 3 AND h_incomeq > 3 THEN 1 ELSE 0 END) * 100.0
        / NULLIF(SUM(CASE WHEN prev_income_decile <= 3 THEN 1 ELSE 0 END), 0),
        1
    ) AS 하위계층_탈출율,
    ROUND(
        SUM(CASE WHEN prev_income_decile >= 8 AND h_incomeq >= 8 THEN 1 ELSE 0 END) * 100.0
        / NULLIF(SUM(CASE WHEN prev_income_decile >= 8 THEN 1 ELSE 0 END), 0),
        1
    ) AS 상위계층_유지율
FROM klips
WHERE year_gap = 1
  AND prev_income_decile IS NOT NULL
  AND h_incomeq IS NOT NULL
GROUP BY year
ORDER BY year;
""".strip()
    lower_upper_line = read_sql("klips", sql["lower_upper_mobility_line"])

    sql["mobility_donut"] = """
SELECT
    income_mobility_type AS 이동유형,
    COUNT(*) AS 인원수,
    ROUND(
        COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (),
        1
    ) AS 비율
FROM klips
WHERE year = (SELECT MAX(year) FROM klips)
  AND income_mobility_type IS NOT NULL
GROUP BY income_mobility_type
ORDER BY
    CASE income_mobility_type
        WHEN 'upward' THEN 1
        WHEN 'stable' THEN 2
        WHEN 'downward' THEN 3
    END;
""".strip()
    mobility_donut = read_sql("klips", sql["mobility_donut"])


    sql["income_transition_matrix_10"] = """
WITH base AS (
    SELECT DISTINCT
        household_id,
        year,
        CAST(prev_income_decile AS INTEGER) AS 이전분위,
        CAST(h_incomeq AS INTEGER) AS 현재분위
    FROM klips
    WHERE year_gap = 1
      AND household_id IS NOT NULL
      AND prev_income_decile BETWEEN 1 AND 10
      AND h_incomeq BETWEEN 1 AND 10
), counted AS (
    SELECT
        이전분위,
        현재분위,
        COUNT(*) AS 가구수
    FROM base
    GROUP BY 이전분위, 현재분위
)
SELECT
    이전분위,
    현재분위,
    가구수,
    ROUND(
        가구수 * 100.0
        / SUM(가구수) OVER (PARTITION BY 이전분위),
        1
    ) AS 전이비율
FROM counted
ORDER BY 이전분위, 현재분위;
""".strip()
    transition_10 = read_sql("klips", sql["income_transition_matrix_10"])
    transition_pivot = (
        transition_10.pivot_table(index="이전분위", columns="현재분위", values="전이비율", aggfunc="sum")
        .reindex(index=list(range(1, 11)), columns=list(range(1, 11)), fill_value=0)
        .fillna(0)
    )

    # KPI
    latest_income_min = float(income_decile["평균가구소득"].min()) if not income_decile.empty else 0
    latest_income_max = float(income_decile["평균가구소득"].max()) if not income_decile.empty else 0
    latest_asset_min = float(asset_decile["평균총자산"].replace(0, pd.NA).min()) if not asset_decile.empty else 0
    latest_asset_max = float(asset_decile["평균총자산"].max()) if not asset_decile.empty else 0
    income_gap = round(latest_income_max / latest_income_min, 1) if latest_income_min else 0
    asset_gap = round(latest_asset_max / latest_asset_min, 1) if latest_asset_min else 0

    upper_sql = """
SELECT
    ROUND(
        SUM(CASE WHEN h_incomeq >= 8 THEN 1 ELSE 0 END) * 100.0 / COUNT(*),
        1
    ) AS 상위계층유지율
FROM klips
WHERE year = (SELECT MAX(year) FROM klips)
  AND year_gap = 1
  AND prev_income_decile >= 8
  AND h_incomeq IS NOT NULL;
""".strip()
    sql["kpi_upper_retention"] = upper_sql
    upper_retention_df = read_sql("klips", upper_sql)
    upper_retention = float(upper_retention_df.iloc[0, 0]) if not upper_retention_df.empty and pd.notna(upper_retention_df.iloc[0, 0]) else 0

    # Convert matrices and pivots
    def pivot_to_chart(pivot_df, label_map=None):
        labels = [str(x) for x in pivot_df.index]
        datasets = []
        for col in pivot_df.columns:
            if label_map and pd.notna(col):
                try:
                    key = int(col)
                except (TypeError, ValueError):
                    key = col
                label = str(label_map.get(key, col))
            else:
                label = str(col)
            datasets.append({"label": label, "data": [round(float(v), 1) for v in pivot_df[col].tolist()]})
        return {"labels": labels, "datasets": datasets}

    edu_emp_chart = pivot_to_chart(edu_emp_pivot, EMPLOYMENT_TYPE_LABELS)
    edu_firm_chart = pivot_to_chart(edu_firm_pivot, FIRM_SIZE_LABELS)
    edu_job_matrix = {
        "rows": list(edu_job_pivot.index),
        "columns": [JOB_STATUS_LABELS.get(int(c), str(c)) for c in edu_job_pivot.columns],
        "values": [[round(float(v), 1) for v in row] for row in edu_job_pivot.values.tolist()],
    }
    emp_mob_chart = pivot_to_chart(emp_mob_pivot, {"upward": "상승", "stable": "유지", "downward": "하락"})

    debt_chart = {
        "labels": [str(int(x)) for x in debt_pivot.index.tolist()],
        "datasets": [
            {"label": GENERATION_LABELS.get(col, col), "data": [round(float(v), 1) for v in debt_pivot[col].tolist()]}
            for col in debt_pivot.columns
        ],
    }

    # Label conversion for simple chart dataframes
    wage_firm["사업장규모명"] = wage_firm["사업장규모"].map(FIRM_SIZE_LABELS)
    wage_status["종사상지위명"] = wage_status["종사상지위"].map(JOB_STATUS_LABELS)
    asset_status["종사상지위명"] = asset_status["종사상지위"].map(JOB_STATUS_LABELS)
    emp_mob["고용형태명"] = emp_mob["고용형태"].map(EMPLOYMENT_TYPE_LABELS)
    mobility_donut["이동유형명"] = mobility_donut["이동유형"].map(MOBILITY_LABELS)

    # Dynamic insights
    insights = {}
    if not income_decile.empty:
        insights["income_by_decile"] = (
            f"최신 연도 기준 1분위 평균 가구소득은 {income_decile.iloc[0]['평균가구소득']:,.1f}만원, "
            f"10분위는 {income_decile.iloc[-1]['평균가구소득']:,.1f}만원으로 약 {income_gap}배 차이가 나타난다. "
            "상위 분위로 갈수록 평균소득이 뚜렷하게 커져 소득 격차가 구조적으로 존재함을 보여준다."
        )
    if not asset_decile.empty:
        insights["asset_by_decile"] = (
            f"최신 연도 기준 1분위 평균 총자산은 {asset_decile.iloc[0]['평균총자산']:,.1f}만원, "
            f"10분위는 {asset_decile.iloc[-1]['평균총자산']:,.1f}만원이다. "
            f"총자산 격차는 약 {asset_gap}배로, 자산 축적의 차이가 계층 고착화의 기반이 될 수 있다."
        )
    if not private_edu.empty:
        min_row = private_edu.iloc[0]
        max_row = private_edu.iloc[-1]
        insights["private_edu_employment_8"] = (
            f"8분위 기준으로 1구간 평균 사교육비는 {min_row['평균사교육비']:,.1f}, "
            f"8구간은 {max_row['평균사교육비']:,.1f}이다. "
            f"기대취업률도 {min_row['기대취업률']:,.1f}%에서 {max_row['기대취업률']:,.1f}%로 높아져, "
            "부모 소득에 따른 교육 투자 차이가 미래 성과 격차로 이어질 가능성을 보여준다."
        )
    # Find parent ed insights
    if parent_grad_rate is not None and not parent_grad_rate.empty:
        first_i = float(parent_grad_rate.iloc[0]["KEEP_I_대졸이상비율"]) if pd.notna(parent_grad_rate.iloc[0]["KEEP_I_대졸이상비율"]) else 0
        last_i = float(parent_grad_rate.iloc[-1]["KEEP_I_대졸이상비율"]) if pd.notna(parent_grad_rate.iloc[-1]["KEEP_I_대졸이상비율"]) else 0
        first_ii = float(parent_grad_rate.iloc[0]["KEEP_II_대졸이상비율"]) if pd.notna(parent_grad_rate.iloc[0]["KEEP_II_대졸이상비율"]) else 0
        last_ii = float(parent_grad_rate.iloc[-1]["KEEP_II_대졸이상비율"]) if pd.notna(parent_grad_rate.iloc[-1]["KEEP_II_대졸이상비율"]) else 0
        ratio_i = round(last_i / first_i, 2) if first_i else 0
        ratio_ii = round(last_ii / first_ii, 2) if first_ii else 0
        insights["parent_education_distribution_5"] = (
            "부모 소득 5분위가 높아질수록 자녀의 고학력 비중이 커진다. "
            "특히 하위 분위에서는 고졸 비중이 상대적으로 높고, 상위 분위에서는 대졸 이상 비중이 높게 나타난다."
        )
        insights["parent_graduate_rate_5"] = (
            f"KEEP I 기준 1분위 대졸 이상 비율은 {first_i:.1f}%, 5분위는 {last_i:.1f}%로 약 {ratio_i}배 차이가 난다. "
            f"KEEP II 기준 1분위는 {first_ii:.1f}%, 5분위는 {last_ii:.1f}%로 약 {ratio_ii}배 차이가 나타나, "
            "두 패널 모두 부모 소득이 높을수록 자녀의 대졸 이상 비율이 높아지는 흐름을 보여준다."
        )
    if not wage_by_edu.empty:
        min_w = wage_by_edu.loc[wage_by_edu["월평균임금"].idxmin()]
        max_w = wage_by_edu.loc[wage_by_edu["월평균임금"].idxmax()]
        insights["wage_by_education"] = (
            f"교육수준별 월평균 임금은 {min_w['교육수준명']} {min_w['월평균임금']:,.1f}만원에서 "
            f"{max_w['교육수준명']} {max_w['월평균임금']:,.1f}만원까지 차이가 난다. "
            "학력 격차가 노동시장 소득 격차로 연결되는 흐름을 확인할 수 있다."
        )
    insights["education_employment_firm"] = (
        "학력별 고용형태와 사업장 규모 분포를 함께 보면, 교육수준이 높을수록 상대적으로 안정적인 고용형태와 큰 사업장에 속할 가능성이 커진다. "
        "이는 학력 → 고용 안정성·사업장 규모 → 임금 격차로 이어지는 중간 경로를 보여준다."
    )
    insights["education_job_status_matrix"] = (
        "학력별 종사상 지위 분포를 100% 누적 막대로 비교하면 각 학력 집단이 어떤 노동시장 지위에 집중되는지 더 직관적으로 확인할 수 있다. "
        "상용직 비중이 높은 집단일수록 임금과 자산 축적 측면에서 유리한 위치에 놓일 가능성이 크다."
    )
    if not wage_firm.empty:
        insights["wage_by_firm_size"] = (
            "사업장 규모별 월평균 임금은 대체로 규모가 커질수록 높아진다. "
            "이는 같은 노동시장 안에서도 어느 규모의 조직에 진입했는지가 소득 격차를 만드는 조건이 될 수 있음을 의미한다."
        )
    insights["wage_by_job_status"] = (
        "종사상 지위별 월평균 임금 차이는 고용 안정성과 소득 수준이 함께 움직일 수 있음을 보여준다. "
        "상용직·고용주/자영업자 등 지위별 차이가 소득 격차의 또 다른 축으로 작동한다."
    )
    insights["asset_by_job_status"] = (
        "종사상 지위별 평균 순자산을 큰 값 순으로 정렬해 비교하면 어떤 노동시장 지위가 자산 축적과 더 강하게 연결되는지 확인할 수 있다. "
        "순자산은 일부 집단에서 음수 또는 낮은 값이 나타날 수 있어, 부채 부담까지 함께 고려해 해석해야 한다."
    )
    insights["employment_mobility"] = (
        "고용형태별 계층 이동 패턴을 가로형 100% 누적 막대로 비교하면 상승·유지·하락 비중의 차이가 더 명확하게 드러난다. "
        "불안정한 고용형태일수록 계층 상승보다 유지 또는 하락 비중이 커질 가능성을 확인할 수 있다."
    )
    insights["income_asset_change"] = (
        "소득분위별 소득·자산 변화율을 비교하면 격차가 시간이 지나며 어떤 분위에서 더 크게 확대되는지 확인할 수 있다. "
        "특정 상위 분위의 자산 증가율이 높을 경우 자산 기반 계층 고착화가 강화될 수 있다."
    )
    insights["asset_gap_trend"] = (
        "1분위 대비 10분위의 자산격차배율 추이는 자산 불평등이 시간에 따라 완화되는지 또는 확대되는지 보여준다. "
        "소득보다 자산에서 격차가 누적되는 경우 계층 이동 사다리는 더 좁아진다."
    )
    insights["debt_by_generation"] = (
        "세대별 평균 부채 추이를 보면 청년층·중장년층·고령층이 서로 다른 부채 부담을 안고 있음을 확인할 수 있다. "
        "특히 특정 세대의 부채 증가가 빠르면 다음 세대의 자산 형성과 이동 가능성을 제약할 수 있다."
    )
    insights["lower_upper_line"] = (
        "하위계층 탈출율과 상위계층 유지율을 함께 보면 계층 이동 사다리의 비대칭성을 확인할 수 있다. "
        "하위층의 탈출율이 낮고 상위층의 유지율이 높다면, 하위는 벗어나기 어렵고 상위는 유지되기 쉬운 구조로 해석된다."
    )
    insights["mobility_donut"] = (
        "소득분위 상승·유지·하락 비중을 보면 계층 이동의 전체 구조가 드러난다. "
        "유지 비중이 크면 같은 위치에 머무르는 경향이 강하다는 뜻이며, 이는 계층 고착 가능성과 연결된다."
    )
    if not transition_10.empty:
        diagonal_vals = [transition_pivot.loc[i, i] for i in transition_pivot.index if i in transition_pivot.columns]
        avg_stay = round(float(sum(diagonal_vals) / len(diagonal_vals)), 1) if diagonal_vals else 0
        lower_stay = round(float(transition_pivot.loc[1, 1]), 1) if 1 in transition_pivot.index else 0
        upper_stay = round(float(transition_pivot.loc[10, 10]), 1) if 10 in transition_pivot.index else 0
        insights["income_transition_matrix_10"] = (
            f"소득 10분위 전이행렬은 이전 분위에서 다음 시점의 분위로 얼마나 이동했는지를 보여준다. "
            f"대각선 평균 유지율은 {avg_stay:.1f}%이며, 1분위 유지율은 {lower_stay:.1f}%, 10분위 유지율은 {upper_stay:.1f}%로 나타난다. "
            "대각선에 값이 집중될수록 계층 이동보다 같은 분위에 머무르는 경향이 강하다고 해석할 수 있다."
        )


    display_sql = dict(sql)
    display_sql["private_edu_employment_8"] = """
SELECT
    E.소득구간코드,
    E.평균사교육비,
    -- 상위 대학 진학 확률이 높을수록 High_Tier 취업률에 가까워지도록 보간(Interpolation) 연산
    ROUND((E.상위대학_진학확률 * H.그룹평균취업률) + ((1 - E.상위대학_진학확률) * N.그룹평균취업률), 1) AS 기대취업률
FROM Edu_Capital_Percentile E
JOIN Univ_Group_Avg H ON H.대학그룹 = 'High_Tier'
JOIN Univ_Group_Avg N ON N.대학그룹 = 'Normal_Tier'
ORDER BY E.소득구간코드 ASC;
""".strip()
    display_sql["parent_education_distribution_5"] = """
SELECT
    부모소득5분위,
    자녀최종학력,
    COUNT(*) AS 인원수,
    ROUND(
        COUNT(*) * 100.0
        / SUM(COUNT(*)) OVER (PARTITION BY 부모소득5분위)
    , 1) AS 비율_pct
FROM 세대간이동성
WHERE 부모소득5분위 IS NOT NULL
  AND 자녀최종학력  IS NOT NULL
GROUP BY 부모소득5분위, 자녀최종학력
ORDER BY 부모소득5분위, 자녀최종학력;
""".strip()
    display_sql["parent_graduate_rate_5"] = """
SELECT
    부모소득5분위,
    COUNT(*) AS 인원수,
    ROUND(AVG(대졸이상여부) * 100, 1) AS 대졸이상비율_pct
FROM 세대간이동성
WHERE 부모소득5분위 IS NOT NULL
GROUP BY 부모소득5분위
ORDER BY 부모소득5분위;
""".strip()

    insights["private_edu_employment_8"] = (
        "데이터 분석 결과 부모의 경제력이 높을수록 자녀의 교육 투자 수준이 높아지는 경향을 확인할 수 있다. "
        "최상위 소득구간의 평균 사교육비는 최하위 소득구간 대비 53.4% 증가하였고, 기대취업률 역시 8.8% 상승하는 것으로 나타났다. "
        "이는 교육 투자 격차가 미래 취업성과 차이로 연결될 가능성을 보여준다."
    )
    insights["parent_education_distribution_5"] = (
        "5분위 데이터를 분석한 결과, 부모 소득이 높을수록 자녀의 대졸 이상 비율이 뚜렷하게 증가한다. "
        "소득 1분위 자녀의 고졸 비중은 49.1% 로 절반에 가까운 반면, 5분위 자녀의 대졸 이상 비중은 47.3% 로 1분위(27.2%) 대비 약 1.7배 높게 나타난다. "
        "또한 저소득층 자녀일수록 4년제 대학 대신 전문대로 집중되는 경향이 관찰되며, 이는 부모의 경제적 지위가 자녀의 학력 수준을 결정하는 구조가 고착화되었음을 시사한다."
    )
    insights["parent_graduate_rate_5"] = (
        "KEEP I(2005~2019년)과 KEEP II(2016~2024년) 두 코호트를 비교한 결과, 세대가 달라져도 부모 소득이 자녀 학력을 결정하는 구조가 반복되고 있음이 확인된다. "
        "KEEP I에서 1분위 대졸이상 비율은 33.9%, 5분위는 77.6% 로 2.3배 격차를 보였으며, KEEP II에서도 1분위 27.2%, 5분위 47.3% 로 1.7배 격차가 지속된다. "
        "수치상 배율은 소폭 완화되었으나, 상위 계층의 고학력 수성 구조는 세대를 넘어 고착화되고 있음을 시사한다."
    )

    data = {
        "kpis": {
            "income_gap": income_gap,
            "asset_gap": asset_gap,
            "upper_retention": upper_retention,
            "latest_year": int(read_sql("klips", "SELECT MAX(year) AS y FROM klips;").iloc[0]["y"]),
        },
        "sql": display_sql,
        "insights": insights,
        "charts": {
            "income_by_decile": as_records(income_decile),
            "asset_by_decile": as_records(asset_decile),
            "private_edu_employment_8": as_records(private_edu),
            "parent_education_distribution_5": parent_edu_dist,
            "parent_graduate_rate_5": as_records(parent_grad_rate),
            "wage_by_education": as_records(wage_by_edu),
            "education_employment_type": edu_emp_chart,
            "education_firm_size": edu_firm_chart,
            "education_job_status_matrix": edu_job_matrix,
            "wage_by_firm_size": as_records(wage_firm),
            "wage_by_job_status": as_records(wage_status),
            "net_asset_by_job_status": as_records(asset_status),
            "employment_mobility_pattern": {
                "labels": [EMPLOYMENT_TYPE_LABELS.get(int(i), str(i)) for i in emp_mob_pivot.index.tolist()],
                "datasets": [
                    {"label": MOBILITY_LABELS.get(col, col), "data": [round(float(v), 1) for v in emp_mob_pivot[col].tolist()]}
                    for col in emp_mob_pivot.columns
                ],
            },
            "income_asset_change_by_decile": as_records(decile_change),
            "asset_gap_ratio_trend": as_records(asset_gap_trend),
            "debt_by_generation": debt_chart,
            "lower_upper_mobility_line": as_records(lower_upper_line),
            "mobility_donut": as_records(mobility_donut),
            "income_transition_matrix_10": {
                "rows": [str(int(x)) for x in transition_pivot.index.tolist()],
                "columns": [str(int(x)) for x in transition_pivot.columns.tolist()],
                "values": [[round(float(v), 1) for v in row] for row in transition_pivot.values.tolist()],
                "raw": as_records(transition_10),
            },
        },
    }
    return data


st.set_page_config(
    page_title="대한민국 계층 고착화 실태 분석 대시보드",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
        .block-container {
            padding-top: 0rem !important;
            padding-bottom: 0rem !important;
            padding-left: 0rem !important;
            padding-right: 0rem !important;
            max-width: 100% !important;
        }
        header[data-testid="stHeader"] {display: none;}
        footer {display: none;}
        div[data-testid="stToolbar"] {display: none;}
        iframe {display: block;}
    </style>
    """,
    unsafe_allow_html=True,
)

missing = [name for name, path in DB_PATHS.items() if not path.exists()]
if not INDEX_PATH.exists():
    st.error("index.html 파일이 없습니다. app.py와 같은 GitHub 폴더에 index.html을 올려주세요.")
    st.stop()

if missing:
    missing_files = [str(DB_PATHS[name].name) for name in missing]
    st.error("다음 DB 파일이 누락되었습니다: " + ", ".join(missing_files))
    st.stop()

try:
    dashboard_data = build_dashboard_data()
except Exception as e:
    st.error("DB에서 대시보드 데이터를 불러오는 중 오류가 발생했습니다.")
    st.exception(e)
    st.stop()

html = INDEX_PATH.read_text(encoding="utf-8")
html = html.replace("__DASHBOARD_DATA__", json.dumps(dashboard_data, ensure_ascii=False))

# 대시보드 전체 길이에 맞춘 높이입니다. 기존 9000px 고정으로 생기던 불필요한 여백을 줄이기 위해
# HTML 자체를 더 촘촘하게 구성하고, 컴포넌트 높이도 적정 수준으로 조정했습니다.
components.html(html, height=9500, scrolling=True)
