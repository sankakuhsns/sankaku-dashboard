import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io
import os
import re
import traceback
import time
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account

# ==============================================================================
#      1. 설정 상수 정의
# ==============================================================================
# --- Google Drive 설정 ---
DRIVE_FOLDER_ID = '13pZg9s5CKv5nn84Zbnk7L6xmiwF_zluR'

# --- 파일별 설정 상수 ---
OKPOS_DATA_START_ROW, OKPOS_COL_DATE, OKPOS_COL_DAY_OF_WEEK, OKPOS_COL_DINE_IN_SALES, OKPOS_COL_TAKEOUT_SALES, OKPOS_COL_DELIVERY_SALES = 7, 0, 1, 34, 36, 38
DOORI_DATA_START_ROW, DOORI_COL_DATE, DOORI_COL_ITEM, DOORI_COL_AMOUNT = 4, 1, 3, 6
SINSEONG_DATA_START_ROW = 3  # 데이터 시작 행 (0-based index)
OURHOME_DATA_START_ROW, OURHOME_COL_DATE, OURHOME_COL_ITEM, OURHOME_COL_AMOUNT, OURHOME_FILTER_COL = 0, 1, 3, 11, 14
SETTLEMENT_DATA_START_ROW, SETTLEMENT_COL_PERSONNEL_NAME, SETTLEMENT_COL_PERSONNEL_AMOUNT, SETTLEMENT_COL_FOOD_ITEM, SETTLEMENT_COL_FOOD_AMOUNT, SETTLEMENT_COL_SUPPLIES_ITEM, SETTLEMENT_COL_SUPPLIES_AMOUNT, SETTLEMENT_COL_AD_ITEM, SETTLEMENT_COL_AD_AMOUNT, SETTLEMENT_COL_FIXED_ITEM, SETTLEMENT_COL_FIXED_AMOUNT = 3, 1, 2, 4, 5, 7, 8, 10, 11, 13, 14

# --- 분석용 카테고리 정의 ---
VARIABLE_COST_ITEMS = ['식자재', '소모품']
DELIVERY_SPECIFIC_VARIABLE_COST_ITEMS = ['배달비']
FIXED_COST_ITEMS = ['인건비', '광고비', '고정비']
ALL_POSSIBLE_EXPENSE_CATEGORIES = list(set(VARIABLE_COST_ITEMS + DELIVERY_SPECIFIC_VARIABLE_COST_ITEMS + FIXED_COST_ITEMS))

# ==============================================================================
#      2. 모든 함수 정의
# ==============================================================================

# ------------------ UI 헬퍼 함수들 ------------------
def setup_page():
    st.set_page_config(
        page_title="Sankaku Dashboard",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    st.markdown("""
    <style>
    /* Streamlit의 기본 UI 요소들을 한 번에 숨깁니다 */
    #MainMenu,
    footer,
    [data-testid="stDecoration"],
    [data-testid="stHeader"] {
        visibility: hidden;
        display: none !important;
        height: 0%;
    }

    /* 툴바 자체를 다시 보이게 하고, 그 안의 GitHub 아이콘만 숨깁니다 */
    [data-testid="stToolbar"] {
        visibility: visible !important;
        display: block !important;
        right: 2rem; /* 위치 조정 */
    }
    
    /* 정확한 GitHub 아이콘 선택자 */
    [data-testid="stToolbar"] a[title="View source"] {
        display: none !important;
    }
    </style>
    """, unsafe_allow_html=True)

    
    st.markdown('<meta name="google" content="notranslate">', unsafe_allow_html=True)
    st.markdown("""
    <style>
    html, body, [data-testid="stApp"] { background-color: #f0f0f0 !important; }
    [data-testid="block-container"] { padding: 1rem 2rem 0rem; margin-bottom: -7rem; background-color: #ffffff !important; border-radius: 12px; box-shadow: 0 0 8px rgba(0, 0, 0, 0.05); }
    [data-testid="stMetric"] { background-color: #ffffff; text-align: center; padding: 15px 0; border-radius: 10px; color: #333333; border: 1px solid #cccccc; box-shadow: 1px 1px 4px rgba(0,0,0,0.05); }
    div[data-testid="stMultiSelect"] div[data-baseweb="tag"] { background-color: #e0e0e0 !important; border-color: #b0b0b0 !important; color: #333333 !important; }
    .center-login { display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }
    .info-box { background-color: #f0f2f6; border-radius: 0.5rem; padding: 1rem; display: flex; align-items: center; justify-content: center; font-size: 1rem; border: 1px solid #e6e6e6; }
    [data-testid="stMetricLabel"] { display: flex; justify-content: center; }
    </style>
    """, unsafe_allow_html=True)

def display_styled_title_box(title_text, **kwargs):
    st.markdown(f"""
        <div style="border: 1px solid #cccccc; padding: {kwargs.get('padding_y', '10px')} 10px; border-radius: 5px; background-color: {kwargs.get('background_color', '#f5f5f5')}; text-align: center; margin-bottom: {kwargs.get('margin_bottom', '20px')};">
            <h3 style="margin: 0; font-size: {kwargs.get('font_size', '22px')}; color: #333333;">{title_text}</h3>
        </div>
    """, unsafe_allow_html=True)

def custom_slider(label, min_value, max_value, default_value, step, help_text, key, format_str="%.1f"):
    """
    st.session_state를 사용해 슬라이더와 숫자 입력이 항상 동기화되도록 개선된 함수.
    숫자 입력 칸은 +/- 버튼을 기본으로 포함합니다.
    """
    # session_state에 값이 없으면 default_value로 초기화
    if key not in st.session_state:
        st.session_state[key] = default_value

    # UI 레이아웃
    c1, c2 = st.columns([0.7, 0.3])

    # 슬라이더 값 변경 처리
    with c1:
        slider_val = st.slider(label, min_value, max_value, st.session_state[key], step, help=help_text, key=f"{key}_slider")
        # 슬라이더를 움직이면 state 업데이트
        if slider_val != st.session_state[key]:
            st.session_state[key] = slider_val
            st.rerun()

    # 숫자 입력 값 변경 처리
    with c2:
        number_val = st.number_input(" ", min_value, max_value, st.session_state[key], step, label_visibility="collapsed", key=f"{key}_num", format=format_str)
        # 숫자 칸 값을 바꾸면 state 업데이트
        if number_val != st.session_state[key]:
            st.session_state[key] = number_val
            st.rerun()

    return st.session_state[key]

# ------------------ 로그인 및 데이터 로딩 함수들 ------------------

def authenticate(password):
    users = st.secrets.get("users", [])
    for user in users:
        if user.get("password") == password:
            st.session_state.authenticated = True
            st.session_state.user_name = user.get("name")
            st.session_state.allowed_branches = user.get("allowed_branches")
            return True
    return False

def show_login_screen():
    _, center_col, _ = st.columns([1, 1.5, 1])
    with center_col:
        st.markdown("<div style='text-align:center;'><h2>산카쿠 분석 시스템</h2></div>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        with st.form("login_form"):
            password = st.text_input("🔐 비밀번호를 입력하세요", type="password")
            submitted = st.form_submit_button("로그인", use_container_width=True)
            if submitted:
                if authenticate(password):
                    st.rerun()
                else:
                    st.error("비밀번호가 틀렸습니다.")
    st.stop()

@st.cache_data(ttl=600)
def load_all_data_from_drive():
    try:
        credentials = service_account.Credentials.from_service_account_info(st.secrets["google"], scopes=['https://www.googleapis.com/auth/drive.readonly'])
        drive_service = build('drive', 'v3', credentials=credentials)
        all_files = list_files_recursive(drive_service, DRIVE_FOLDER_ID)
        all_rows = []
        file_counts = {'OKPOS': 0, '정산표': 0, '두리축산': 0, '신성미트': 0, '아워홈': 0, '기타/미지원': 0}
        processed_rows = {'OKPOS': 0, '정산표': 0, '두리축산': 0, '신성미트': 0, '아워홈': 0}

        for file in all_files:
            file_id, file_name = file['id'], file['name']
            file_path = file.get('path', file_name)
            path_parts = [part for part in file_path.split('/') if part]
            지점명 = path_parts[-2] if len(path_parts) >= 2 else "미분류"

            try:
                fh = io.BytesIO()
                request = drive_service.files().get_media(fileId=file_id)
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done: _, done = downloader.next_chunk()
                fh.seek(0)
            except HttpError: continue

            engine_to_use = 'openpyxl' if file_name.lower().endswith('.xlsx') else 'xlrd' if file_name.lower().endswith('.xls') else None
            if not engine_to_use:
                file_counts['기타/미지원'] += 1
                continue

            try:
                rows_before = len(all_rows)
                if "OKPOS" in file_path:
                    file_counts['OKPOS'] += 1
                    df_sheet = pd.read_excel(fh, header=None, engine=engine_to_use)
                    all_rows.extend(extract_okpos_table(df_sheet, 지점명))
                    processed_rows['OKPOS'] += (len(all_rows) - rows_before)
                elif "정산표" in file_path:
                    file_counts['정산표'] += 1
                    xls = pd.ExcelFile(fh, engine=engine_to_use)
                    for sheet_name in xls.sheet_names:
                        df_sheet = xls.parse(sheet_name, header=None)
                        all_rows.extend(extract_from_sheet(df_sheet, sheet_name, 지점명))
                        all_rows.extend(extract_kim_myeon_dashima(df_sheet, sheet_name, 지점명))
                    processed_rows['정산표'] += (len(all_rows) - rows_before)
                elif "두리축산" in file_path:
                    file_counts['두리축산'] += 1
                    df_sheet = pd.read_excel(fh, header=None, engine=engine_to_use)
                    all_rows.extend(extract_doori(df_sheet, 지점명))
                    processed_rows['두리축산'] += (len(all_rows) - rows_before)
                elif "신성미트" in file_path:
                    file_counts['신성미트'] += 1
                    df_sheet = pd.read_excel(fh, header=None, engine=engine_to_use)
                    all_rows.extend(extract_sinseongmeat(df_sheet, 지점명))
                    processed_rows['신성미트'] += (len(all_rows) - rows_before)
                elif "아워홈" in file_path:
                    file_counts['아워홈'] += 1
                    df_sheet = pd.read_excel(fh, header=None, engine=engine_to_use)
                    all_rows.extend(extract_ourhome(df_sheet, 지점명))
                    processed_rows['아워홈'] += (len(all_rows) - rows_before)
            except Exception as e:
                st.warning(f"😥 '{file_path}' 파일 처리 중 오류 발생: {e}")
        
        if not all_rows: return pd.DataFrame(), {}, {}
        
        df_통합 = pd.DataFrame(all_rows, columns=['날짜', '지점명', '분류', '항목1', '항목2', '금액'])
        df_통합['금액'] = pd.to_numeric(df_통합['금액'], errors='coerce')
        df_통합.dropna(subset=['금액', '날짜'], inplace=True)
        df_통합['날짜'] = pd.to_datetime(df_통합['날짜'], errors='coerce')
        df_통합.dropna(subset=['날짜'], inplace=True)
        return df_통합[df_통합['금액'] > 0].copy(), file_counts, processed_rows
    except Exception as e:
        st.error(f"Google Drive 데이터 로딩 중 심각한 오류가 발생했습니다: {e}")
        return pd.DataFrame(), {}, {}

def get_data():
    if 'df_all_branches' not in st.session_state or st.session_state.df_all_branches is None:
        st.toast(f'{st.session_state.get("user_name", "사용자")}님, 환영합니다!', icon='🎉')
        loading_message = "모든 지점의 데이터를 로딩 중입니다..."
        if "all" not in st.session_state.get("allowed_branches", []):
            loading_message = f'{", ".join(st.session_state.allowed_branches)} 지점의 데이터를 로딩 중입니다...'
        with st.spinner(loading_message):
            df_all, counts, rows = load_all_data_from_drive()
            st.session_state.df_all_branches, st.session_state.file_counts, st.session_state.processed_rows = df_all, counts, rows
        st.rerun()
    return st.session_state.df_all_branches, st.session_state.file_counts, st.session_state.processed_rows

# ------------------ 데이터 추출 헬퍼 함수들 ------------------
def list_files_recursive(service, folder_id, path_prefix=""):
    files = []
    try:
        results = service.files().list(q=f"'{folder_id}' in parents and trashed=false", fields="files(id, name, mimeType, parents)").execute()
        items = results.get('files', [])
        for item in items:
            item_path = f"{path_prefix}/{item['name']}" if path_prefix else item['name']
            if item.get('mimeType') == 'application/vnd.google-apps.folder':
                files.extend(list_files_recursive(service, item['id'], item_path))
            else:
                item['path'] = item_path
                files.append(item)
    except HttpError as e:
        st.error(f"Google Drive 폴더 접근 오류: {e}")
    return files

def sheetname_to_date(sheetname):
    match = re.match(r"(\d{2})[.\-](\d{1,2})", sheetname)
    if match: return f"20{match.group(1)}-{match.group(2).zfill(2)}-01"
    return ""

def extract_okpos_table(df, 지점명):
    out = []
    for i in range(OKPOS_DATA_START_ROW, df.shape[0]):
        date_cell = df.iloc[i, OKPOS_COL_DATE]
        if pd.isna(date_cell) or str(date_cell).strip() == '' or '합계' in str(date_cell): break
        try:
            if isinstance(date_cell, (int, float)):
                날짜 = (pd.to_datetime('1899-12-30') + pd.to_timedelta(date_cell, 'D')).strftime('%Y-%m-%d')
            else:
                날짜 = pd.to_datetime(str(date_cell).replace("소계:", "").strip()).strftime('%Y-%m-%d')
        except Exception: continue
        요일_str = str(df.iloc[i, OKPOS_COL_DAY_OF_WEEK]).strip() + "요일"
        홀매출 = pd.to_numeric(df.iloc[i, OKPOS_COL_DINE_IN_SALES], errors='coerce')
        포장매출 = pd.to_numeric(df.iloc[i, OKPOS_COL_TAKEOUT_SALES], errors='coerce')
        배달매출 = pd.to_numeric(df.iloc[i, OKPOS_COL_DELIVERY_SALES], errors='coerce')
        if pd.notna(홀매출) and 홀매출 > 0: out.append([날짜, 지점명, '매출', '홀매출', 요일_str, 홀매출])
        if pd.notna(포장매출) and 포장매출 > 0: out.append([날짜, 지점명, '매출', '포장매출', 요일_str, 포장매출])
        if pd.notna(배달매출) and 배달매출 > 0: out.append([날짜, 지점명, '매출', '배달매출', 요일_str, 배달매출])
    return out

def extract_doori(df, 지점명):
    out = []
    for i in range(DOORI_DATA_START_ROW, df.shape[0]):
        if pd.isna(df.iloc[i, 0]) or str(df.iloc[i, 0]).strip() == '': break
        try: 날짜 = pd.to_datetime(df.iloc[i, DOORI_COL_DATE]).strftime('%Y-%m-%d')
        except (ValueError, TypeError): continue
        항목2, 금액 = str(df.iloc[i, DOORI_COL_ITEM]).strip(), pd.to_numeric(df.iloc[i, DOORI_COL_AMOUNT], errors='coerce')
        if pd.notna(금액) and 금액 > 0 and 항목2:
            out.append([날짜, 지점명, '식자재', '두리축산', 항목2, 금액])
    return out

def extract_sinseongmeat(df, 지점명):
    out = []
    for i in range(SINSEONG_DATA_START_ROW, df.shape[0]):
        try:
            # 1. 날짜 추출 및 정제
            date_cell = str(df.iloc[i, 0]).strip()
            if not date_cell or '계' in date_cell or '이월' in date_cell:
                continue

            try:
                날짜 = pd.to_datetime(date_cell, errors='coerce')
                if pd.isna(날짜):
                    continue
                날짜 = 날짜.strftime('%Y-%m-%d')
            except Exception:
                continue

            # 2. 항목명 필터링
            항목2 = str(df.iloc[i, 2]).strip()
            if not 항목2 or any(k in 항목2 for k in ['[일 계]', '[월계]', '합계', '이월금액']):
                continue

            # 3. 금액 정제 (쉼표 제거 후 숫자화)
            raw_amount = str(df.iloc[i, 8]).replace(",", "").strip()
            금액 = pd.to_numeric(raw_amount, errors='coerce')
            if pd.isna(금액) or 금액 <= 0:
                continue

            # 4. 최종 추가
            out.append([날짜, 지점명, '식자재', '신성미트', 항목2, 금액])
        except (ValueError, TypeError, IndexError):
            continue
    return out

def extract_ourhome(df, 지점명):
    out, current_date = [], None
    for i in range(OURHOME_DATA_START_ROW, df.shape[0]):
        if len(df.columns) <= OURHOME_FILTER_COL or pd.isna(df.iloc[i, OURHOME_FILTER_COL]) or '아워홈' not in str(df.iloc[i, OURHOME_FILTER_COL]): continue
        raw_date_cell = df.iloc[i, OURHOME_COL_DATE]
        if pd.notna(raw_date_cell):
            try: current_date = pd.to_datetime(str(raw_date_cell), format='%Y%m%d').strftime('%Y-%m-%d')
            except (ValueError, TypeError): pass
        if not current_date: continue
        항목2, 금액 = str(df.iloc[i, OURHOME_COL_ITEM]).strip(), pd.to_numeric(df.iloc[i, OURHOME_COL_AMOUNT], errors='coerce')
        if pd.notna(금액) and 금액 > 0 and 항목2 and not any(k in 항목2 for k in ['소계', '합계', '총매입액']):
            out.append([current_date, 지점명, '식자재', '아워홈', 항목2, 금액])
    return out

def extract_kim_myeon_dashima(df, sheetname, 지점명):
    날짜 = sheetname_to_date(sheetname)
    if not 날짜: return []
    out = []
    for i in range(SETTLEMENT_DATA_START_ROW, df.shape[0]):
        item_cell, amount_cell = df.iloc[i, SETTLEMENT_COL_FOOD_ITEM], df.iloc[i, SETTLEMENT_COL_FOOD_AMOUNT]
        if pd.isna(item_cell) or pd.isna(amount_cell):
            if pd.isna(item_cell) and pd.isna(amount_cell): break
            continue
        금액 = pd.to_numeric(amount_cell, errors='coerce')
        if pd.isna(금액) or 금액 <= 0: continue
        항목_str = str(item_cell).strip()
        if any(keyword in 항목_str for keyword in ["김", "면", "다시마"]):
            parts = 항목_str.split('(')
            항목1 = parts[0].strip()
            항목2 = parts[1].replace(')', '').strip() if len(parts) > 1 else ""
            if 항목1 and 항목2:
                out.append([날짜, 지점명, "식자재", 항목1, 항목2, 금액])
    return out

def extract_from_sheet(df, sheetname, 지점명):
    날짜 = sheetname_to_date(sheetname)
    if not 날짜: return []
    out = []
    configs = [
        ("인건비", SETTLEMENT_COL_PERSONNEL_NAME, SETTLEMENT_COL_PERSONNEL_AMOUNT),
        ("식자재", SETTLEMENT_COL_FOOD_ITEM, SETTLEMENT_COL_FOOD_AMOUNT),
        ("소모품", SETTLEMENT_COL_SUPPLIES_ITEM, SETTLEMENT_COL_SUPPLIES_AMOUNT),
        ("광고비", SETTLEMENT_COL_AD_ITEM, SETTLEMENT_COL_AD_AMOUNT),
        ("고정비", SETTLEMENT_COL_FIXED_ITEM, SETTLEMENT_COL_FIXED_AMOUNT),
    ]
    for i in range(SETTLEMENT_DATA_START_ROW, df.shape[0]):
        if all(pd.isna(df.iloc[i, c[2]]) for c in configs if len(df.columns) > c[2]): break
        for cat, item_col, amount_col in configs:
            if len(df.columns) > item_col and len(df.columns) > amount_col:
                항목, 금액 = df.iloc[i, item_col], pd.to_numeric(df.iloc[i, amount_col], errors='coerce')
                if pd.notna(항목) and pd.notna(금액) and 금액 > 0:
                    항목_str = str(항목).strip()
                    분류 = "배달비" if cat == "고정비" and ("배달대행" in 항목_str or "배달수수료" in 항목_str) else cat
                    out.append([날짜, 지점명, "지출", 분류, 항목_str, 금액])
    return out

# ==================================================================
#                       >>> 메인 앱 실행 <<<
# ==================================================================

setup_page()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if not st.session_state.authenticated:
    show_login_screen()

df_all_branches, file_counts, processed_rows = get_data()

if df_all_branches.empty:
    st.error("처리할 데이터가 없습니다. Google Drive 폴더 또는 파일 내용을 확인해주세요.")
    st.stop()

if "all" in st.session_state.allowed_branches:
    df = df_all_branches.copy()
else:
    df = df_all_branches[df_all_branches['지점명'].isin(st.session_state.allowed_branches)].copy()

df['월'] = df['날짜'].dt.strftime('%y년 %m월')
df['요일'] = df['날짜'].dt.day_name().map({'Monday': '월요일', 'Tuesday': '화요일', 'Wednesday': '수요일', 'Thursday': '목요일', 'Friday': '금요일', 'Saturday': '토요일', 'Sunday': '일요일'})
df['항목1'] = df['항목1'].fillna('기타')
df['항목2'] = df['항목2'].fillna('기타')

with st.sidebar:
    st.title('📊 대시보드')
    st.info(f"**로그인 계정:**\n\n{st.session_state.user_name}")
    st.markdown("---")
    
    지점목록 = sorted(df['지점명'].unique())
    월목록 = sorted(df['월'].unique(), reverse=True)
    
    선택_지점 = st.multiselect("📍 지점 선택", 지점목록, default=지점목록)
    선택_월 = st.multiselect("🗓️ 월 선택", 월목록, default=월목록)

df_filtered = df[df['지점명'].isin(선택_지점) & df['월'].isin(선택_월)]

if df_filtered.empty:
    st.warning("선택하신 조건에 해당하는 데이터가 없습니다. 필터를 조정해주세요.")
    st.stop()

# --- UI 렌더링을 위한 최종 데이터 준비 ---
매출 = df_filtered[df_filtered['분류'] == '매출'].copy()
지출 = df_filtered[df_filtered['분류'] == '지출'].copy()
식자재_분석용_df = df_filtered[(df_filtered['분류'] == '식자재') & (~df_filtered['항목2'].astype(str).str.contains("소계|총계|합계|전체|총액|이월금액|일계", na=False, regex=True))].copy() 

chart_colors_palette = ['#964F4C', '#7A6C60', '#B0A696', '#5E534A', '#DED3BF', '#C0B4A0', '#F0E6D8', '#687E8E']
color_map_항목1_매출 = {cat: chart_colors_palette[i % len(chart_colors_palette)] for i, cat in enumerate(매출['항목1'].unique())}
color_map_항목1_지출 = {cat: chart_colors_palette[i % len(chart_colors_palette)] for i, cat in enumerate(지출['항목1'].unique())}
color_map_월 = {month: chart_colors_palette[i % len(chart_colors_palette)] for i, month in enumerate(sorted(df['월'].unique()))}
color_map_요일 = {day: chart_colors_palette[i % len(chart_colors_palette)] for i, day in enumerate(['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일'])}
color_map_지점 = {branch: chart_colors_palette[i % len(chart_colors_palette)] for i, branch in enumerate(sorted(df['지점명'].unique()))}


# --- 헤더 및 KPI ---
분석최소일 = df_filtered['날짜'].min().strftime('%Y-%m-%d')
분석최대일 = df_filtered['날짜'].max().strftime('%Y-%m-%d')

st.markdown(f"""
<div style='text-align: center; margin-bottom: 1rem; padding: 3rem 2rem; border-radius: 12px; background-color: #ffffff; border: 1px solid #cccccc; box-shadow: 0 4px 12px rgba(0,0,0,0.05);'>
    <span style='color: #333333; font-size: 60px; font-weight: 700; letter-spacing: -1px;'>산카쿠 분석 시스템</span>
</div>
""", unsafe_allow_html=True)
st.markdown("<br>", unsafe_allow_html=True)
st.markdown(f"""
<div style='background-color: #f5f5f5; padding: 1rem 2rem; border-radius: 8px; border: 1px solid #cccccc; margin-bottom: 2rem; font-size: 16px; color: #333333;'>
    🔎 <b>분석 지점</b>: {", ".join(선택_지점) if 선택_지점 else "전체 지점"}<br>
    ⚙️ <b>데이터 적용 상태</b>: 최신 상태 반영 완료 ( {분석최소일} ~ {분석최대일} )
</div>
""", unsafe_allow_html=True)

with st.expander("🗂️ 파일 처리 요약 보기"):
    col1, col2 = st.columns(2)
    with col1:
        st.write("**발견된 파일 수**")
        st.dataframe(pd.DataFrame.from_dict(file_counts, orient='index', columns=['파일 수']))
    with col2:
        st.write("**추출된 행 수**")
        st.dataframe(pd.DataFrame.from_dict(processed_rows, orient='index', columns=['행 수']))

st.markdown("---")
display_styled_title_box("🔸 정보 요약 🔸", font_size="32px", padding_y="15px")
매출합계 = 매출['금액'].sum()
지출합계 = 지출['금액'].sum()
순수익 = 매출합계 - 지출합계
순수익률 = (순수익 / 매출합계 * 100) if 매출합계 > 0 else 0
col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)
col_kpi1.metric("전체 매출", f"{매출합계:,.0f} 원")
col_kpi2.metric("전체 지출", f"{지출합계:,.0f} 원")
col_kpi3.metric("순수익", f"{순수익:,.0f} 원")
col_kpi4.metric("순수익률", f"{순수익률:.2f}%")
st.markdown("---")
st.markdown("<br>", unsafe_allow_html=True)

#######################
# 📈 매출 분석 섹션
#######################
display_styled_title_box("📈 매출 분석 📈", background_color="#f5f5f5", font_size="32px", margin_bottom="20px", padding_y="15px")
col_chart1, col_chart2 = st.columns(2)
with col_chart1:
    display_styled_title_box("매출 항목 비율", background_color="#f5f5f5", font_size="22px", margin_bottom="20px")
    if 매출.empty:
        st.warning("매출 데이터가 없어 '매출 항목 비율' 차트를 표시할 수 없습니다.")
    else:
        pie1 = px.pie(매출.groupby('항목1')['금액'].sum().reset_index(), names='항목1', values='금액', hole=0, color='항목1', color_discrete_map=color_map_항목1_매출)
        pie1.update_traces(marker=dict(line=dict(color='#cccccc', width=1)), hovertemplate="항목 : %{label}<br>금액: %{value:,.0f}원<extra></extra>", textinfo='label+percent', texttemplate='%{label}<br>%{percent}', textfont_size=15)
        pie1.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5), height=550, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(pie1, use_container_width=True)
with col_chart2:
    display_styled_title_box("매출 항목 월별 트렌드", background_color="#f5f5f5", font_size="22px", margin_bottom="20px")
    if 매출.empty:
        st.warning("매출 데이터가 없어 '매출 항목 월별 트렌드' 차트를 표시할 수 없습니다.")
    else:
        line_data = 매출.groupby(['월','항목1'])['금액'].sum().reset_index()
        line = px.line(line_data, x='월', y='금액', color='항목1', markers=True, color_discrete_map=color_map_항목1_매출)
        line.update_traces(text=line_data['금액'].apply(lambda x: f'{x:,.0f}'), texttemplate='%{text}', textposition='top center', hovertemplate="항목 : %{fullData.name}<br>금액: %{y:,.0f}원<extra></extra>")
        line.update_layout(height=550, legend=dict(title_text='', orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5), yaxis_tickformat=',', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(line, use_container_width=True)

st.markdown("---")
col_chart3, col_chart4, col_chart5 = st.columns(3)
with col_chart3:
    display_styled_title_box("지점별 매출 비교", background_color="#f5f5f5", font_size="22px", margin_bottom="20px")
    if 매출.empty:
        st.warning("매출 데이터가 없어 '지점별 매출 비교' 차트를 표시할 수 없습니다.")
    else:
        매출_지점별 = 매출.groupby('지점명')['금액'].sum().reset_index()
        bar1 = px.bar(매출_지점별, x='지점명', y='금액', text='금액', color='지점명', color_discrete_map=color_map_지점)
        bar1.update_traces(texttemplate='%{text:,.0f}원', textposition='outside', hovertemplate="지점: %{x}<br>금액: %{y:,.0f}원<extra></extra>", textangle=0)
        bar1.update_layout(height=550, xaxis_tickangle=0, bargap=0.5, showlegend=False, yaxis_tickformat=',', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(bar1, use_container_width=True)
with col_chart4:
    display_styled_title_box("월별 매출 비율", background_color="#f5f5f5", font_size="22px", margin_bottom="20px")
    if 매출.empty:
        st.warning("매출 데이터가 없어 '월별 매출 비율' 차트를 표시할 수 없습니다.")
    else:
        pie2 = px.pie(매출.groupby('월')['금액'].sum().reset_index(), names='월', values='금액', color='월', color_discrete_map=color_map_월)
        pie2.update_traces(marker=dict(line=dict(color='#cccccc', width=1)), hovertemplate="월: %{label}<br>금액: %{value:,.0f}원<extra></extra>", textinfo='label+percent', texttemplate='%{label}<br>%{percent}', textfont_size=15)
        pie2.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5), height=550, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(pie2, use_container_width=True)
with col_chart5:
    display_styled_title_box("요일별 매출 비율", background_color="#f5f5f5", font_size="22px", margin_bottom="20px")
    if 매출.empty:
        st.warning("매출 데이터가 없어 '요일별 매출 비율' 차트를 표시할 수 없습니다.")
    else:
        ordered_weekdays = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']
        매출_요일별 = 매출.groupby('요일')['금액'].sum().reindex(ordered_weekdays).reset_index()
        pie3 = px.pie(매출_요일별, names='요일', values='금액', color='요일', color_discrete_map=color_map_요일)
        pie3.update_traces(marker=dict(line=dict(color='#cccccc', width=1)), hovertemplate="요일: %{label}<br>금액: %{value:,.0f}원<extra></extra>", textinfo='label+percent', texttemplate='%{label}<br>%{percent}', textfont_size=15)
        pie3.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5, traceorder='normal'), height=550, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(pie3, use_container_width=True)

####################################################################################################
# 💸 지출 분석 섹션
####################################################################################################
st.markdown("---")
st.markdown("<br>", unsafe_allow_html=True)
display_styled_title_box("💸 지출 분석 💸", background_color="#f5f5f5", font_size="32px", margin_bottom="20px", padding_y="15px")

if not 매출.empty:
    총매출_월별_지점별 = 매출.groupby(['지점명', '월'])['금액'].sum().reset_index().rename(columns={'금액': '총매출'})
    배달매출_월별_지점별 = 매출[매출['항목1'].isin(['배달매출', '포장매출'])].groupby(['지점명', '월'])['금액'].sum().reset_index().rename(columns={'금액': '배달매출_총액'})
    홀매출_월별_지점별 = 매출[매출['항목1'] == '홀매출'].groupby(['지점명', '월'])['금액'].sum().reset_index().rename(columns={'금액': '홀매출_총액'})
    지출_항목1별_월별_지점별_raw = pd.DataFrame()
    if not 지출.empty:
        지출_항목1별_월별_지점별_raw = 지출.groupby(['지점명', '월', '항목1'])['금액'].sum().unstack(level='항목1', fill_value=0).reset_index()
    for col in ALL_POSSIBLE_EXPENSE_CATEGORIES:
        if col not in 지출_항목1별_월별_지점별_raw.columns:
            지출_항목1별_월별_지점별_raw[col] = 0
    df_expense_analysis = pd.merge(총매출_월별_지점별, 배달매출_월별_지점별, on=['지점명', '월'], how='left').fillna(0)
    df_expense_analysis = pd.merge(df_expense_analysis, 홀매출_월별_지점별, on=['지점명', '월'], how='left').fillna(0)
    df_expense_analysis = pd.merge(df_expense_analysis, 지출_항목1별_월별_지점별_raw, on=['지점명', '월'], how='left').fillna(0)
else:
    df_expense_analysis = pd.DataFrame()

col_h_exp1, col_h_exp2 = st.columns(2)
with col_h_exp1:
    display_styled_title_box("홀매출 지출 항목 비율", font_size="22px", margin_bottom="20px")
    홀매출_지출_원형_대상_항목 = [item for item in (VARIABLE_COST_ITEMS + FIXED_COST_ITEMS) if item in df_expense_analysis.columns]
    pie_data_list_h = []
    홀매출_분석용_비중_series = (df_expense_analysis.get('홀매출_총액', 0) / df_expense_analysis['총매출'].replace(0, 1)).fillna(0)
    for item in 홀매출_지출_원형_대상_항목:
        allocated_amount = (df_expense_analysis[item] * 홀매출_분석용_비중_series).sum()
        if allocated_amount > 0: pie_data_list_h.append({'항목1': item, '금액': allocated_amount})
    pie_data_h = pd.DataFrame(pie_data_list_h)
    if pie_data_h.empty or pie_data_h['금액'].sum() == 0:
        st.warning("홀매출 지출 데이터가 없어 비율 차트를 표시할 수 없습니다.")
    else:
        pie_expense_h1 = px.pie(pie_data_h, names='항목1', values='금액', hole=0, color='항목1', color_discrete_map=color_map_항목1_지출)
        pie_expense_h1.update_traces(marker=dict(line=dict(color='#cccccc', width=1)), hovertemplate="항목 : %{label}<br>금액: %{value:,.0f}원<extra></extra>", textinfo='label+percent', texttemplate='%{label}<br>%{percent}', textfont_size=15)
        pie_expense_h1.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5), height=550, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(pie_expense_h1, use_container_width=True)
with col_h_exp2:
    display_styled_title_box("홀매출 지출 항목 월별 지출", font_size="22px", margin_bottom="20px")
    df_홀지출_월별_data_list = []
    df_expense_analysis['홀매출_비중_계산용'] = (df_expense_analysis.get('홀매출_총액', 0) / df_expense_analysis['총매출'].replace(0, 1)).fillna(0)
    for item in 홀매출_지출_원형_대상_항목:
        if item in df_expense_analysis.columns:
            df_temp = df_expense_analysis.groupby('월').apply(lambda x: (x[item] * x['홀매출_비중_계산용']).sum()).reset_index(name='금액')
            df_홀지출_월별_data_list.append(df_temp.assign(항목1=item))
    df_홀지출_월별_data = pd.concat(df_홀지출_월별_data_list, ignore_index=True) if df_홀지출_월별_data_list else pd.DataFrame()
    if df_홀지출_월별_data.empty or df_홀지출_월별_data['금액'].sum() == 0:
        st.warning("홀매출 월별 지출 데이터가 없어 트렌드 차트를 표시할 수 없습니다.")
    else:
        line_expense_h2 = px.line(df_홀지출_월별_data, x='월', y='금액', color='항목1', markers=True, color_discrete_map=color_map_항목1_지출)
        line_expense_h2.update_traces(text=df_홀지출_월별_data['금액'], texttemplate='%{text:,.0f}', textposition='top center', hovertemplate="항목 : %{fullData.name}<br>금액: %{y:,.0f}원<extra></extra>")
        line_expense_h2.update_layout(height=550, legend=dict(title_text='', orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5), yaxis_tickformat=',', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(line_expense_h2, use_container_width=True)

st.markdown("---")
col_d_exp1, col_d_exp2 = st.columns(2)
with col_d_exp1:
    display_styled_title_box("배달+포장 지출 항목 비율", font_size="22px", margin_bottom="20px")
    배달매출_지출_원형_데이터_list = []
    delivery_specific_sum = df_expense_analysis.get('배달비', 0).sum()
    if delivery_specific_sum > 0: 배달매출_지출_원형_데이터_list.append({'항목1': '배달비', '금액': delivery_specific_sum})
    기타_지출_항목들_배달관련_원형 = [item for item in (VARIABLE_COST_ITEMS + FIXED_COST_ITEMS) if item in df_expense_analysis.columns]
    if not df_expense_analysis.empty and '배달매출_총액' in df_expense_analysis.columns:
        배달매출_비중 = (df_expense_analysis['배달매출_총액'] / df_expense_analysis['총매출'].replace(0, 1)).fillna(0)
        for item in 기타_지출_항목들_배달관련_원형:
            allocated_amount = (df_expense_analysis[item] * 배달매출_비중).sum()
            if allocated_amount > 0: 배달매출_지출_원형_데이터_list.append({'항목1': item, '금액': allocated_amount})
    pie_data_d = pd.DataFrame(배달매출_지출_원형_데이터_list)
    if pie_data_d.empty or pie_data_d['금액'].sum() == 0:
        st.warning("배달+포장 지출 데이터가 없어 비율 차트를 표시할 수 없습니다.")
    else:
        pie_expense_d1 = px.pie(pie_data_d, names='항목1', values='금액', hole=0, color='항목1', color_discrete_map=color_map_항목1_지출)
        pie_expense_d1.update_traces(marker=dict(line=dict(color='#cccccc', width=1)), hovertemplate="항목 : %{label}<br>금액: %{value:,.0f}원<extra></extra>", textinfo='label+percent', texttemplate='%{label}<br>%{percent}', textfont_size=15)
        pie_expense_d1.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5), height=550, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(pie_expense_d1, use_container_width=True)
with col_d_exp2:
    display_styled_title_box("배달+포장 지출 항목 월별 지출", font_size="22px", margin_bottom="20px")
    df_temp_line_d_list = []
    if '배달비' in df_expense_analysis.columns:
        df_temp = df_expense_analysis.groupby('월')['배달비'].sum().reset_index(name='금액')
        df_temp_line_d_list.append(df_temp.assign(항목1='배달비'))
    if '배달매출_총액' in df_expense_analysis.columns:
        df_expense_analysis['배달매출_비중_계산용'] = (df_expense_analysis['배달매출_총액'] / df_expense_analysis['총매출'].replace(0, 1)).fillna(0)
        for item in 기타_지출_항목들_배달관련_원형:
            if item in df_expense_analysis.columns:
                df_temp = df_expense_analysis.groupby('월').apply(lambda x: (x[item] * x['배달매출_비중_계산용']).sum()).reset_index(name='금액')
                df_temp_line_d_list.append(df_temp.assign(항목1=item))
    df_temp_line_d = pd.concat(df_temp_line_d_list, ignore_index=True) if df_temp_line_d_list else pd.DataFrame()
    if df_temp_line_d.empty or df_temp_line_d['금액'].sum() == 0:
        st.warning("배달+포장 월별 지출 데이터가 없어 트렌드 차트를 표시할 수 없습니다.")
    else:
        line_expense_d2 = px.line(df_temp_line_d, x='월', y='금액', color='항목1', markers=True, color_discrete_map=color_map_항목1_지출)
        line_expense_d2.update_traces(text=df_temp_line_d['금액'], texttemplate='%{text:,.0f}', textposition='top center', hovertemplate="항목 : %{fullData.name}<br>금액: %{y:,.0f}원<extra></extra>")
        line_expense_d2.update_layout(height=550, legend=dict(title_text='', orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5), yaxis_tickformat=',', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(line_expense_d2, use_container_width=True)

####################################################################################################
# 💰 순수익 분석 섹션
####################################################################################################
st.markdown("---")
st.markdown("<br>", unsafe_allow_html=True)
display_styled_title_box("💰 순수익 분석 💰", background_color="#f5f5f5", font_size="32px", margin_bottom="20px", padding_y="15px")

if not df_expense_analysis.empty:
    df_profit_analysis_recalc = df_expense_analysis.copy()
    df_profit_analysis_recalc['총지출'] = df_profit_analysis_recalc[[item for item in ALL_POSSIBLE_EXPENSE_CATEGORIES if item in df_profit_analysis_recalc.columns]].sum(axis=1)
    df_profit_analysis_recalc['총순수익'] = df_profit_analysis_recalc['총매출'] - df_profit_analysis_recalc['총지출']
    df_profit_analysis_recalc['총순수익률'] = (df_profit_analysis_recalc['총순수익'] / df_profit_analysis_recalc['총매출'].replace(0, 1e-9)) * 100

    df_profit_analysis_recalc['홀매출_분석용'] = df_profit_analysis_recalc.get('홀매출_총액', 0)
    홀매출_비중 = (df_profit_analysis_recalc['홀매출_분석용'] / df_profit_analysis_recalc['총매출'].replace(0, 1e-9)).fillna(0)
    홀매출_관련_공통비용 = (df_profit_analysis_recalc[[c for c in FIXED_COST_ITEMS + VARIABLE_COST_ITEMS if c in df_profit_analysis_recalc.columns]].sum(axis=1) * 홀매출_비중)
    df_profit_analysis_recalc['홀순수익'] = df_profit_analysis_recalc['홀매출_분석용'] - 홀매출_관련_공통비용
    df_profit_analysis_recalc['홀순수익률'] = (df_profit_analysis_recalc['홀순수익'] / df_profit_analysis_recalc['홀매출_분석용'].replace(0, 1e-9) * 100).fillna(0)

    df_profit_analysis_recalc['배달매출_분석용'] = df_profit_analysis_recalc.get('배달매출_총액', 0)
    배달매출_비중 = (df_profit_analysis_recalc['배달매출_분석용'] / df_profit_analysis_recalc['총매출'].replace(0, 1e-9)).fillna(0)
    배달매출_관련_공통비용 = (df_profit_analysis_recalc[[c for c in FIXED_COST_ITEMS + VARIABLE_COST_ITEMS if c in df_profit_analysis_recalc.columns]].sum(axis=1) * 배달매출_비중)
    배달매출_전용비용 = df_profit_analysis_recalc.get('배달비', 0)
    df_profit_analysis_recalc['배달순수익'] = df_profit_analysis_recalc['배달매출_분석용'] - (배달매출_관련_공통비용 + 배달매출_전용비용)
    df_profit_analysis_recalc['배달순수익률'] = (df_profit_analysis_recalc['배달순수익'] / df_profit_analysis_recalc['배달매출_분석용'].replace(0, 1e-9) * 100).fillna(0)
else:
    df_profit_analysis_recalc = pd.DataFrame()

col_profit_rate1_1, col_profit_rate1_2, col_profit_rate1_3 = st.columns(3)
with col_profit_rate1_1:
    display_styled_title_box("총 순수익률 추이", font_size="22px", margin_bottom="20px")
    if df_profit_analysis_recalc.empty or '총순수익률' not in df_profit_analysis_recalc or df_profit_analysis_recalc['총순수익률'].isnull().all():
        st.warning("데이터가 없어 '총 순수익률 추이' 차트를 표시할 수 없습니다.")
    else:
        line_total_profit_rate = px.line(df_profit_analysis_recalc, x='월', y='총순수익률', color='지점명', markers=True, custom_data=['총순수익'], color_discrete_map=color_map_지점)
        line_total_profit_rate.update_traces(texttemplate='%{y:.2f}%', textposition='top center', hovertemplate="<b>지점:</b> %{fullData.name}<br><b>월:</b> %{x}<br><b>순수익률:</b> %{y:.2f}%<br><b>순수익:</b> %{customdata[0]:,.0f}원<extra></extra>")
        line_total_profit_rate.update_layout(height=550, legend=dict(title_text="", orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5), yaxis=dict(ticksuffix="%", tickformat=",.2f"), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(line_total_profit_rate, use_container_width=True)
with col_profit_rate1_2:
    display_styled_title_box("홀 순수익률 추이", font_size="22px", margin_bottom="20px")
    if df_profit_analysis_recalc.empty or '홀순수익률' not in df_profit_analysis_recalc or df_profit_analysis_recalc['홀순수익률'].isnull().all():
        st.warning("데이터가 없어 '홀 순수익률 추이' 차트를 표시할 수 없습니다.")
    else:
        line_hall_profit_rate = px.line(df_profit_analysis_recalc, x='월', y='홀순수익률', color='지점명', markers=True, custom_data=['홀순수익'], color_discrete_map=color_map_지점)
        line_hall_profit_rate.update_traces(texttemplate='%{y:.2f}%', textposition='top center', hovertemplate="<b>지점:</b> %{fullData.name}<br><b>월:</b> %{x}<br><b>순수익률:</b> %{y:.2f}%<br><b>순수익:</b> %{customdata[0]:,.0f}원<extra></extra>")
        line_hall_profit_rate.update_layout(height=550, legend=dict(title_text="", orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5), yaxis=dict(ticksuffix="%"), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(line_hall_profit_rate, use_container_width=True)
with col_profit_rate1_3:
    display_styled_title_box("배달+포장 순수익률 추이", font_size="22px", margin_bottom="20px")
    if df_profit_analysis_recalc.empty or '배달순수익률' not in df_profit_analysis_recalc or df_profit_analysis_recalc['배달순수익률'].isnull().all():
        st.warning("데이터가 없어 '배달 순수익률 추이' 차트를 표시할 수 없습니다.")
    else:
        line_delivery_profit_rate = px.line(df_profit_analysis_recalc, x='월', y='배달순수익률', color='지점명', markers=True, custom_data=['배달순수익'], color_discrete_map=color_map_지점)
        line_delivery_profit_rate.update_traces(texttemplate='%{y:.2f}%', textposition='top center', hovertemplate="<b>지점:</b> %{fullData.name}<br><b>월:</b> %{x}<br><b>순수익률:</b> %{y:.2f}%<br><b>순수익:</b> %{customdata[0]:,.0f}원<extra></extra>")
        line_delivery_profit_rate.update_layout(height=550, legend=dict(title_text="", orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5), yaxis=dict(ticksuffix="%"), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(line_delivery_profit_rate, use_container_width=True)

st.markdown("---")
col_profit_cost_1, col_profit_cost_2, col_profit_cost_3 = st.columns(3)
with col_profit_cost_1:
    display_styled_title_box("매출 손익분기점 분석", font_size="22px", margin_bottom="20px")
    if df_profit_analysis_recalc.empty:
        st.warning("데이터가 없어 '매출 손익분기점 분석' 차트를 표시할 수 없습니다.")
    else:
        df_profit_analysis_recalc['총변동비_계산'] = df_profit_analysis_recalc[[c for c in VARIABLE_COST_ITEMS + DELIVERY_SPECIFIC_VARIABLE_COST_ITEMS if c in df_profit_analysis_recalc.columns]].sum(axis=1)
        df_profit_analysis_recalc['총고정비_계산'] = df_profit_analysis_recalc[[c for c in FIXED_COST_ITEMS if c in df_profit_analysis_recalc.columns]].sum(axis=1)
        df_profit_analysis_recalc['공헌이익률'] = (1 - (df_profit_analysis_recalc['총변동비_계산'] / df_profit_analysis_recalc['총매출'].replace(0,1e-9))).fillna(0)
        df_profit_analysis_recalc['손익분기점_매출'] = (df_profit_analysis_recalc['총고정비_계산'] / df_profit_analysis_recalc['공헌이익률'].replace(0,1e-9)).replace([float('inf'), -float('inf')], 0).fillna(0)
        df_profit_analysis_recalc['안전여유매출액'] = df_profit_analysis_recalc['총매출'] - df_profit_analysis_recalc['손익분기점_매출']
        df_bep_total = df_profit_analysis_recalc.groupby('월').agg(총매출=('총매출', 'sum'), 손익분기점_매출=('손익분기점_매출', 'sum'), 안전여유매출액=('안전여유매출액', 'sum')).reset_index()
        fig_bep = go.Figure()
        fig_bep.add_trace(go.Bar(x=df_bep_total['월'], y=df_bep_total['총매출'], name='총매출', marker_color=chart_colors_palette[0], text=df_bep_total['총매출']))
        fig_bep.add_trace(go.Bar(x=df_bep_total['월'], y=df_bep_total['손익분기점_매출'], name='손익분기점 매출', marker_color=chart_colors_palette[1], text=df_bep_total['손익분기점_매출']))
        fig_bep.add_trace(go.Scatter(x=df_bep_total['월'], y=df_bep_total['안전여유매출액'], mode='lines+markers+text', name='안전여유매출액', marker_color=chart_colors_palette[2], line=dict(width=2), text=df_bep_total['안전여유매출액'], textposition="top center"))
        fig_bep.update_traces(selector=dict(type='bar'), texttemplate='%{text:,.0f}', textangle=0, hovertemplate="<b>월:</b> %{x}<br><b>%{data.name}:</b> %{y:,.0f}원<extra></extra>")
        fig_bep.update_traces(selector=dict(type='scatter'), texttemplate='%{text:,.0f}', hovertemplate="<b>월:</b> %{x}<br><b>%{data.name}:</b> %{y:,.0f}원<extra></extra>")
        fig_bep.update_layout(barmode='group', height=550, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5), yaxis=dict(tickformat=","), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig_bep, use_container_width=True)
with col_profit_cost_2:
    display_styled_title_box("식자재 원가율 추이", font_size="22px", margin_bottom="20px")
    if df_profit_analysis_recalc.empty or '식자재' not in df_profit_analysis_recalc.columns:
        st.warning("데이터가 없어 '식자재 원가율 추이' 차트를 표시할 수 없습니다.")
    else:
        df_profit_analysis_recalc['식자재_원가율'] = (df_profit_analysis_recalc.get('식자재', 0) / df_profit_analysis_recalc['총매출'].replace(0,1e-9) * 100).fillna(0)
        line_food_cost = px.line(df_profit_analysis_recalc, x='월', y='식자재_원가율', color='지점명', markers=True, color_discrete_map=color_map_지점)
        line_food_cost.update_traces(texttemplate='%{y:.2f}%', textposition='top center', hovertemplate="<b>지점:</b> %{fullData.name}<br><b>월:</b> %{x}<br><b>원가율:</b> %{y:.2f}%<extra></extra>")
        line_food_cost.update_layout(height=550, legend=dict(title_text="", orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5), yaxis=dict(ticksuffix="%"), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(line_food_cost, use_container_width=True)
with col_profit_cost_3:
    display_styled_title_box("인건비 원가율 추이", font_size="22px", margin_bottom="20px")
    if df_profit_analysis_recalc.empty or '인건비' not in df_profit_analysis_recalc.columns:
        st.warning("데이터가 없어 '인건비 원가율 추이' 차트를 표시할 수 없습니다.")
    else:
        df_profit_analysis_recalc['인건비_원가율'] = (df_profit_analysis_recalc.get('인건비', 0) / df_profit_analysis_recalc['총매출'].replace(0,1e-9) * 100).fillna(0)
        line_labor_cost = px.line(df_profit_analysis_recalc, x='월', y='인건비_원가율', color='지점명', markers=True, color_discrete_map=color_map_지점)
        line_labor_cost.update_traces(texttemplate='%{y:.2f}%', textposition='top center', hovertemplate="<b>지점:</b> %{fullData.name}<br><b>월:</b> %{x}<br><b>원가율:</b> %{y:.2f}%<extra></extra>")
        line_labor_cost.update_layout(height=550, legend=dict(title_text="", orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5), yaxis=dict(ticksuffix="%"), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(line_labor_cost, use_container_width=True)

####################################################################################################
# 🥒 식자재 분석 섹션
####################################################################################################
st.markdown("---")
st.markdown("<br>", unsafe_allow_html=True)
display_styled_title_box("🥒 식자재 분석 🥒", background_color="#f5f5f5", font_size="32px", margin_bottom="20px", padding_y="15px")
st.subheader("상위 20개 식자재 품목 총액")
if 식자재_분석용_df.empty:
    st.warning("식자재 지출 데이터가 없어 상위 20개 리스트를 표시할 수 없습니다.")
else:
    top_20_식자재 = 식자재_분석용_df.groupby('항목2')['금액'].sum().nlargest(20).reset_index()
    top_20_식자재.columns = ['식자재 품목 (세부)', '총 금액']
    if not top_20_식자재.empty:
        top_20_식자재['순위'] = range(1, len(top_20_식자재) + 1)
        total_식자재_금액 = top_20_식자재['총 금액'].sum()
        top_20_식자재['비중 (%)'] = (top_20_식자재['총 금액'] / total_식자재_금액 * 100).fillna(0) if total_식자재_금액 > 0 else 0
    st.dataframe(top_20_식자재[['순위', '식자재 품목 (세부)', '총 금액', '비중 (%)']].style.format({"총 금액": "{:,.0f}원", "비중 (%)": "{:.2f}%"}).set_properties(**{'text-align': 'center'}), use_container_width=True, hide_index=True)

# ####################################################################################################
# # 📊 시뮬레이션 분석 섹션 (최종 수정된 코드)
# ####################################################################################################
st.markdown("---")
st.markdown("<br>", unsafe_allow_html=True)
display_styled_title_box("📊 시뮬레이션 분석 📊", background_color="#f5f5f5", font_size="32px", margin_bottom="20px", padding_y="15px")


if not df_expense_analysis.empty:
    # --- UI 너비 조정을 위한 CSS 주입 (더 정교하게 수정) ---
    # 슬라이더 옆 숫자 입력(st.number_input) 필드의 너비만 조정
    st.markdown("""
        <style>
        /* data-testid가 stNumberInput인 div 내부의 input 요소의 최소 너비를 지정 */
        div[data-testid="stNumberInput"] input {
            min-width: 110px !important;
            width: 110px !important; /* 고정 너비를 주어 일관성 유지 */
        }
        </style>
    """, unsafe_allow_html=True)

    num_months = len(선택_월)
    num_stores = df_expense_analysis['지점명'].nunique()
    divisor = num_months * num_stores if num_months * num_stores > 0 else 1

    base_total_revenue = df_expense_analysis['총매출'].sum() / divisor
    base_costs = {item: df_expense_analysis[item].sum() / divisor for item in ALL_POSSIBLE_EXPENSE_CATEGORIES if item in df_expense_analysis.columns}
    base_total_cost = sum(base_costs.values())
    base_profit = base_total_revenue - base_total_cost
    base_profit_margin = (base_profit / base_total_revenue * 100) if base_total_revenue > 0 else 0

    base_hall_revenue = df_expense_analysis.get('홀매출_총액', 0).sum() / divisor
    base_delivery_takeout_revenue = df_expense_analysis.get('배달매출_총액', 0).sum() / divisor
    base_hall_ratio = (base_hall_revenue / base_total_revenue * 100) if base_total_revenue > 0 else 0

    st.subheader("📋 현재 상태 요약 (지점당 월평균)")
    summary_cols = st.columns(4)
    summary_cols[0].metric("평균 총매출", f"{base_total_revenue:,.0f} 원")
    summary_cols[1].metric("평균 총비용", f"{base_total_cost:,.0f} 원")
    summary_cols[2].metric("평균 순수익", f"{base_profit:,.0f} 원")
    summary_cols[3].metric("평균 순수익률", f"{base_profit_margin:.1f}%")
    st.markdown("---")
    st.subheader("⚙️ 시뮬레이션 조건 설정")

    sim_rev_col, sim_hall_col = st.columns(2)
    sim_rev_col, sim_hall_col = st.columns(2)
    with sim_rev_col:
        # ✅ [요청 반영] format_str="%.0f"로 소수점 제거, 도움말에는 쉼표 서식 적용
        sim_revenue = custom_slider(
            label="예상 월평균 매출 (원)",
            min_value=0.0, max_value=150_000_000.0,
            default_value=base_total_revenue, step=100000.0,
            help_text=f"현재 지점당 월평균 매출: {base_total_revenue:,.0f} 원",
            key="sim_revenue",
            format_str="%.0f"
        )
    with sim_hall_col:
        # ✅ [요청 반영] 소수점 한 자리, +/- 버튼이 있는 숫자 칸 사용
        sim_hall_ratio_pct = custom_slider(
            label="예상 홀매출 비율 (%)",
            min_value=0.0, max_value=100.0,
            default_value=base_hall_ratio, step=0.1,
            help_text=f"현재 홀매출 비율: {base_hall_ratio:.1f}%",
            key="sim_hall_ratio",
            format_str="%.1f" # 소수점 한 자리 지정
        )

    sim_delivery_ratio_pct = 100.0 - sim_hall_ratio_pct
    live_total_revenue_growth = sim_revenue / base_total_revenue if base_total_revenue > 0 else 0
    live_delivery_takeout_revenue_growth = (sim_revenue * (sim_delivery_ratio_pct / 100)) / base_delivery_takeout_revenue if base_delivery_takeout_revenue > 0 else 0

    with st.expander("항목별 비용 상세 조정 (선택)"):
        cost_adjustments = {}
        ordered_cost_items = ['식자재', '소모품', '배달비', '인건비', '광고비', '고정비']
        for i in range(0, len(ordered_cost_items), 2):
            col1, col2 = st.columns(2)
            # 이하는 원본 코드와 동일하게 custom_slider를 사용하도록 유지
            item1 = ordered_cost_items[i]
            if item1 in base_costs:
                with col1:
                    cost_adjustments[item1] = custom_slider(label=f"{item1} 조정률 (%)", min_value=-50.0, max_value=50.0, default_value=0.0, step=0.1, help_text=f"현재 월평균 {item1} 비용: {base_costs.get(item1, 0):,.0f} 원", key=f"slider_{item1}")
                    base_cost_item = base_costs.get(item1, 0)
                    growth_factor = live_total_revenue_growth if item1 in VARIABLE_COST_ITEMS else live_delivery_takeout_revenue_growth if item1 in DELIVERY_SPECIFIC_VARIABLE_COST_ITEMS else 1.0
                    final_sim_cost = base_cost_item * growth_factor * (1 + cost_adjustments[item1] / 100)
                    adjustment_amount = final_sim_cost - base_cost_item
                    sign = "+" if adjustment_amount >= 0 else ""
                    color = "#3D9970" if adjustment_amount >= 0 else "#FF4136"
                    st.markdown(f"<p style='color:{color}; text-align:right; font-size: 0.9rem;'>변동액: {sign}{adjustment_amount:,.0f} 원</p>", unsafe_allow_html=True)
            if i + 1 < len(ordered_cost_items):
                item2 = ordered_cost_items[i+1]
                if item2 in base_costs:
                    with col2:
                        cost_adjustments[item2] = custom_slider(label=f"{item2} 조정률 (%)", min_value=-50.0, max_value=50.0, default_value=0.0, step=0.1, help_text=f"현재 월평균 {item2} 비용: {base_costs.get(item2, 0):,.0f} 원", key=f"slider_{item2}")
                        base_cost_item = base_costs.get(item2, 0)
                        growth_factor = live_total_revenue_growth if item2 in VARIABLE_COST_ITEMS else live_delivery_takeout_revenue_growth if item2 in DELIVERY_SPECIFIC_VARIABLE_COST_ITEMS else 1.0
                        final_sim_cost = base_cost_item * growth_factor * (1 + cost_adjustments[item2] / 100)
                        adjustment_amount = final_sim_cost - base_cost_item
                        sign = "+" if adjustment_amount >= 0 else ""
                        color = "#3D9970" if adjustment_amount >= 0 else "#FF4136"
                        st.markdown(f"<p style='color:{color}; text-align:right; font-size: 0.9rem;'>변동액: {sign}{adjustment_amount:,.0f} 원</p>", unsafe_allow_html=True)

    st.markdown("---")
    royalty_rate = custom_slider(label="👑 로열티 설정 (매출 대비 %)", min_value=0.0, max_value=10.0, default_value=0.0, step=0.1, help_text="전체 예상 매출액 대비 로열티 비율을 설정합니다.", key="royalty_rate")
    st.success(f"예상 로열티 금액 (월): **{sim_revenue * (royalty_rate / 100):,.0f} 원**")
    st.markdown("<br>", unsafe_allow_html=True)


    if st.button("🚀 시뮬레이션 실행", use_container_width=True):
        sim_costs = {}
        for item in VARIABLE_COST_ITEMS:
            if item in base_costs: sim_costs[item] = base_costs[item] * live_total_revenue_growth * (1 + cost_adjustments.get(item, 0) / 100)
        for item in DELIVERY_SPECIFIC_VARIABLE_COST_ITEMS:
            if item in base_costs: sim_costs[item] = base_costs[item] * live_delivery_takeout_revenue_growth * (1 + cost_adjustments.get(item, 0) / 100)
        for item in FIXED_COST_ITEMS:
            if item in base_costs: sim_costs[item] = base_costs[item] * (1 + cost_adjustments.get(item, 0) / 100)
        sim_costs['로열티'] = sim_revenue * (royalty_rate / 100)
        sim_total_cost = sum(sim_costs.values())
        sim_profit = sim_revenue - sim_total_cost
        sim_profit_margin = (sim_profit / sim_revenue * 100) if sim_revenue > 0 else 0

        st.markdown("---")
        st.subheader("📈 시뮬레이션 결과 보고서")
        theme_color_map = {'현재': '#B0A696', '시뮬레이션': '#964F4C'}
        cost_item_color_map = {'식자재': '#964F4C', '인건비': '#7A6C60', '배달비': '#B0A696', '고정비': '#5E534A', '소모품': '#DED3BF', '광고비': '#C0B4A0', '로열티': '#687E8E'}
        row1_col1, row1_col2 = st.columns([2, 1])
        with row1_col1:
            display_styled_title_box("종합 비교", font_size="22px", margin_bottom="20px")
            r1_sub_col1, r1_sub_col2 = st.columns(2)
            with r1_sub_col1:
                df_revenue = pd.DataFrame({'구분': ['현재', '시뮬레이션'], '금액': [base_total_revenue, sim_revenue]})
                fig_revenue = px.bar(df_revenue, x='구분', y='금액', color='구분', text_auto=True, title="총매출 비교", color_discrete_map=theme_color_map)
                fig_revenue.update_traces(texttemplate='%{y:,.0f}', hovertemplate="<b>%{x}</b><br>금액: %{y:,.0f}원<extra></extra>")
                fig_revenue.update_layout(height=550, showlegend=False, yaxis_title="금액(원)", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                st.plotly_chart(fig_revenue, use_container_width=True, key="sim_revenue_bar")
            with r1_sub_col2:
                df_cost = pd.DataFrame({'구분': ['현재', '시뮬레이션'], '금액': [base_total_cost, sim_total_cost]})
                fig_cost = px.bar(df_cost, x='구분', y='금액', color='구분', text_auto=True, title="총비용 비교", color_discrete_map=theme_color_map)
                fig_cost.update_traces(texttemplate='%{y:,.0f}', hovertemplate="<b>%{x}</b><br>금액: %{y:,.0f}원<extra></extra>")
                fig_cost.update_layout(height=550, showlegend=False, yaxis_title="금액(원)", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                st.plotly_chart(fig_cost, use_container_width=True, key="sim_cost_bar")
        with row1_col2:
            display_styled_title_box("순수익률 비교", font_size="22px", margin_bottom="20px")
            df_profit_rate = pd.DataFrame({'구분': ['현재', '시뮬레이션'],'수익률': [base_profit_margin, sim_profit_margin], '수익금액': [base_profit, sim_profit]})
            fig_profit_rate = px.line(df_profit_rate, x='구분', y='수익률', markers=True, text='수익률', custom_data=['수익금액'])
            fig_profit_rate.update_traces(line=dict(color='#687E8E', width=3), marker=dict(size=10, color='#687E8E'), texttemplate='%{text:.1f}%', textposition='top center', hovertemplate="<b>%{x}</b><br>수익률: %{y:.1f}%<br>수익금액: %{customdata[0]:,.0f}원<extra></extra>")
            fig_profit_rate.update_layout(height=550, yaxis_title="순수익률 (%)", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis=dict(range=[-0.5, 1.5]))
            st.plotly_chart(fig_profit_rate, use_container_width=True, key="sim_profit_line")
        st.markdown("---")
        row2_col1, row2_col2 = st.columns(2)
        with row2_col1:
            display_styled_title_box("현재 비용 구조", font_size="22px", margin_bottom="20px")
            r2_c1_sub1, r2_c1_sub2 = st.columns(2)
            base_costs_for_pie = {k: v for k, v in base_costs.items() if v > 0}
            with r2_c1_sub1:
                if base_costs_for_pie:
                    pie_data = pd.DataFrame(list(base_costs_for_pie.items()), columns=['항목', '금액'])
                    fig_pie_base = px.pie(pie_data, names='항목', values='금액')
                    pie_colors = [cost_item_color_map.get(label, '#CCCCCC') for label in pie_data['항목']]
                    fig_pie_base.update_traces(marker=dict(colors=pie_colors), textinfo='percent+label', textfont_size=14, hovertemplate="<b>항목:</b> %{label}<br><b>금액:</b> %{value:,.0f}원<extra></extra>")
                    fig_pie_base.update_layout(height=450, showlegend=False, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                    st.plotly_chart(fig_pie_base, use_container_width=True, key="base_cost_pie")
            with r2_c1_sub2:
                if base_costs_for_pie:
                    df_base_costs = pd.DataFrame(list(base_costs_for_pie.items()), columns=['항목', '금액']).sort_values('금액', ascending=False)
                    fig_bar_base = px.bar(df_base_costs, x='항목', y='금액', text_auto=True, color='항목', color_discrete_map=cost_item_color_map)
                    fig_bar_base.update_traces(texttemplate='%{y:,.0f}', hovertemplate="<b>항목:</b> %{x}<br><b>금액:</b> %{y:,.0f}원<extra></extra>", textangle=0)
                    fig_bar_base.update_layout(height=450, yaxis_title="금액(원)", xaxis_title=None, showlegend=False, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                    st.plotly_chart(fig_bar_base, use_container_width=True, key="base_cost_bar_2")
        with row2_col2:
            display_styled_title_box("시뮬레이션 비용 구조", font_size="22px", margin_bottom="20px")
            r2_c2_sub1, r2_c2_sub2 = st.columns(2)
            sim_costs_for_pie = {k: v for k, v in sim_costs.items() if v > 0}
            with r2_c2_sub1:
                if sim_costs_for_pie:
                    pie_data_sim = pd.DataFrame(list(sim_costs_for_pie.items()), columns=['항목', '금액'])
                    fig_pie_sim = px.pie(pie_data_sim, names='항목', values='금액')
                    pie_colors_sim = [cost_item_color_map.get(label, '#CCCCCC') for label in pie_data_sim['항목']]
                    fig_pie_sim.update_traces(marker=dict(colors=pie_colors_sim), textinfo='percent+label', textfont_size=14, hovertemplate="<b>항목:</b> %{label}<br><b>금액:</b> %{value:,.0f}원<extra></extra>")
                    fig_pie_sim.update_layout(height=450, showlegend=False, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                    st.plotly_chart(fig_pie_sim, use_container_width=True, key="sim_cost_pie")
            with r2_c2_sub2:
                if sim_costs_for_pie:
                    df_sim_costs = pd.DataFrame(list(sim_costs_for_pie.items()), columns=['항목', '금액']).sort_values('금액', ascending=False)
                    fig_bar_sim = px.bar(df_sim_costs, x='항목', y='금액', text_auto=True, color='항목', color_discrete_map=cost_item_color_map)
                    fig_bar_sim.update_traces(texttemplate='%{y:,.0f}', hovertemplate="<b>항목:</b> %{x}<br><b>금액:</b> %{y:,.0f}원<extra></extra>", textangle=0)
                    fig_bar_sim.update_layout(height=450, yaxis_title="금액(원)", xaxis_title=None, showlegend=False, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                    st.plotly_chart(fig_bar_sim, use_container_width=True, key="sim_cost_bar_2")
else:
    st.warning("분석을 위한 데이터가 부족하여 시뮬레이션을 실행할 수 없습니다.")
