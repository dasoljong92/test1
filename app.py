"""
마케팅 대시보드 (Streamlit) — marketing.db + 로그인
실행: streamlit run app.py
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import time

import pandas as pd
import streamlit as st

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "marketing.db")

ADMIN_ID = "admin"
# SHA-256("admin1234") — 로그인 검증용
PASSWORD_SHA256 = hashlib.sha256("admin1234".encode("utf-8")).hexdigest()

MAX_ATTEMPTS = 3
LOCK_SECONDS = 5 * 60


def _init_session() -> None:
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "fail_count" not in st.session_state:
        st.session_state.fail_count = 0
    if "lock_until" not in st.session_state:
        st.session_state.lock_until = 0.0


def _verify_password(plain: str) -> bool:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest() == PASSWORD_SHA256


def _load_raw() -> pd.DataFrame:
    if not os.path.isfile(DB_PATH):
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query(
            """
            SELECT date, channel, campaign, impressions, clicks, cost, conversions, revenue
            FROM daily_report
            ORDER BY date
            """,
            conn,
        )
    finally:
        conn.close()
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(ttl=60)
def load_data() -> pd.DataFrame:
    return _load_raw()


def login_page() -> None:
    st.title("로그인")
    now = time.time()
    lock_until = float(st.session_state.lock_until)

    if now < lock_until:
        left = int(lock_until - now)
        m, s = left // 60, left % 60
        st.error(f"로그인 시도가 너무 많습니다. {m}분 {s}초 후에 다시 시도하세요.")
        st.stop()

    with st.form("login_form"):
        uid = st.text_input("ID")
        pwd = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인")

    if not submitted:
        return

    if uid != ADMIN_ID or not _verify_password(pwd):
        st.session_state.fail_count += 1
        remain = MAX_ATTEMPTS - st.session_state.fail_count
        if st.session_state.fail_count >= MAX_ATTEMPTS:
            st.session_state.lock_until = time.time() + LOCK_SECONDS
            st.session_state.fail_count = 0
            st.error("3회 이상 실패했습니다. 5분간 로그인이 제한됩니다.")
            st.rerun()
        st.error(f"ID 또는 비밀번호가 올바르지 않습니다. (남은 시도: {remain}회)")
        return

    st.session_state.authenticated = True
    st.session_state.fail_count = 0
    st.session_state.lock_until = 0.0
    st.rerun()


def sidebar_filters(df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.header("필터")

    if df.empty:
        st.sidebar.warning("데이터가 없습니다.")
        return df

    dmin, dmax = df["date"].min().date(), df["date"].max().date()
    dr = st.sidebar.date_input(
        "기간",
        value=(dmin, dmax),
        min_value=dmin,
        max_value=dmax,
    )
    if isinstance(dr, tuple) and len(dr) == 2:
        start_d, end_d = dr
    else:
        start_d = end_d = dr

    channels = sorted(df["channel"].unique().tolist())
    sel_ch = st.sidebar.multiselect("채널", options=channels, default=channels)

    camp_df = df[df["channel"].isin(sel_ch)] if sel_ch else df
    campaigns = sorted(camp_df["campaign"].unique().tolist())
    sel_camp = st.sidebar.multiselect("캠페인", options=campaigns, default=campaigns)

    mask = (
        (df["date"].dt.date >= start_d)
        & (df["date"].dt.date <= end_d)
        & (df["channel"].isin(sel_ch))
        & (df["campaign"].isin(sel_camp))
    )
    return df.loc[mask]


def dashboard(df: pd.DataFrame) -> None:
    st.title("마케팅 대시보드")
    st.caption(f"DB: `{os.path.basename(DB_PATH)}` · 행 수: {len(df):,}")

    if df.empty:
        st.warning("표시할 데이터가 없습니다. 필터를 조정하거나 DB를 확인하세요.")
        return

    total_imp = int(df["impressions"].sum())
    total_clk = int(df["clicks"].sum())
    total_cost = int(df["cost"].sum())
    total_conv = int(df["conversions"].sum())
    total_rev = int(df["revenue"].sum())
    ctr = (total_clk / total_imp * 100) if total_imp else 0.0
    cpc = (total_cost / total_clk) if total_clk else 0.0
    roas = (total_rev / total_cost) if total_cost else 0.0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("노출", f"{total_imp:,}")
    c2.metric("클릭", f"{total_clk:,}")
    c3.metric("비용(원)", f"{total_cost:,}")
    c4.metric("전환", f"{total_conv:,}")
    c5.metric("매출(원)", f"{total_rev:,}")

    c6, c7, c8 = st.columns(3)
    c6.metric("CTR", f"{ctr:.2f}%")
    c7.metric("CPC(원)", f"{cpc:,.0f}")
    c8.metric("ROAS", f"{roas:.2f}x")

    st.subheader("일별 추이")
    daily = (
        df.assign(day=df["date"].dt.date)
        .groupby("day", as_index=False)
        .agg({"cost": "sum", "revenue": "sum", "clicks": "sum", "conversions": "sum"})
        .sort_values("day")
    )
    daily = daily.rename(columns={"day": "날짜"})
    st.line_chart(daily.set_index("날짜")[["cost", "revenue"]])

    st.subheader("채널별 일별 성과")
    ch_daily = (
        df.assign(day=df["date"].dt.date)
        .groupby(["day", "channel"], as_index=False)
        .agg({"cost": "sum", "revenue": "sum", "clicks": "sum", "conversions": "sum"})
    )
    ch_daily["roas"] = ch_daily["revenue"] / ch_daily["cost"].replace(0, pd.NA)
    metric_daily = st.selectbox(
        "표시 지표",
        ["비용", "매출", "클릭", "전환", "ROAS"],
        key="channel_daily_metric",
        help="채널마다 일자별 합계(ROAS는 해당 일·채널 매출÷비용)",
    )
    metric_col = {
        "비용": "cost",
        "매출": "revenue",
        "클릭": "clicks",
        "전환": "conversions",
        "ROAS": "roas",
    }[metric_daily]
    wide_ch = ch_daily.pivot(index="day", columns="channel", values=metric_col).sort_index()
    wide_ch = wide_ch.fillna(0)
    st.line_chart(wide_ch)
    st.caption("범례: 각 선이 채널입니다. 사이드바 채널·기간 필터가 그대로 적용됩니다.")

    st.subheader("채널별 비용·매출")
    by_ch = df.groupby("channel", as_index=False).agg({"cost": "sum", "revenue": "sum"})
    st.bar_chart(by_ch.set_index("channel"))

    st.subheader("캠페인 TOP (매출)")
    top = (
        df.groupby(["channel", "campaign"], as_index=False)["revenue"]
        .sum()
        .sort_values("revenue", ascending=False)
        .head(15)
    )
    st.dataframe(top, use_container_width=True, hide_index=True)

    with st.expander("원본 데이터 미리보기"):
        show = df.sort_values("date", ascending=False).copy()
        show["date"] = show["date"].dt.strftime("%Y-%m-%d")
        st.dataframe(show, use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(page_title="마케팅 대시보드", layout="wide")
    _init_session()

    if not st.session_state.authenticated:
        login_page()
        return

    if st.sidebar.button("로그아웃"):
        st.session_state.authenticated = False
        st.rerun()

    df = load_data()
    filtered = sidebar_filters(df)
    dashboard(filtered)


if __name__ == "__main__":
    main()
