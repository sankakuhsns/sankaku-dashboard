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
#      !!! 중요: 엑셀 파일의 고정된 행/열 인덱스 설정 (사용자 지시사항 기반) !!!
# ==============================================================================
# --- Google Drive 설정 ---
DRIVE_FOLDER_ID = '13pZg9s5CKv5nn84Zbnk7L6xmiwF_zluR'

# --- 파일별 설정 상수 ---
OKPOS_DATA_START_ROW = 7
OKPOS_COL_DATE = 0
OKPOS_COL_DAY_OF_WEEK = 1
OKPOS_COL_DINE_IN_SALES = 34
OKPOS_COL_TAKEOUT_SALES = 36
OKPOS_COL_DELIVERY_SALES = 38

DOORI_DATA_START_ROW = 4
DOORI_COL_DATE = 1
DOORI_COL_ITEM = 3
DOORI_COL_AMOUNT = 6

SINSEONG_DATA_START_ROW = 3

OURHOME_DATA_START_ROW = 0
OURHOME_COL_DATE = 1
OURHOME_COL_ITEM = 3
OURHOME_COL_AMOUNT = 11
OURHOME_FILTER_COL = 14

SETTLEMENT_DATA_START_ROW = 3
SETTLEMENT_COL_PERSONNEL_NAME = 1
SETTLEMENT_COL_PERSONNEL_AMOUNT = 2
SETTLEMENT_COL_FOOD_ITEM = 4
SETTLEMENT_COL_FOOD_AMOUNT = 5
SETTLEMENT_COL_SUPPLIES_ITEM = 7
SETTLEMENT_COL_SUPPLIES_AMOUNT = 8
SETTLEMENT_COL_AD_ITEM = 10
SETTLEMENT_COL_AD_AMOUNT = 11
SETTLEMENT_COL_FIXED_ITEM = 13
SETTLEMENT_COL_FIXED_AMOUNT = 14
# ==============================================================================

# ------------------ 1. 페이지 설정 및 스타일 ------------------
st.set_page_config(
    page_title="Sankaku Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)
st.markdown('<meta name="google" content="notranslate">', unsafe_allow_html=True)
st.markdown("""
<style>
/* 전체 스타일 */
html, body, [data-testid="stApp"] { background-color: #f0f0f0 !important; }
[data-testid="block-container"] { padding: 1rem 2rem 0rem; margin-bottom: -7rem; background-color: #ffffff !important; border-radius: 12px; box-shadow: 0 0 8px rgba(0, 0, 0, 0.05); }
[data-testid="stMetric"] { background-color: #ffffff; text-align: center; padding: 15px 0; border-radius: 10px; color: #333333; border: 1px solid #cccccc; box-shadow: 1px 1px 4px rgba(0,0,0,0.05); }
div[data-testid="stMultiSelect"] div[data-baseweb="tag"] { background-color: #e0e0e0 !important; border-color: #b0b0b0 !important; color: #333333 !important; }
.center-login { display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }
.info-box { background-color: #f0f2f6; border-radius: 0.5rem; padding: 1rem; display: flex; align-items: center; justify-content: center; font-size: 1rem; border: 1px solid #e6e6e6; }

/* ✅✅✅ 수정된 KPI 소제목 가운데 정렬 코드 ✅✅✅ */
/* 더 강력한 Flexbox 방식을 사용하여 가운데 정렬을 강제합니다. */
[data-testid="stMetricLabel"] {
    display: flex;
    justify-content: center;
}

</style>
""", unsafe_allow_html=True)

def display_styled_title_box(title_text, background_color="#f5f5f5", font_size="22px", margin_bottom="20px", padding_y="10px"):
    st.markdown(f"""
        <div style="border: 1px solid #cccccc; padding: {padding_y} 10px; border-radius: 5px; background-color: {background_color}; text-align: center; margin-bottom: {margin_bottom};">
            <h3 style="margin: 0; font-size: {font_size}; color: #333333;">{title_text}</h3>
        </div>
    """, unsafe_allow_html=True)

# ------------------ 2. 로그인 및 데이터 로딩 관리 ------------------

def authenticate(password):
    users = st.secrets.get("users", [])
    for user in users:
        if user["password"] == password:
            st.session_state.authenticated = True
            st.session_state.user_name = user["name"]
            st.session_state.allowed_branches = user["allowed_branches"]
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

# ------------------ 3. 데이터 추출 함수들 ------------------

def list_files_recursive(service, folder_id, path_prefix=""):
    files = []
    try:
        results = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="files(id, name, mimeType, parents)"
        ).execute()
        items = results.get('files', [])
        for item in items:
            item_path = f"{path_prefix}/{item['name']}" if path_prefix else item['name']
            if item.get('mimeType') == 'application/vnd.google-apps.folder':
                files.extend(list_files_recursive(service, item['id'], item_path))
            else:
                item['path'] = item_path
                files.append(item)
    except HttpError as e:
        st.error(f"Google Drive 폴더({folder_id}) 접근 오류: {e}. 공유 설정을 확인하세요.")
    return files

def sheetname_to_date(sheetname):
    match = re.match(r"(\d{2})[.\-](\d{1,2})", sheetname)
    if match:
        year = "20" + match.group(1)
        month = match.group(2).zfill(2)
        return f"{year}-{month}-01"
    return ""

def extract_okpos_table(df, 지점명):
    out = []
    for i in range(OKPOS_DATA_START_ROW, df.shape[0]):
        date_cell = df.iloc[i, OKPOS_COL_DATE]
        if pd.isna(date_cell) or str(date_cell).strip() == '' or '합계' in str(date_cell):
            break
        try:
            if isinstance(date_cell, (int, float)):
                날짜 = (pd.to_datetime('1899-12-30') + pd.to_timedelta(date_cell, 'D')).strftime('%Y-%m-%d')
            else:
                날짜 = pd.to_datetime(str(date_cell).replace("소계:", "").strip()).strftime('%Y-%m-%d')
        except Exception:
            continue
        
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
        try:
            날짜 = pd.to_datetime(df.iloc[i, DOORI_COL_DATE]).strftime('%Y-%m-%d')
        except (ValueError, TypeError): continue
        항목2 = str(df.iloc[i, DOORI_COL_ITEM]).strip()
        금액 = pd.to_numeric(df.iloc[i, DOORI_COL_AMOUNT], errors='coerce')
        if pd.notna(금액) and 금액 > 0 and 항목2:
            out.append([날짜, 지점명, '식자재', '두리축산', 항목2, 금액])
    return out

def extract_sinseongmeat(df, 지점명):
    out = []
    for i in range(SINSEONG_DATA_START_ROW, df.shape[0]):
        if str(df.iloc[i, 1]).strip() != '매출': continue
        try:
            날짜 = pd.to_datetime(df.iloc[i, 0]).strftime('%Y-%m-%d')
        except (ValueError, TypeError): continue
        항목2 = str(df.iloc[i, 2]).strip()
        금액 = pd.to_numeric(df.iloc[i, 8], errors='coerce')
        if pd.notna(금액) and 금액 > 0 and 항목2 and not any(k in 항목2 for k in ['[일 계]', '[월계]', '합계']):
            out.append([날짜, 지점명, '식자재', '신성미트', 항목2, 금액])
    return out

def extract_ourhome(df, 지점명):
    out = []
    current_date = None
    for i in range(OURHOME_DATA_START_ROW, df.shape[0]):
        if len(df.columns) <= OURHOME_FILTER_COL or pd.isna(df.iloc[i, OURHOME_FILTER_COL]) or '아워홈' not in str(df.iloc[i, OURHOME_FILTER_COL]): continue
        raw_date_cell = df.iloc[i, OURHOME_COL_DATE]
        if pd.notna(raw_date_cell):
            try:
                current_date = pd.to_datetime(str(raw_date_cell), format='%Y%m%d').strftime('%Y-%m-%d')
            except (ValueError, TypeError): pass
        if not current_date: continue
        항목2 = str(df.iloc[i, OURHOME_COL_ITEM]).strip()
        금액 = pd.to_numeric(df.iloc[i, OURHOME_COL_AMOUNT], errors='coerce')
        if pd.notna(금액) and 금액 > 0 and 항목2 and not any(k in 항목2 for k in ['소계', '합계', '총매입액']):
            out.append([current_date, 지점명, '식자재', '아워홈', 항목2, 금액])
    return out

def extract_kim_myeon_dashima(df, sheetname, 지점명):
    날짜 = sheetname_to_date(sheetname)
    if not 날짜: return []
    out = []
    for i in range(SETTLEMENT_DATA_START_ROW, df.shape[0]):
        item_cell = df.iloc[i, SETTLEMENT_COL_FOOD_ITEM]
        amount_cell = df.iloc[i, SETTLEMENT_COL_FOOD_AMOUNT]
        if pd.isna(item_cell) or pd.isna(amount_cell):
            if pd.isna(item_cell) and pd.isna(amount_cell): break
            continue
        금액 = pd.to_numeric(amount_cell, errors='coerce')
        if pd.isna(금액) or 금액 <= 0: continue
        항목_str = str(item_cell).strip()
        if any(keyword in 항목_str for keyword in ["김", "면", "다시마"]):
            parts = 항목_str.split('(')
            항목1 = parts[0].strip()
            항목2 = ""
            if len(parts) > 1:
                항목2 = parts[1].replace(')', '').strip()
            if 항목1 and 항목2:
                out.append([날짜, 지점명, "식자재", 항목1, 항목2, 금액])
    return out

def extract_from_sheet(df, sheetname, 지점명):
    날짜 = sheetname_to_date(sheetname)
    if not 날짜: return []
    out = []
    for i in range(SETTLEMENT_DATA_START_ROW, df.shape[0]):
        amount_cells = [ df.iloc[i, c] for c in [2, 5, 8, 11, 14] ]
        if all(pd.isna(cell) for cell in amount_cells): break
        
        이름 = df.iloc[i, SETTLEMENT_COL_PERSONNEL_NAME]
        금액 = pd.to_numeric(df.iloc[i, SETTLEMENT_COL_PERSONNEL_AMOUNT], errors='coerce')
        if pd.notna(이름) and pd.notna(금액) and 금액 > 0: out.append([날짜, 지점명, "지출", "인건비", str(이름).strip(), 금액])
        
        항목 = df.iloc[i, SETTLEMENT_COL_FOOD_ITEM]
        금액 = pd.to_numeric(df.iloc[i, SETTLEMENT_COL_FOOD_AMOUNT], errors='coerce')
        if pd.notna(항목) and pd.notna(금액) and 금액 > 0: out.append([날짜, 지점명, "지출", "식자재", str(항목).strip(), 금액])

        항목 = df.iloc[i, SETTLEMENT_COL_SUPPLIES_ITEM]
        금액 = pd.to_numeric(df.iloc[i, SETTLEMENT_COL_SUPPLIES_AMOUNT], errors='coerce')
        if pd.notna(항목) and pd.notna(금액) and 금액 > 0: out.append([날짜, 지점명, "지출", "소모품", str(항목).strip(), 금액])
        
        항목 = df.iloc[i, SETTLEMENT_COL_AD_ITEM]
        금액 = pd.to_numeric(df.iloc[i, SETTLEMENT_COL_AD_AMOUNT], errors='coerce')
        if pd.notna(항목) and pd.notna(금액) and 금액 > 0: out.append([날짜, 지점명, "지출", "광고비", str(항목).strip(), 금액])

        항목 = df.iloc[i, SETTLEMENT_COL_FIXED_ITEM]
        금액 = pd.to_numeric(df.iloc[i, SETTLEMENT_COL_FIXED_AMOUNT], errors='coerce')
        if pd.notna(항목) and pd.notna(금액) and 금액 > 0:
            항목_str = str(항목).strip()
            항목1 = "배달비" if "배달대행" in 항목_str or "배달수수료" in 항목_str else "고정비"
            out.append([날짜, 지점명, "지출", 항목1, 항목_str, 금액])
    return out

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
                st.warning(f"😥 '{file_path}' 파일 처리 중 오류 발생")
                st.code(traceback.format_exc())
        
        if not all_rows: return pd.DataFrame(), {}, {}
        
        df_통합 = pd.DataFrame(all_rows, columns=['날짜', '지점명', '분류', '항목1', '항목2', '금액'])
        df_통합['금액'] = pd.to_numeric(df_통합['금액'], errors='coerce')
        df_통합.dropna(subset=['금액', '날짜'], inplace=True)
        df_통합['날짜'] = pd.to_datetime(df_통합['날짜'], errors='coerce')
        df_통합.dropna(subset=['날짜'], inplace=True)
        df_통합 = df_통합[df_통합['금액'] > 0].copy()
        
        return df_통합, file_counts, processed_rows
    except Exception as e:
        st.error(f"Google Drive 데이터 로딩 중 심각한 오류가 발생했습니다: {e}")
        return pd.DataFrame(), {}, {}

# ==================================================================
#                       메인 앱 실행 로직
# ==================================================================

# --- 1. 세션 상태 초기화 ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.user_name = ""
    st.session_state.allowed_branches = []
    # 데이터와 로딩 상태를 저장할 공간 초기화
    st.session_state.df_all_branches = None
    st.session_state.file_counts = None
    st.session_state.processed_rows = None

# --- 2. 로그인 화면 표시 ---
if not st.session_state.authenticated:
    show_login_screen()

# --- 3. 최초 데이터 로딩 (로그인 후 1회만 실행) ---
# 세션에 데이터가 없을 때만 로딩 프로세스를 실행
if st.session_state.df_all_branches is None:
    st.toast(f'{st.session_state.user_name}님, 환영합니다!', icon='🎉')
    time.sleep(0.5)
    
    loading_message = "모든 지점의 데이터를 로딩 중입니다..."
    if "all" not in st.session_state.allowed_branches:
        loading_message = f'{", ".join(st.session_state.allowed_branches)} 지점의 데이터를 로딩 중입니다...'

    with st.spinner(loading_message):
        # 데이터 로딩 함수를 호출하고 결과를 세션에 저장
        df_all, counts, rows = load_all_data_from_drive()
        st.session_state.df_all_branches = df_all
        st.session_state.file_counts = counts
        st.session_state.processed_rows = rows
        st.rerun() # 데이터를 세션에 저장한 후 UI를 다시 그리기 위해 재실행

# --- 4. 데이터 준비 및 필터링 ---
df_all_branches = st.session_state.df_all_branches
file_counts = st.session_state.file_counts
processed_rows = st.session_state.processed_rows

if df_all_branches is None or df_all_branches.empty:
    st.error("처리할 데이터가 없습니다. Google Drive 폴더, 파일 내용, 공유 설정을 확인해주세요.")
    st.stop()

# 권한에 따른 데이터 필터링
if "all" in st.session_state.allowed_branches:
    df = df_all_branches.copy()
else:
    df = df_all_branches[df_all_branches['지점명'].isin(st.session_state.allowed_branches)].copy()

# ✅✅✅ 수정: 데이터 후처리를 사이드바보다 먼저 실행 ✅✅✅
# --- 데이터 후처리 ---
# '월'과 '요일' 열을 먼저 만들어야 사이드바에서 사용할 수 있습니다.
if '날짜' in df.columns:
    df['월'] = df['날짜'].dt.strftime('%y년 %m월')
    df['요일'] = df['날짜'].dt.day_name().map({'Monday': '월요일', 'Tuesday': '화요일', 'Wednesday': '수요일', 'Thursday': '목요일', 'Friday': '금요일', 'Saturday': '토요일', 'Sunday': '일요일'})
    df['항목1'] = df['항목1'].fillna('기타')
    df['항목2'] = df['항목2'].fillna('기타')
else:
    st.error("'날짜' 열을 찾을 수 없어 후처리를 진행할 수 없습니다. 데이터 로딩을 확인해주세요.")
    st.stop()

# --- 5. 사이드바 UI ---
with st.sidebar:
    st.title('📊 대시보드')
    st.info(f"**로그인 계정 :**\n\n{st.session_state.user_name}")
    st.markdown("---")
    
    지점목록 = sorted(df['지점명'].unique())
    월목록 = sorted(df['월'].unique(), reverse=True)
    
    선택_지점 = st.multiselect("📍 지점 선택", 지점목록, default=지점목록)
    선택_월 = st.multiselect("🗓️ 월 선택", 월목록, default=월목록)

# --- 6. 메인 화면 UI ---
df_filtered = df[df['지점명'].isin(선택_지점) & df['월'].isin(선택_월)]

if df_filtered.empty:
    st.warning("선택하신 조건에 해당하는 데이터가 없습니다. 필터를 조정해주세요.")
    st.stop()

# --- 데이터 후처리 ---
df['월'] = df['날짜'].dt.strftime('%y년 %m월')
df['요일'] = df['날짜'].dt.day_name().map({'Monday': '월요일', 'Tuesday': '화요일', 'Wednesday': '수요일', 'Thursday': '목요일', 'Friday': '금요일', 'Saturday': '토요일', 'Sunday': '일요일'})
df['항목1'] = df['항목1'].fillna('기타')
df['항목2'] = df['항목2'].fillna('기타')

# --- 차트 색상 및 변수 정의 ---
chart_colors_palette = ['#964F4C', '#7A6C60', '#B0A696', '#5E534A', '#DED3BF', '#C0B4A0', '#F0E6D8', '#687E8E']
매출_항목1_unique = df[df['분류'] == '매출']['항목1'].unique() if not df[df['분류'] == '매출'].empty else []
color_map_항목1_매출 = {cat: chart_colors_palette[i % len(chart_colors_palette)] for i, cat in enumerate(매출_항목1_unique)}

지출_항목1_unique = df[df['분류'] == '지출']['항목1'].unique() if not df[df['분류'] == '지출'].empty else []
color_map_항목1_지출 = {cat: chart_colors_palette[i % len(chart_colors_palette)] for i, cat in enumerate(지출_항목1_unique)}

color_map_월 = {month: chart_colors_palette[i % len(chart_colors_palette)] for i, month in enumerate(sorted(df['월'].unique()))}
color_map_요일 = {day: chart_colors_palette[i % len(chart_colors_palette)] for i, day in enumerate(['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일'])}

VARIABLE_COST_ITEMS = ['식자재', '소모품']
DELIVERY_SPECIFIC_VARIABLE_COST_ITEMS = ['배달비']
FIXED_COST_ITEMS = ['인건비', '광고비', '고정비']
all_possible_expense_categories_for_analysis = list(set(VARIABLE_COST_ITEMS + DELIVERY_SPECIFIC_VARIABLE_COST_ITEMS + FIXED_COST_ITEMS))

# --- 데이터 분리 ---
매출 = df_filtered[df_filtered['분류'] == '매출'].copy()
지출 = df_filtered[df_filtered['분류'] == '지출'].copy()
식자재_분석용_df = df_filtered[
    (df_filtered['분류'] == '식자재') & 
    (~df_filtered['항목2'].astype(str).str.contains("소계|총계|합계|전체|총액|이월금액|일계", na=False, regex=True))
].copy() 

# ------------------ 6. 헤더 및 KPI ------------------
if not df_filtered.empty and '날짜' in df_filtered.columns:
    분석최소일 = df_filtered['날짜'].min().strftime('%Y-%m-%d')
    분석최대일 = df_filtered['날짜'].max().strftime('%Y-%m-%d')
else:
    분석최소일 = "N/A"
    분석최대일 = "N/A"

st.markdown(f"""
<div style='text-align: center; margin-bottom: 1rem; padding: 3rem 2rem; border-radius: 12px; background-color: #ffffff; border: 1px solid #cccccc; box-shadow: 0 4px 12px rgba(0,0,0,0.05);'>
    <span style='color: #333333; font-size: 60px; font-weight: 700; letter-spacing: -1px;'>산카쿠 분석 시스템</span>
</div>
""", unsafe_allow_html=True)

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
        st.warning("선택된 필터 조건에 해당하는 매출 데이터가 없어 '매출 항목 비율' 차트를 표시할 수 없습니다.")
    else:
        pie1 = px.pie(
            매출.groupby('항목1')['금액'].sum().reset_index(),
            names='항목1',
            values='금액',
            hole=0,
            color='항목1',
            color_discrete_map=color_map_항목1_매출
        )
        unique_categories_pie1 = pie1.data[0].labels
        color_map_for_pie1_traces = {cat: color_map_항목1_매출.get(cat, chart_colors_palette[0]) for cat in unique_categories_pie1}
        
        pie1.update_traces(
            marker=dict(
                colors=[color_map_for_pie1_traces.get(cat) for cat in pie1.data[0].labels],
                line=dict(color='#cccccc', width=1)
            ),
            hovertemplate="항목 : %{label}<br>금액: %{value:,.0f}원<extra></extra>",
            textinfo='label+percent',
            texttemplate='%{label}<br>%{percent}',
            textfont_size=15
        )
        pie1.update_layout(
            legend=dict(
                orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5, font=dict(color='#555555')
            ),
            height=550, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(pie1, use_container_width=True)

with col_chart2:
    display_styled_title_box("매출 항목 월별 트렌드", background_color="#f5f5f5", font_size="22px", margin_bottom="20px")
    if 매출.empty:
        st.warning("선택된 필터 조건에 해당하는 매출 데이터가 없어 '매출 항목 월별 트렌드' 차트를 표시할 수 없습니다.")
    else:
        line = px.line(
            매출.groupby(['월','항목1'])['금액'].sum().reset_index(),
            x='월', y='금액', color='항목1', markers=True,
            color_discrete_map=color_map_항목1_매출
        )
        unique_categories_line = 매출['항목1'].unique()
        color_map_line = {cat: color_map_항목1_매출.get(cat, chart_colors_palette[0]) for cat in unique_categories_line}
        line.for_each_trace(lambda t: t.update(marker_color=color_map_line.get(t.name), line_color=color_map_line.get(t.name)))


        line.update_traces(hovertemplate="항목 : %{fullData.name}<br>금액: %{y:,.0f}원<extra></extra>")
        line.update_layout(
            height=550,
            legend=dict(
                title_text='', orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5, font=dict(color='#555555')
            ),
            xaxis=dict(tickfont=dict(color='#555555')),
            yaxis=dict(tickfont=dict(color='#555555')),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(line, use_container_width=True)

st.markdown("---")

col_chart3, col_chart4, col_chart5 = st.columns(3)

with col_chart3:
    display_styled_title_box("지점별 매출 비교", background_color="#f5f5f5", font_size="22px", margin_bottom="20px")
    if 매출.empty:
        st.warning("선택된 필터 조건에 해당하는 매출 데이터가 없어 '지점별 매출 비교' 차트를 표시할 수 없습니다.")
    else:
        매출_지점별 = 매출.groupby('지점명')['금액'].sum().reset_index()
        min_금액 = 매출_지점별['금액'].min()
        max_금액 = 매출_지점별['금액'].max()
        y_axis_start = min_금액 * 0.9 if min_금액 > 0 else 0
        y_axis_end = max_금액 * 1.1
        if max_금액 - min_금액 < max_금액 * 0.1 and max_금액 > 0:
             y_axis_start = max(0, min_금액 * 0.8)

        bar1 = px.bar(
            매출_지점별, x='지점명', y='금액', text='금액',
        )
        bar1.update_traces(
            texttemplate='%{text:,.0f}원', textposition='outside',
            hovertemplate="지점: %{x}<br>금액: %{y:,.0f}원<extra></extra>",
            marker_color='#555555',
            marker_line_color='#cccccc', marker_line_width=1
        )
        bar1.update_layout(
            height=550, xaxis_tickangle=0, bargap=0.5,
            xaxis=dict(tickfont=dict(color='#555555')),
            yaxis=dict(tickfont=dict(color='#555555'), range=[y_axis_start, y_axis_end]),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(bar1, use_container_width=True)

with col_chart4:
    display_styled_title_box("월별 매출 비율", background_color="#f5f5f5", font_size="22px", margin_bottom="20px")
    if 매출.empty:
        st.warning("선택된 필터 조건에 해당하는 매출 데이터가 없어 '월별 매출 비율' 차트를 표시할 수 없습니다.")
    else:
        pie2 = px.pie(
            매출.groupby('월')['금액'].sum().reset_index(),
            names='월', values='금액',
            color='월',
            color_discrete_map=color_map_월
        )
        unique_categories_pie2 = pie2.data[0].labels
        color_map_for_pie2_traces = {cat: color_map_월.get(cat, chart_colors_palette[0]) for cat in unique_categories_pie2}
        pie2.update_traces(
            marker=dict(
                colors=[color_map_for_pie2_traces.get(cat) for cat in pie2.data[0].labels],
                line=dict(color='#cccccc', width=1)
            ),
            hovertemplate="월: %{label}<br>금액: %{value:,.0f}원<extra></extra>",
            textinfo='label+percent', texttemplate='%{label}<br>%{percent}', textfont_size=15
        )
        pie2.update_layout(
            legend=dict(
                orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5, font=dict(color='#555555')
            ),
            height=550, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(pie2, use_container_width=True)

with col_chart5:
    display_styled_title_box("요일별 매출 비율", background_color="#f5f5f5", font_size="22px", margin_bottom="20px")
    if 매출.empty:
        st.warning("선택된 필터 조건에 해당하는 매출 데이터가 없어 '요일별 매출 비율' 차트를 표시할 수 없습니다.")
    else:
        ordered_weekdays = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']
        매출_요일별 = 매출.groupby('요일')['금액'].sum().reset_index()
        매출_요일별['요일'] = pd.Categorical(매출_요일별['요일'], categories=ordered_weekdays, ordered=True)
        매출_요일별 = 매출_요일별.sort_values('요일')

        pie3 = px.pie(
            매출_요일별, names='요일', values='금액',
            color='요일',
            color_discrete_map=color_map_요일
        )
        unique_categories_pie3 = 매출_요일별['요일'].unique()
        color_map_for_pie3_traces = {cat: color_map_요일.get(cat, chart_colors_palette[0]) for cat in unique_categories_pie3}
        pie3.update_traces(
            marker=dict(
                colors=[color_map_for_pie3_traces.get(cat) for cat in pie3.data[0].labels],
                line=dict(color='#cccccc', width=1)
            ),
            hovertemplate="요일: %{label}<br>금액: %{value:,.0f}원<extra></extra>",
            textinfo='label+percent', texttemplate='%{label}<br>%{percent}', textfont_size=15
        )
        pie3.update_layout(
            legend=dict(
                orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5, font=dict(color='#555555'),
                traceorder='normal'
            ),
            height=550, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(pie3, use_container_width=True)

####################################################################################################
# 💸 지출 분석 섹션
####################################################################################################
st.markdown("---")
st.markdown("<br>", unsafe_allow_html=True)
display_styled_title_box(
    "💸 지출 분석 💸",
    background_color="#f5f5f5", font_size="32px", margin_bottom="20px", padding_y="15px"
)

# --- 분석용 데이터프레임 생성 ---
if not 매출.empty:
    총매출_월별_지점별 = 매출.groupby(['지점명', '월'])['금액'].sum().reset_index().rename(columns={'금액': '총매출'})
    
    # ✅ 수정: '배달매출'과 '포장매출'을 함께 집계
    배달매출_월별_지점별 = 매출[매출['항목1'].isin(['배달매출', '포장매출'])].groupby(['지점명', '월'])['금액'].sum().reset_index().rename(columns={'금액': '배달매출_총액'})
    
    # ✅ 수정: '홀매출'만 집계하도록 변경
    홀매출_월별_지점별 = 매출[매출['항목1'] == '홀매출'].groupby(['지점명', '월'])['금액'].sum().reset_index().rename(columns={'금액': '홀매출_총액'})
    
    지출_항목1별_월별_지점별_raw = pd.DataFrame(columns=['지점명', '월'] + all_possible_expense_categories_for_analysis)
    if not 지출.empty:
        try:
            지출_항목1별_월별_지점별_raw = 지출.groupby(['지점명', '월', '항목1'])['금액'].sum().unstack(level='항목1', fill_value=0).reset_index()
            for col in all_possible_expense_categories_for_analysis:
                if col not in 지출_항목1별_월별_지점별_raw.columns:
                    지출_항목1별_월별_지점별_raw[col] = 0
        except Exception as e:
            st.warning(f"DEBUG: 지출 피벗 테이블 생성 중 오류 발생: {e}")

    cols_to_reindex_지출_pivot = ['지점명', '월'] + [item for item in all_possible_expense_categories_for_analysis if item not in ['지점명', '월']]
    지출_항목1별_월별_지점별 = 지출_항목1별_월별_지점별_raw.reindex(columns=cols_to_reindex_지출_pivot, fill_value=0)
    
    df_expense_analysis = pd.merge(총매출_월별_지점별, 배달매출_월별_지점별, on=['지점명', '월'], how='left').fillna(0)
    # ✅ 수정: merge 대상을 '홀매출_총액'으로 변경
    df_expense_analysis = pd.merge(df_expense_analysis, 홀매출_월별_지점별, on=['지점명', '월'], how='left').fillna(0)
    df_expense_analysis = pd.merge(df_expense_analysis, 지출_항목1별_월별_지점별, on=['지점명', '월'], how='left').fillna(0)
else:
    df_expense_analysis = pd.DataFrame()


# --- 1줄 홀매출 지출항목 비율(원형차트), 홀매출 지출항목 월별지출 선그래프 ---
col_h_exp1, col_h_exp2 = st.columns(2)

with col_h_exp1:
    display_styled_title_box("홀매출 지출 항목 비율", font_size="22px", margin_bottom="20px")
    
    # 홀매출 지출 항목 정의: 식자재, 소모품 (변동비) + 인건비, 광고비, 고정비 (고정비)
    # 배달비는 제외됩니다.
    홀매출_지출_원형_대상_항목 = [item for item in (VARIABLE_COST_ITEMS + FIXED_COST_ITEMS) if item in df_expense_analysis.columns]
    
    # DAX 방식: 각 지출 항목에 홀매출 비중을 곱한 후 총합 계산
    pie_data_list_h = []
    
    valid_총매출_series = df_expense_analysis['총매출'].replace(0, 1) # 0으로 나누는 것을 방지
    홀매출_분석용_비중_series = (df_expense_analysis['홀_포장_매출_총액'] / valid_총매출_series).fillna(0)
    홀매출_분석용_비중_series.replace([float('inf'), -float('inf')], 0, inplace=True)

    df_expense_analysis['홀매출_비중_계산용'] = 홀매출_분석용_비중_series

    for item in 홀매출_지출_원형_대상_항목: # 홀매출_지출_원형_대상_항목 사용
        allocated_amount = (df_expense_analysis[item] * df_expense_analysis['홀매출_비중_계산용']).sum()
        if allocated_amount > 0:
            pie_data_list_h.append({'항목1': item, '금액': allocated_amount})
    
    pie_data_h = pd.DataFrame(pie_data_list_h)
    
    if pie_data_h.empty or pie_data_h['금액'].sum() == 0 or pie_data_h['금액'].isnull().all():
         st.warning("선택된 필터 조건에 해당하는 홀매출 지출 데이터가 없어 '홀매출 지출 항목 비율' 차트를 표시할 수 없습니다.")
    else:
        pie_expense_h1 = px.pie(
            pie_data_h,
            names='항목1', values='금액', hole=0,
            color='항목1', color_discrete_map={category: color_map_항목1_지출[category] if category in color_map_항목1_지출 else chart_colors_palette[0] for category in pie_data_h['항목1'].unique()}
        )
        # 차트 색상 직접 지정 (추가)
        unique_categories_pie_h1 = pie_data_h['항목1'].unique()
        color_map_pie_h1 = {cat: chart_colors_palette[i % len(chart_colors_palette)] for i, cat in enumerate(unique_categories_pie_h1)}
        pie_expense_h1.update_traces(
            marker=dict( # 'marker' dict를 한 번만 정의
                colors=[color_map_pie_h1.get(cat) for cat in pie_data_h['항목1']], # .get() 사용하여 키 없을 때 오류 방지
                line=dict(color='#cccccc', width=1) # 라인 속성
            ),
            hovertemplate="항목 : %{label}<br>금액: %{value:,.0f}원<extra></extra>",
            textinfo='label+percent', texttemplate='%{label}<br>%{percent}', textfont_size=15
        )
        pie_expense_h1.update_layout(
            legend=dict(orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5, font=dict(color='#555555')),
            height=550, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(pie_expense_h1, use_container_width=True)

with col_h_exp2:
    display_styled_title_box("홀매출 지출 항목 월별 지출", font_size="22px", margin_bottom="20px")
    
    df_홀지출_월별_data_list = []
    
    valid_총매출_for_line_h_series = df_expense_analysis['총매출'].replace(0, 1)
    홀매출_분석용_비중_series_for_line = (df_expense_analysis['홀_포장_매출_총액'] / valid_총매출_for_line_h_series).fillna(0)
    홀매출_분석용_비중_series_for_line.replace([float('inf'), -float('inf')], 0, inplace=True)

    df_expense_analysis['홀매출_비중_계산용'] = 홀매출_분석용_비중_series_for_line

    for item in 홀매출_지출_원형_대상_항목: # 홀매출_지출_원형_대상_항목 사용
        if item in df_expense_analysis.columns:
            df_temp = df_expense_analysis.groupby('월').apply(lambda x: (x[item] * x['홀매출_비중_계산용']).sum()).reset_index(name='금액')
            df_홀지출_월별_data_list.append(df_temp.assign(항목1=item))
    
    df_홀지출_월별_data = pd.concat(df_홀지출_월별_data_list, ignore_index=True) if df_홀지출_월별_data_list else pd.DataFrame(columns=['월', '항목1', '금액'])

    if df_홀지출_월별_data.empty or df_홀지출_월별_data['금액'].sum() == 0 or df_홀지출_월별_data['금액'].isnull().all():
        st.warning("선택된 필터 조건에 해당하는 홀매출 지출 데이터가 없어 '홀매출 월별 지출' 차트를 표시할 수 없습니다.")
    else:
        line_expense_h2 = px.line(
            df_홀지출_월별_data,
            x='월', y='금액', color='항목1', markers=True, # 항목1 사용
            color_discrete_map={category: color_map_항목1_지출.get(category, chart_colors_palette[0]) for category in df_홀지출_월별_data['항목1'].unique()}
        )
        # 차트 색상 직접 지정 (추가)
        unique_categories_line_h2 = df_홀지출_월별_data['항목1'].unique()
        color_map_line_h2 = {cat: chart_colors_palette[i % len(chart_colors_palette)] for i, cat in enumerate(unique_categories_line_h2)}
        line_expense_h2.for_each_trace(lambda t: t.update(marker_color=color_map_line_h2.get(t.name), line_color=color_map_line_h2.get(t.name)))

        line_expense_h2.update_traces(hovertemplate="항목 : %{fullData.name}<br>금액: %{y:,.0f}원<extra></extra>")
        line_expense_h2.update_layout(
            height=550,
            legend=dict(title_text='', orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5, font=dict(color='#555555')),
            xaxis=dict(tickfont=dict(color='#555555')), yaxis=dict(tickfont=dict(color='#555555')),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(line_expense_h2, use_container_width=True)

# --- 2줄 배달매출 지출항목 비율(원형차트), 배달매출 지출항목 월별지출 선그래프 ---
st.markdown("---") # 지출 분석 내 구분선
col_d_exp1, col_d_exp2 = st.columns(2)

with col_d_exp1:
    display_styled_title_box("배달매출 지출 항목 비율", font_size="22px", margin_bottom="20px")
    
    배달매출_지출_원형_데이터_list = []
    
    # 1. 배달비 (배달매출 전액 반영)
    delivery_specific_cols_present = [item for item in DELIVERY_SPECIFIC_VARIABLE_COST_ITEMS if item in df_expense_analysis.columns]
    delivery_specific_sum = df_expense_analysis[delivery_specific_cols_present].sum().sum()
    
    if delivery_specific_sum > 0:
        배달매출_지출_원형_데이터_list.append({'항목1': '배달비', '금액': delivery_specific_sum}) # '배달수수료' -> '배달비'
    
    # 2. 기타 변동비 및 고정비 (배달매출 비중만큼 배분)
    # 기타 지출 항목들: 식자재, 소모품 (변동비) + 인건비, 광고비, 고정비 (고정비)
    기타_지출_항목들_배달관련_원형 = [item for item in (VARIABLE_COST_ITEMS + FIXED_COST_ITEMS) if item in df_expense_analysis.columns]
    
    sum_기타_배달_지출 = 0
    if not df_expense_analysis.empty and '총매출' in df_expense_analysis.columns and '배달매출_총액' in df_expense_analysis.columns:
        valid_총매출_비율_d = df_expense_analysis['총매출'].replace(0, 1)
        배달매출_비중 = (df_expense_analysis['배달매출_총액'] / valid_총매출_비율_d).fillna(0)
        배달매출_비중.replace([float('inf'), -float('inf')], 0, inplace=True)

        for item in 기타_지출_항목들_배달관련_원형:
            allocated_amount = (df_expense_analysis[item] * 배달매출_비중).sum()
            if allocated_amount > 0:
                배달매출_지출_원형_데이터_list.append({'항목1': item, '금액': allocated_amount})
    
    pie_data_d = pd.DataFrame(배달매출_지출_원형_데이터_list)

    if pie_data_d.empty or pie_data_d['금액'].sum() == 0 or pie_data_d['금액'].isnull().all():
        st.warning("선택된 필터 조건에 해당하는 배달매출 지출 데이터가 없어 '배달매출 지출 항목 비율' 차트를 표시할 수 없습니다.")
    else:
        pie_expense_d1 = px.pie(
            pie_data_d,
            names='항목1', values='금액', hole=0,
            color='항목1', color_discrete_map={category: color_map_항목1_지출[category] if category in color_map_항목1_지출 else chart_colors_palette[0] for category in pie_data_d['항목1'].unique()}
        )
        # 차트 색상 직접 지정 (추가)
        unique_categories_pie_d1 = pie_data_d['항목1'].unique()
        color_map_pie_d1 = {cat: chart_colors_palette[i % len(chart_colors_palette)] for i, cat in enumerate(unique_categories_pie_d1)}
        pie_expense_d1.update_traces(
            marker=dict(colors=[color_map_pie_d1.get(cat) for cat in pie_data_d['항목1'] if cat in color_map_pie_d1]),
            hovertemplate="항목 : %{label}<br>금액: %{value:,.0f}원<extra></extra>",
            textinfo='label+percent', texttemplate='%{label}<br>%{percent}', textfont_size=15,
            marker_line=dict(color='#cccccc', width=1)
        )
        pie_expense_d1.update_layout(
            legend=dict(orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5, font=dict(color='#555555')),
            height=550, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(pie_expense_d1, use_container_width=True)

with col_d_exp2:
    display_styled_title_box("배달매출 지출 항목 월별 지출", font_size="22px", margin_bottom="20px")
    
    df_temp_line_d_list = []
    
    # 1. 배달비 (월별)
    delivery_specific_cols_present_line = [item for item in DELIVERY_SPECIFIC_VARIABLE_COST_ITEMS if item in df_expense_analysis.columns]
    for item in delivery_specific_cols_present_line:
        df_temp = df_expense_analysis.groupby('월')[item].sum().reset_index(name='금액')
        df_temp_line_d_list.append(df_temp.assign(항목1=item))
    
    # 2. 기타 변동비 및 고정비 (월별, 배달매출 비중에 따라 배분)
    기타_지출_항목들_for_line = [item for item in (VARIABLE_COST_ITEMS + FIXED_COST_ITEMS) if item in df_expense_analysis.columns]

    if 기타_지출_항목들_for_line and not df_expense_analysis.empty and '총매출' in df_expense_analysis.columns and '배달매출_총액' in df_expense_analysis.columns:
        df_temp_기타_지출_월별 = df_expense_analysis[['지점명', '월', '총매출', '배달매출_총액'] + 기타_지출_항목들_for_line].copy()
        
        valid_총매출_비율_line = df_temp_기타_지출_월별['총매출'].replace(0, 1)
        배달매출_비중_line = (df_temp_기타_지출_월별['배달매출_총액'] / valid_총매출_비율_line).fillna(0)
        배달매출_비중_line.replace([float('inf'), -float('inf')], 0, inplace=True)

        for item in 기타_지출_항목들_for_line:
            df_temp_기타_지출_월별[f'{item}_배달_배분'] = df_temp_기타_지출_월별[item] * 배달매출_비중_line
            df_temp_line_d_list.append(df_temp_기타_지출_월별.groupby('월')[f'{item}_배달_배분'].sum().reset_index(name='금액').assign(항목1=item))

    df_temp_line_d = pd.concat(df_temp_line_d_list, ignore_index=True) if df_temp_line_d_list else pd.DataFrame(columns=['월', '항목1', '금액'])
    
    if df_temp_line_d.empty or df_temp_line_d['금액'].sum() == 0 or df_temp_line_d['금액'].isnull().all():
        st.warning("선택된 필터 조건에 해당하는 배달매출 지출 데이터가 없어 '배달매출 지출 항목 월별 지출' 차트를 표시할 수 없습니다.")
    else:
        line_expense_d2 = px.line(
            df_temp_line_d,
            x='월', y='금액', color='항목1', markers=True, # 항목1 사용
            color_discrete_map={category: color_map_항목1_지출.get(category, chart_colors_palette[0]) for category in df_temp_line_d['항목1'].unique()}
        )
        # 차트 색상 직접 지정 (추가)
        unique_categories_line_d2 = df_temp_line_d['항목1'].unique()
        color_map_line_d2 = {cat: chart_colors_palette[i % len(chart_colors_palette)] for i, cat in enumerate(unique_categories_line_d2)}
        line_expense_d2.for_each_trace(lambda t: t.update(marker_color=color_map_line_d2.get(t.name), line_color=color_map_line_d2.get(t.name)))

        line_expense_d2.update_traces(hovertemplate="항목 : %{fullData.name}<br>금액: %{y:,.0f}원<extra></extra>")
        line_expense_d2.update_layout(
            height=550,
            legend=dict(title_text='', orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5, font=dict(color='#555555')),
            xaxis=dict(tickfont=dict(color='#555555')), yaxis=dict(tickfont=dict(color='#555555')),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(line_expense_d2, use_container_width=True)


####################################################################################################
# 💰 순수익 분석 섹션
####################################################################################################
st.markdown("---")
st.markdown("<br>", unsafe_allow_html=True)
display_styled_title_box(
    "💰 순수익 분석 💰",
    background_color="#f5f5f5", font_size="32px", margin_bottom="20px", padding_y="15px")

# --- 순수익 분석 데이터 준비 (재계산) ---
if not df_expense_analysis.empty and '총매출' in df_expense_analysis.columns:
    df_profit_analysis_recalc = df_expense_analysis.copy() # df_expense_analysis는 모든 필요한 컬럼을 포함하고 있음

    # 총지출 (모든 지출 항목의 합계)
    df_profit_analysis_recalc['총지출'] = df_profit_analysis_recalc[[item for item in all_possible_expense_categories_for_analysis if item in df_profit_analysis_recalc.columns]].sum(axis=1)
    df_profit_analysis_recalc['총순수익'] = df_profit_analysis_recalc['총매출'] - df_profit_analysis_recalc['총지출']
    df_profit_analysis_recalc['총순수익률'] = (df_profit_analysis_recalc['총순수익'] / df_profit_analysis_recalc['총매출'] * 100).fillna(0)
    df_profit_analysis_recalc.loc[df_profit_analysis_recalc['총매출'] == 0, '총순수익률'] = 0


# 홀 순수익 계산 (홀매출 = 홀_포장_매출_총액)
df_profit_analysis_recalc['홀매출_분석용'] = df_profit_analysis_recalc['홀_포장_매출_총액']

df_profit_analysis_recalc['홀_변동비_계산'] = 0
valid_총매출 = df_profit_analysis_recalc['총매출'].replace(0, 1e-9) # 0으로 나누는 것을 방지
홀매출_비중_for_변동비 = (df_profit_analysis_recalc['홀매출_분석용'] / valid_총매출).fillna(0)
홀매출_비중_for_변동비.replace([float('inf'), -float('inf')], 0, inplace=True)


for item in VARIABLE_COST_ITEMS: # 식자재, 소모품 등
    if item in df_profit_analysis_recalc.columns:
        df_profit_analysis_recalc['홀_변동비_계산'] += df_profit_analysis_recalc[item] * 홀매출_비중_for_변동비

df_profit_analysis_recalc['홀_고정비_계산'] = 0
for item in FIXED_COST_ITEMS: # 인건비, 광고비, 고정비
    if item in df_profit_analysis_recalc.columns:
        df_profit_analysis_recalc['홀_고정비_계산'] += df_profit_analysis_recalc[item] * 홀매출_비중_for_변동비 # 고정비도 매출 비중에 따라 배분

df_profit_analysis_recalc['홀순수익'] = df_profit_analysis_recalc['홀매출_분석용'] - df_profit_analysis_recalc['홀_변동비_계산'] - df_profit_analysis_recalc['홀_고정비_계산']
df_profit_analysis_recalc['홀순수익률'] = (df_profit_analysis_recalc['홀순수익'] / df_profit_analysis_recalc['홀매출_분석용'] * 100).fillna(0)
df_profit_analysis_recalc.loc[df_profit_analysis_recalc['홀매출_분석용'] == 0, '홀순수익률'] = 0


# 배달 순수익 계산
df_profit_analysis_recalc['배달매출_분석용'] = df_profit_analysis_recalc['배달매출_총액'] # 배달매출은 그대로 사용

df_profit_analysis_recalc['배달_변동비_계산'] = 0
valid_총매출_for_delivery_ratio = df_profit_analysis_recalc['총매출'].replace(0, 1e-9)
배달매출_비중_for_변동비 = (df_profit_analysis_recalc['배달매출_분석용'] / valid_총매출_for_delivery_ratio).fillna(0)
배달매출_비중_for_변동비.replace([float('inf'), -float('inf')], 0, inplace=True)

for item in VARIABLE_COST_ITEMS: # 식자재, 소모품 등
    if item in df_profit_analysis_recalc.columns:
        df_profit_analysis_recalc['배달_변동비_계산'] += df_profit_analysis_recalc[item] * 배달매출_비중_for_변동비

for item in DELIVERY_SPECIFIC_VARIABLE_COST_ITEMS: # 배달비
    if item in df_profit_analysis_recalc.columns:
        df_profit_analysis_recalc['배달_변동비_계산'] += df_profit_analysis_recalc[item]

df_profit_analysis_recalc['배달_고정비_계산'] = 0
for item in FIXED_COST_ITEMS: # 인건비, 광고비, 고정비
    if item in df_profit_analysis_recalc.columns:
        df_profit_analysis_recalc['배달_고정비_계산'] += df_profit_analysis_recalc[item] * 배달매출_비중_for_변동비

df_profit_analysis_recalc['배달순수익'] = df_profit_analysis_recalc['배달매출_분석용'] - df_profit_analysis_recalc['배달_변동비_계산'] - df_profit_analysis_recalc['배달_고정비_계산']
df_profit_analysis_recalc['배달순수익률'] = (df_profit_analysis_recalc['배달순수익'] / df_profit_analysis_recalc['배달매출_분석용'] * 100).fillna(0)
df_profit_analysis_recalc.loc[df_profit_analysis_recalc['배달매출_분석용'] == 0, '배달순수익률'] = 0


# --- 1행 (3개 차트): 총순수익률 추이, 홀순수익률, 배달순수익률 선그래프 ---
col_profit_rate1_1, col_profit_rate1_2, col_profit_rate1_3 = st.columns(3)

with col_profit_rate1_1:
    display_styled_title_box("총 순수익률 추이", background_color="#f5f5f5", font_size="22px", margin_bottom="20px")
    if df_profit_analysis_recalc.empty or df_profit_analysis_recalc['총순수익률'].isnull().all():
        st.warning("선택된 필터 조건에 해당하는 데이터가 없어 '총 순수익률 추이' 차트를 표시할 수 없습니다.")
    else:
        line_total_profit_rate = px.line(
            df_profit_analysis_recalc,
            x='월', y='총순수익률', color='지점명', markers=True,
            # color_discrete_map 사용 대신 직접 트레이스 색상 설정
        )
        # 차트 색상 직접 지정
        unique_branches_line_total = df_profit_analysis_recalc['지점명'].unique()
        color_map_line_total = {b: chart_colors_palette[i % len(chart_colors_palette)] for i, b in enumerate(unique_branches_line_total)}
        line_total_profit_rate.for_each_trace(lambda t: t.update(marker_color=color_map_line_total.get(t.name), line_color=color_map_line_total.get(t.name)))

        line_total_profit_rate.update_traces(hovertemplate="지점: %{fullData.name}<br>월: %{x}<br>총 순수익률: %{y:.2f}%<extra></extra>")
        line_total_profit_rate.update_layout(
            height=550,
            legend=dict(
                title_text='', orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5, font=dict(color='#555555')
            ),
            xaxis=dict(tickfont=dict(color='#555555')),
            yaxis=dict(tickfont=dict(color='#555555'), tickformat=".2f", ticksuffix="%"),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(line_total_profit_rate, use_container_width=True)

with col_profit_rate1_2:
    display_styled_title_box("홀 순수익률 추이", background_color="#f5f5f5", font_size="22px", margin_bottom="20px")
    if df_profit_analysis_recalc.empty or df_profit_analysis_recalc['홀순수익률'].isnull().all():
        st.warning("선택된 필터 조건에 해당하는 데이터가 없어 '홀 순수익률 추이' 차트를 표시할 수 없습니다.")
    else:
        line_hall_profit_rate = px.line(
            df_profit_analysis_recalc,
            x='월', y='홀순수익률', color='지점명', markers=True,
            # color_discrete_map 사용 대신 직접 트레이스 색상 설정
        )
        # 차트 색상 직접 지정 (추가)
        unique_branches_line_hall = df_profit_analysis_recalc['지점명'].unique()
        color_map_line_hall = {b: chart_colors_palette[i % len(chart_colors_palette)] for i, b in enumerate(unique_branches_line_hall)}
        line_hall_profit_rate.for_each_trace(lambda t: t.update(marker_color=color_map_line_hall.get(t.name), line_color=color_map_line_hall.get(t.name)))

        line_hall_profit_rate.update_traces(hovertemplate="지점: %{fullData.name}<br>월: %{x}<br>홀 순수익률: %{y:.2f}%<extra></extra>")
        line_hall_profit_rate.update_layout(
            height=550,
            legend=dict(
                title_text='', orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5, font=dict(color='#555555')
            ),
            xaxis=dict(tickfont=dict(color='#555555')),
            yaxis=dict(tickfont=dict(color='#555555'), tickformat=".2f", ticksuffix="%"),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(line_hall_profit_rate, use_container_width=True)

with col_profit_rate1_3:
    display_styled_title_box("배달 순수익률 추이", background_color="#f5f5f5", font_size="22px", margin_bottom="20px")
    if df_profit_analysis_recalc.empty or df_profit_analysis_recalc['배달순수익률'].isnull().all():
        st.warning("선택된 필터 조건에 해당하는 데이터가 없어 '배달 순수익률 추이' 차트를 표시할 수 없습니다.")
    else:
        line_delivery_profit_rate = px.line(
            df_profit_analysis_recalc,
            x='월', y='배달순수익률', color='지점명', markers=True,
            # color_discrete_map 사용 대신 직접 트레이스 색상 설정
        )
        # 차트 색상 직접 지정 (추가)
        unique_branches_line_delivery = df_profit_analysis_recalc['지점명'].unique()
        color_map_line_delivery = {b: chart_colors_palette[i % len(chart_colors_palette)] for i, b in enumerate(unique_branches_line_delivery)}
        line_delivery_profit_rate.for_each_trace(lambda t: t.update(marker_color=color_map_line_delivery.get(t.name), line_color=color_map_line_delivery.get(t.name)))

        line_delivery_profit_rate.update_traces(hovertemplate="지점: %{fullData.name}<br>월: %{x}<br>배달 순수익률: %{y:.2f}%<extra></extra>")
        line_delivery_profit_rate.update_layout(
            height=550,
            legend=dict(
                title_text='', orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5, font=dict(color='#555555')
            ),
            xaxis=dict(tickfont=dict(color='#555555')),
            yaxis=dict(tickfont=dict(color='#555555'), tickformat=".2f", ticksuffix="%"),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(line_delivery_profit_rate, use_container_width=True)


# --- 2행 (3개 차트): 손익분기점, 식자재 원가율, 인건비 원가율 ---
st.markdown("---") # 순수익 분석 내 구분선
col_profit_cost_1, col_profit_cost_2, col_profit_cost_3 = st.columns(3) # 3개 컬럼으로 변경

with col_profit_cost_1:
    display_styled_title_box("매출 손익분기점 분석", background_color="#f5f5f5", font_size="22px", margin_bottom="20px")
    
    # 총변동비와 총고정비 합계 계산 (df_profit_analysis_recalc 사용)
    df_profit_analysis_recalc['총변동비_계산'] = 0
    for item in VARIABLE_COST_ITEMS + DELIVERY_SPECIFIC_VARIABLE_COST_ITEMS:
        if item in df_profit_analysis_recalc.columns:
            df_profit_analysis_recalc['총변동비_계산'] += df_profit_analysis_recalc[item]
    
    df_profit_analysis_recalc['총고정비_계산'] = 0
    for item in FIXED_COST_ITEMS:
        if item in df_profit_analysis_recalc.columns:
            df_profit_analysis_recalc['총고정비_계산'] += df_profit_analysis_recalc[item]

    if df_profit_analysis_recalc.empty or df_profit_analysis_recalc['총매출'].sum() == 0 or df_profit_analysis_recalc[['총매출', '총변동비_계산', '총고정비_계산']].isnull().all().all():
        st.warning("선택된 필터 조건에 해당하는 매출/지출 데이터가 없어 '매출 손익분기점 분석' 차트를 표시할 수 없습니다.")
    else:
        # 공헌이익률 계산 (매출이 0일 경우 NaN 방지)
        df_profit_analysis_recalc['공헌이익률'] = (1 - (df_profit_analysis_recalc['총변동비_계산'] / df_profit_analysis_recalc['총매출'])).fillna(0)
        df_profit_analysis_recalc.loc[df_profit_analysis_recalc['총매출'] == 0, '공헌이익률'] = 0

        # 손익분기점 매출액 계산
        df_profit_analysis_recalc['손익분기점_매출'] = (df_profit_analysis_recalc['총고정비_계산'] / df_profit_analysis_recalc['공헌이익률']).replace([float('inf'), -float('inf')], 0).fillna(0)

        # 안전여유매출액
        df_profit_analysis_recalc['안전여유매출액'] = df_profit_analysis_recalc['총매출'] - df_profit_analysis_recalc['손익분기점_매출']

        # 모든 지점의 데이터를 합산하여 단일 차트로 구성
        df_bep_total = df_profit_analysis_recalc.groupby('월').agg(
            총매출=('총매출', 'sum'),
            손익분기점_매출=('손익분기점_매출', 'sum'),
            안전여유매출액=('안전여유매출액', 'sum')
        ).reset_index()

        # 복합 차트 생성 (막대: 총매출, 손익분기점_매출 / 선: 안전여유매출액)
        fig_bep = go.Figure()

        # 총매출 막대
        fig_bep.add_trace(go.Bar(
            x=df_bep_total['월'],
            y=df_bep_total['총매출'],
            name='총매출', # 지점명 제거
            marker_color=chart_colors_palette[0], # 총매출 색상
            hovertemplate="월: %{x}<br>총매출: %{y:,.0f}원<extra></extra>"
        ))
        # 손익분기점 매출 막대
        fig_bep.add_trace(go.Bar(
            x=df_bep_total['월'],
            y=df_bep_total['손익분기점_매출'],
            name='손익분기점 매출', # 지점명 제거
            marker_color=chart_colors_palette[1], # 손익분기점 색상
            hovertemplate="월: %{x}<br>손익분기점: %{y:,.0f}원<extra></extra>"
        ))
        
        # 선 그래프 (안전여유매출액)
        fig_bep.add_trace(go.Scatter(
            x=df_bep_total['월'],
            y=df_bep_total['안전여유매출액'],
            mode='lines+markers',
            name='안전여유매출액', # 지점명 제거
            marker_color=chart_colors_palette[2], # 안전여유 색상
            line=dict(width=2),
            hovertemplate="월: %{x}<br>안전여유매출액: %{y:,.0f}원<extra></extra>"
        ))

        fig_bep.update_layout(
            barmode='group', # 막대들을 그룹화
            height=550,
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5, font=dict(color='#555555')
            ),
            xaxis=dict(tickfont=dict(color='#555555')),
            yaxis=dict(tickfont=dict(color='#555555'), tickformat=",.0f", hoverformat=",.0f"),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(fig_bep, use_container_width=True)


with col_profit_cost_2: # 두 번째 컬럼으로 이동
    display_styled_title_box("식자재 원가율 추이", background_color="#f5f5f5", font_size="22px", margin_bottom="20px")
    if df_profit_analysis_recalc.empty or '식자재' not in df_profit_analysis_recalc.columns or df_profit_analysis_recalc['총매출'].sum() == 0:
        st.warning("선택된 필터 조건에 해당하는 식자재 원가율 데이터가 없어 '식자재 원가율 추이' 차트를 표시할 수 없습니다.")
    else:
        df_profit_analysis_recalc['식자재_원가율'] = (df_profit_analysis_recalc.get('식자재', 0) / df_profit_analysis_recalc['총매출'] * 100).fillna(0)
        df_profit_analysis_recalc.loc[df_profit_analysis_recalc['총매출'] == 0, '식자재_원가율'] = 0

        line_food_cost = px.line(
            df_profit_analysis_recalc,
            x='월', y='식자재_원가율', color='지점명', markers=True,
            # color_discrete_map 사용 대신 직접 트레이스 색상 설정
        )
        # 차트 색상 직접 지정 (추가)
        unique_branches_line_food = df_profit_analysis_recalc['지점명'].unique()
        color_map_line_food = {b: chart_colors_palette[i % len(chart_colors_palette)] for i, b in enumerate(unique_branches_line_food)}
        line_food_cost.for_each_trace(lambda t: t.update(marker_color=color_map_line_food.get(t.name), line_color=color_map_line_food.get(t.name)))


        line_food_cost.update_traces(hovertemplate="지점: %{fullData.name}<br>월: %{x}<br>식자재 원가율: %{y:.2f}%<extra></extra>")
        line_food_cost.update_layout(
            height=550,
            legend=dict(title_text='', orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5, font=dict(color='#555555')),
            xaxis=dict(tickfont=dict(color='#555555')),
            yaxis=dict(tickfont=dict(color='#555555'), tickformat=".2f", ticksuffix="%"),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(line_food_cost, use_container_width=True)

with col_profit_cost_3: # 세 번째 컬럼으로 이동
    display_styled_title_box("인건비 원가율 추이", background_color="#f5f5f5", font_size="22px", margin_bottom="20px")
    if df_profit_analysis_recalc.empty or '인건비' not in df_profit_analysis_recalc.columns or df_profit_analysis_recalc['총매출'].sum() == 0:
        st.warning("선택된 필터 조건에 해당하는 인건비 원가율 데이터가 없어 '인건비 원가율 추이' 차트를 표시할 수 없습니다.")
    else:
        df_profit_analysis_recalc['인건비_원가율'] = (df_profit_analysis_recalc.get('인건비', 0) / df_profit_analysis_recalc['총매출'] * 100).fillna(0)
        df_profit_analysis_recalc.loc[df_profit_analysis_recalc['총매출'] == 0, '인건비_원가율'] = 0

        line_labor_cost = px.line(
            df_profit_analysis_recalc,
            x='월', y='인건비_원가율', color='지점명', markers=True,
            # color_discrete_map 사용 대신 직접 트레이스 색상 설정
        )
        # 차트 색상 직접 지정 (추가)
        unique_branches_line_labor = df_profit_analysis_recalc['지점명'].unique()
        color_map_line_labor = {b: chart_colors_palette[i % len(chart_colors_palette)] for i, b in enumerate(unique_branches_line_labor)}
        line_labor_cost.for_each_trace(lambda t: t.update(marker_color=color_map_line_labor.get(t.name), line_color=color_map_line_labor.get(t.name)))

        line_labor_cost.update_traces(hovertemplate="지점: %{fullData.name}<br>월: %{x}<br>인건비 원가율: %{y:.2f}%<extra></extra>")
        line_labor_cost.update_layout(
            height=550,
            legend=dict(title_text='', orientation="h", yanchor="bottom", y=1.15, xanchor="center", x=0.5, font=dict(color='#555555')),
            xaxis=dict(tickfont=dict(color='#555555')),
            yaxis=dict(tickfont=dict(color='#555555'), tickformat=".2f", ticksuffix="%"),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(line_labor_cost, use_container_width=True)

####################################################################################################
# 🥒 식자재 분석 섹션
####################################################################################################
st.markdown("---")
st.markdown("<br>", unsafe_allow_html=True)
display_styled_title_box(
    "🥒 식자재 분석 🥒", # 새로운 제목
    background_color="#f5f5f5", font_size="32px", margin_bottom="20px", padding_y="15px"
)

st.subheader("상위 20개 식자재 품목 총액") # 상위 10개 -> 20개로 변경 및 '품목' 추가
# 식자재 지출 필터링: **분류가 '식자재'인 경우만 사용 (요청에 따라 고정)**
식자재_분석용_df = df_filtered[df_filtered['분류'] == '식자재'].copy() # 분류가 '식자재'인 경우만 필터링

if 식자재_분석용_df.empty:
    st.warning("선택된 필터 조건에 해당하는 식자재 지출 데이터가 없어 상위 20개 리스트를 표시할 수 없습니다. (현재 필터: 분류 == '식자재')")
else:
    # 항목2(세부 식자재명)별 금액 합산 및 상위 20개 추출 (항목1은 납품처이므로 항목2를 사용)
    top_20_식자재 = 식자재_분석용_df.groupby('항목2')['금액'].sum().nlargest(20).reset_index() # 상위 10개 -> 20개로 변경
    top_20_식자재.columns = ['식자재 품목 (세부)', '총 금액'] # 컬럼명 변경

    if not top_20_식자재.empty:
        top_20_식자재['순위'] = range(1, len(top_20_식자재) + 1) # 1부터 시작하는 순위 컬럼 추가
        total_식자재_금액 = top_20_식자재['총 금액'].sum()
        top_20_식자재['비중 (%)'] = (top_20_식자재['총 금액'] / total_식자재_금액 * 100).fillna(0) if total_식자재_금액 > 0 else 0

    st.dataframe(
        top_20_식자재[['순위', '식자재 품목 (세부)', '총 금액', '비중 (%)']].style.format({
            "총 금액": "{:,.0f}원",
            "비중 (%)": "{:.2f}%"
        }).set_properties(**{'text-align': 'center'}), # 모든 컬럼을 가운데 정렬로 변경
        use_container_width=True,
        hide_index=True
    )

####################################################################################################
# 📊 시뮬레이션 분석 섹션
####################################################################################################
st.markdown("---")
st.markdown("<br>", unsafe_allow_html=True)
display_styled_title_box(
    "📊 시뮬레이션 분석 📊",
    background_color="#f5f5f5", font_size="32px", margin_bottom="20px", padding_y="15px"
)

# --- 0. 시뮬레이션 기반 데이터 준비 ---
if not df_expense_analysis.empty and '총매출' in df_expense_analysis.columns and df_expense_analysis['총매출'].sum() > 0:
    num_months = len(선택_월)
    num_stores = df_expense_analysis['지점명'].nunique()
    
    divisor_months = num_months if num_months > 0 else 1
    divisor_stores = num_stores if num_stores > 0 else 1

    base_total_revenue = df_expense_analysis['총매출'].sum() / divisor_months / divisor_stores
    base_costs = {item: df_expense_analysis[item].sum() / divisor_months / divisor_stores for item in all_possible_expense_categories_for_analysis if item in df_expense_analysis.columns}
    base_total_cost = sum(base_costs.values())
    base_profit = base_total_revenue - base_total_cost
    base_profit_margin = (base_profit / base_total_revenue * 100) if base_total_revenue > 0 else 0
    
    # ✅ 수정: 홀매출 비율 계산 기준을 '홀매출_총액'으로 변경
    if '홀매출_총액' in df_expense_analysis.columns and base_total_revenue > 0:
        base_hall_ratio = ( (df_expense_analysis['홀매출_총액'].sum() / divisor_months / divisor_stores) / base_total_revenue * 100)
    else:
        base_hall_ratio = 0.0
else:
    st.warning("시뮬레이션을 위해 사이드바에서 1개 이상의 '월'과 '지점'을 선택하고, 충분한 매출 데이터가 로드되었는지 확인해주세요.")
    st.stop()

# --- 1. 현재 상태 요약 ---
st.subheader("📋 현재 상태 요약 (지점당 월평균)")
summary_cols = st.columns(4)
summary_cols[0].metric("평균 총매출", f"{base_total_revenue:,.0f} 원")
summary_cols[1].metric("평균 총비용", f"{base_total_cost:,.0f} 원")
summary_cols[2].metric("평균 순수익", f"{base_profit:,.0f} 원")
summary_cols[3].metric("평균 순수익률", f"{base_profit_margin:.1f}%")
st.markdown("---")

# --- 2. 시뮬레이션 조건 설정 UI ---
st.subheader("⚙️ 시뮬레이션 조건 설정")

col1, col2 = st.columns(2)
with col1:
    sim_revenue = st.number_input(
        "예상 월평균 매출 (원)",
        min_value=0.0,
        value=base_total_revenue,
        step=100000.0,
        format="%.0f",
        help=f"현재 지점당 월평균 매출: {base_total_revenue:,.0f} 원"
    )

with col2:
    sim_hall_ratio_pct = st.slider(
        "예상 홀매출 비율 (%)",
        min_value=0.0,
        max_value=100.0,
        value=base_hall_ratio,
        step=0.1,
        format="%.1f",
        help=f"현재 홀매출 비율: {base_hall_ratio:.1f}%"
    )

sim_delivery_ratio_pct = 100.0 - sim_hall_ratio_pct

info_col1, info_col2 = st.columns(2)
with info_col1:
    st.markdown(f"<div class='info-box'>홀매출 비율: {sim_hall_ratio_pct:.1f}%</div>", unsafe_allow_html=True)
with info_col2:
    st.markdown(f"<div class='info-box'>배달+포장 비율: {sim_delivery_ratio_pct:.1f}%</div>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# 시뮬레이션 매출액 및 성장률 계산
base_hall_revenue = (df_expense_analysis['홀매출_총액'].sum() / divisor_months / divisor_stores) if '홀매출_총액' in df_expense_analysis else 0
base_delivery_takeout_revenue = (df_expense_analysis['배달매출_총액'].sum() / divisor_months / divisor_stores) if '배달매출_총액' in df_expense_analysis else 0

sim_hall_revenue = sim_revenue * (sim_hall_ratio_pct / 100)
sim_delivery_takeout_revenue = sim_revenue * (sim_delivery_ratio_pct / 100)

live_hall_revenue_growth = sim_hall_revenue / base_hall_revenue if base_hall_revenue > 0 else 0
live_delivery_takeout_revenue_growth = sim_delivery_takeout_revenue / base_delivery_takeout_revenue if base_delivery_takeout_revenue > 0 else 0

with st.expander("항목별 비용 상세 조정 (선택)"):
    cost_adjustments = {}
    cost_cols = st.columns(3)
    ordered_cost_items = ['식자재', '소모품', '배달비', '인건비', '광고비', '고정비']
    col_idx = 0
    for item in ordered_cost_items:
        if item in base_costs:
            with cost_cols[col_idx % 3]:
                slider_value = st.slider(f"{item} 조정률 (%)", -50.0, 50.0, 0.0, 0.1, "%.1f", help=f"현재 월평균 {item} 비용: {base_costs.get(item, 0):,.0f} 원", key=f"slider_{item}")
                cost_adjustments[item] = slider_value

st.markdown("---")
royalty_rate = st.slider("👑 로열티 설정 (매출 대비 %)", 0.0, 10.0, 0.0, 0.1, "%.1f%%")
st.success(f"예상 로열티 금액 (월): **{sim_revenue * (royalty_rate / 100):,.0f} 원**")
st.markdown("<br>", unsafe_allow_html=True)

st.markdown("""<style>div[data-testid="stButton"] > button { height: 60px; padding: 10px 24px; font-size: 24px; font-weight: bold; }</style>""", unsafe_allow_html=True)

if st.button("🚀 시뮬레이션 실행", use_container_width=True):
    sim_costs = {}
    cost_adjustment_defaults = locals().get('cost_adjustments', {})
    for item in VARIABLE_COST_ITEMS:
        if item in base_costs: sim_costs[item] = base_costs[item] * live_total_revenue_growth * (1 + cost_adjustment_defaults.get(item, 0) / 100)
    for item in DELIVERY_SPECIFIC_VARIABLE_COST_ITEMS:
        if item in base_costs: sim_costs[item] = base_costs[item] * live_delivery_revenue_growth * (1 + cost_adjustment_defaults.get(item, 0) / 100)
    for item in FIXED_COST_ITEMS:
        if item in base_costs: sim_costs[item] = base_costs[item] * (1 + cost_adjustment_defaults.get(item, 0) / 100)
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
            st.plotly_chart(fig_revenue, use_container_width=True)
        with r1_sub_col2:
            df_cost = pd.DataFrame({'구분': ['현재', '시뮬레이션'], '금액': [base_total_cost, sim_total_cost]})
            fig_cost = px.bar(df_cost, x='구분', y='금액', color='구분', text_auto=True, title="총비용 비교", color_discrete_map=theme_color_map)
            fig_cost.update_traces(texttemplate='%{y:,.0f}', hovertemplate="<b>%{x}</b><br>금액: %{y:,.0f}원<extra></extra>")
            fig_cost.update_layout(height=550, showlegend=False, yaxis_title="금액(원)", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig_cost, use_container_width=True)
            
    with row1_col2:
        display_styled_title_box("순수익률 비교", font_size="22px", margin_bottom="20px")
        df_profit_rate = pd.DataFrame({'구분': ['현재', '시뮬레이션'],'수익률': [base_profit_margin, sim_profit_margin], '수익금액': [base_profit, sim_profit]})
        fig_profit_rate = px.line(df_profit_rate, x='구분', y='수익률', markers=True, text='수익률', custom_data=['수익금액'])
        fig_profit_rate.update_traces(line=dict(color='#687E8E', width=3), marker=dict(size=10, color='#687E8E'), texttemplate='%{text:.1f}%', textposition='top center', hovertemplate="<b>%{x}</b><br>수익률: %{y:.1f}%<br>수익금액: %{customdata[0]:,.0f}원<extra></extra>")
        fig_profit_rate.update_layout(height=550, yaxis_title="순수익률 (%)", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis=dict(range=[-0.5, 1.5]))
        st.plotly_chart(fig_profit_rate, use_container_width=True)

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
                st.plotly_chart(fig_bar_base, use_container_width=True, key="base_cost_bar")
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
                st.plotly_chart(fig_bar_sim, use_container_width=True, key="sim_cost_bar")
