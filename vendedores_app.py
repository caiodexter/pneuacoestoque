
import os
import base64
from datetime import datetime
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from streamlit_autorefresh import st_autorefresh
from pathlib import Path

def img_b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


st.set_page_config(page_title="Consulta de Estoque - Vendedores", page_icon="🛞", layout="wide", initial_sidebar_state="expanded")
st_autorefresh(interval=60000, key="seller_refresh")

def get_database_url():
    try:
        if "DATABASE_URL" in st.secrets:
            return st.secrets["DATABASE_URL"]
    except Exception:
        pass
    return os.getenv("DATABASE_URL", "")

@st.cache_resource
def get_engine():
    url = get_database_url().strip()
    if not url:
        st.error("Banco online não configurado.")
        st.stop()
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return create_engine(url, pool_pre_ping=True, future=True)

engine = get_engine()

def load_stock():
    return pd.read_sql_query(text("""
        SELECT origem, descricao, marca, preco_unitario, quantidade
        FROM produtos
        WHERE ativo IS TRUE
        ORDER BY marca, descricao
    """), engine)

def brl(v):
    s = f"{float(v or 0):,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")

st.markdown("""
<style>
[data-testid="stAppViewContainer"]{background:#f5f8fc}
.block-container{padding-top:1.0rem;max-width:1500px}
[data-testid="stSidebar"]{background:linear-gradient(180deg,#03172f,#06264d)}
[data-testid="stSidebar"] *{color:white}
.hero{background:white;border-bottom:1px solid #dfe7f1;padding:10px 12px 16px;margin:-10px 0 22px}
.hero-row{display:flex;align-items:center;justify-content:space-between;gap:20px}
.hero h1{margin:0;color:#082b59;font-size:29px;font-weight:800}
.hero p{margin:5px 0 0;color:#334155}
.logo{max-width:310px;max-height:78px;object-fit:contain}
.update{display:inline-block;background:#e8f8ed;color:#16833a;padding:11px 15px;border-radius:8px;font-size:14px;white-space:nowrap}
.card{border:1px solid #dfe6ef;border-radius:10px;padding:18px 20px;min-height:112px;background:white;box-shadow:0 2px 8px rgba(0,0,0,.04)}
.card .label{font-size:14px;font-weight:800}.card .value{font-size:30px;font-weight:800;color:#0a2447;margin-top:10px}
.blue{color:#075bd8}.green{color:#0b8d2d}.orange{color:#f05b08}.purple{color:#7132b9}
.origin-note{background:#e9f9ee;color:#128132;padding:5px 9px;border-radius:6px;font-weight:700}
.origin-diesel{background:#fff1e5;color:#f05b08;padding:5px 9px;border-radius:6px;font-weight:700}
[data-testid="stDataFrame"]{background:white;border:1px solid #dfe6ef;border-radius:10px;padding:5px}
div[data-testid="stTextInput"] input, div[data-testid="stSelectbox"]>div>div{background:white}
.small-note{background:#eef6ff;border-radius:8px;padding:12px;color:#173b67;margin-top:10px}

.public-badge{display:inline-block;background:#e8f8ed;color:#16833a;border:1px solid #bde7ca;
padding:7px 11px;border-radius:8px;font-weight:700;margin-bottom:10px}
[data-testid="stSidebar"]{display:none}
</style>
""", unsafe_allow_html=True)

df = load_stock()

st.markdown('<div class="public-badge">🌐 ACESSO PÚBLICO — NÃO É NECESSÁRIO LOGIN</div>', unsafe_allow_html=True)

logo64 = img_b64(Path(__file__).resolve().parent / "assets" / "logo_pneuaco.png")
agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
st.markdown(f"""
<div class="hero">
 <div class="hero-row">
   <div>
     <h1>CONSULTA DE ESTOQUE - VENDEDORES</h1>
     <p>Consulte disponibilidade, valores e origem dos pneus em estoque</p>
   </div>
   <div class="update">↻ Última atualização: {agora}</div>
   <img class="logo" src="data:image/png;base64,{logo64}">
 </div>
</div>
""", unsafe_allow_html=True)

total = int(df["quantidade"].sum()) if not df.empty else 0
nota = int(df.loc[df["origem"]=="PNEUS COM NOTA","quantidade"].sum()) if not df.empty else 0
diesel = int(df.loc[df["origem"]=="DIESEL PNEUS","quantidade"].sum()) if not df.empty else 0

c1,c2,c3,c4 = st.columns(4)
for col,label,value,suf,klass,icon in [
    (c1,"TOTAL DE PNEUS",f"{total:,}".replace(",","."),"unidades","blue","🛞"),
    (c2,"PNEUS COM NOTA",f"{nota:,}".replace(",","."),"unidades","green","📄"),
    (c3,"DIESEL PNEUS",f"{diesel:,}".replace(",","."),"unidades","orange","🛞"),
    (c4,"TOTAL DE MODELOS",str(len(df)),"modelos","purple","🏷️"),
]:
    with col:
        st.markdown(f'<div class="card"><div class="label {klass}">{label}</div><div style="display:flex;justify-content:space-between;align-items:center"><div><div class="value">{value}</div><div>{suf}</div></div><div style="font-size:42px">{icon}</div></div></div>', unsafe_allow_html=True)

st.markdown("### 🔎 PESQUISAR")
a,b,c = st.columns([1,1,2])
with a:
    origem = st.selectbox("Origem", ["TODAS","PNEUS COM NOTA","DIESEL PNEUS"])
base = df if origem=="TODAS" else df[df["origem"]==origem]
with b:
    marca = st.selectbox("Marca", ["TODAS"] + sorted(base["marca"].dropna().unique().tolist()))
with c:
    busca = st.text_input("Pesquisar por medida, modelo ou descrição", placeholder="Ex.: 600/65R28, PIRELLI, TM95...")

f = base.copy()
if marca != "TODAS":
    f = f[f["marca"]==marca]
if busca.strip():
    t = busca.strip()
    f = f[f["descricao"].str.contains(t, case=False, na=False) | f["marca"].str.contains(t, case=False, na=False)]

mostrar_zero = st.checkbox("Mostrar itens sem estoque", value=False)
if not mostrar_zero:
    f = f[f["quantidade"] > 0]

show = f[["origem","marca","descricao","quantidade","preco_unitario"]].copy()
show.columns = ["ORIGEM","MARCA","MODELO / DESCRIÇÃO","QUANTIDADE","VALOR UNITÁRIO"]
show["VALOR UNITÁRIO"] = show["VALOR UNITÁRIO"].map(brl)
st.dataframe(show, hide_index=True, use_container_width=True, height=620)
st.markdown(f'<div class="small-note">ⓘ {len(show)} modelos encontrados. Os estoques são atualizados automaticamente conforme movimentações no sistema. Atualização automática: 60 segundos.</div>', unsafe_allow_html=True)
