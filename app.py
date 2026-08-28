
from pathlib import Path
import io
import os
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

BASE_DIR = Path(__file__).resolve().parent
LOCAL_DB = BASE_DIR / "estoque.db"

st.set_page_config(
    page_title="Estoque de Pneus Online",
    page_icon="🛞",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
:root{
  --navy:#0b2344;
  --blue:#2563eb;
  --line:#e2e8f0;
  --muted:#64748b;
  --bg:#f7f9fc;
}
.stApp {background:var(--bg);}
.block-container{
  max-width:1480px;
  padding-top:1.15rem;
  padding-bottom:2rem;
  padding-left:1.5rem;
  padding-right:1.5rem;
}

/* Sidebar mais próximo do layout aprovado */
section[data-testid="stSidebar"]{
  background:#ffffff;
  border-right:1px solid #e5e7eb;
}
section[data-testid="stSidebar"] > div{
  padding-top:1rem;
}
section[data-testid="stSidebar"] h1{
  color:#111827;
  font-size:25px !important;
  font-weight:900;
}
section[data-testid="stSidebar"] [role="radiogroup"] label{
  border-radius:9px;
  padding:7px 9px;
  margin:2px 0;
}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked){
  background:#0b2d58;
  color:#ffffff;
}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p{
  color:#ffffff !important;
}
section[data-testid="stSidebar"] button{
  border-radius:9px;
}

/* Componentes antigos preservados para outras páginas */
.hero{
  background:linear-gradient(100deg,#031f45,#073a77);
  color:white;padding:24px 28px;border-radius:14px;margin-bottom:16px;
}
.hero h1{margin:0;font-size:34px;}
.hero p{margin:7px 0 0;opacity:.9;font-size:15px;}
.kpi{
  border:1px solid #d7e0ec;border-radius:14px;padding:18px 20px;
  background:white;min-height:120px;
}
.kpi .lbl{font-weight:700;font-size:13px;color:#111827;}
.kpi .val{font-weight:800;font-size:26px;color:#061f43;margin-top:10px;}
.section-title{
  background:linear-gradient(100deg,#062b59,#073a77);
  color:white;padding:10px 14px;border-radius:10px 10px 0 0;
  font-weight:800;margin-top:8px;
}
.okbox{
  background:#edf8f1;border:1px solid #b7e0c4;padding:12px 14px;
  border-radius:10px;color:#155d2f;margin-bottom:12px;
}
.warnbox{
  background:#fff7e6;border:1px solid #f2d59b;padding:12px 14px;
  border-radius:10px;color:#7a5200;margin-bottom:12px;
}
</style>
""", unsafe_allow_html=True)

def get_database_url():
    # Priority: Streamlit secrets, then environment variable.
    try:
        if "DATABASE_URL" in st.secrets:
            return st.secrets["DATABASE_URL"]
    except Exception:
        pass
    return os.getenv("DATABASE_URL", "")

@st.cache_resource
def get_engine() -> Engine:
    url = get_database_url().strip()
    if url:
        # Supabase and some providers still hand out postgres:// URLs.
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return create_engine(
            url,
            pool_pre_ping=True,
            future=True,
            pool_size=2,
            max_overflow=0,
            pool_recycle=300,
            pool_timeout=30,
            pool_use_lifo=True,
        )
    return create_engine(f"sqlite:///{LOCAL_DB}", future=True)

engine = get_engine()

def is_online_db():
    return str(engine.url).startswith("postgresql")

def ativo_sql():
    # PostgreSQL uses BOOLEAN; SQLite uses 0/1 integers.
    return "ativo IS TRUE" if engine.dialect.name == "postgresql" else "ativo=1"

def init_db():
    dialect = engine.dialect.name

    if dialect == "postgresql":
        # O banco online já foi criado por migrar_para_postgres.py.
        # No Streamlit Cloud apenas validamos a existência das tabelas.
        with engine.connect() as conn:
            for tabela in ("produtos", "movimentacoes", "usuarios"):
                existe = conn.execute(
                    text("""
                        SELECT EXISTS (
                            SELECT 1
                            FROM information_schema.tables
                            WHERE table_schema='public' AND table_name=:tabela
                        )
                    """),
                    {"tabela": tabela},
                ).scalar_one()
                if not existe:
                    raise RuntimeError(
                        f"Tabela '{tabela}' não encontrada no Supabase. "
                        "Execute migrar_para_postgres.py antes de publicar."
                    )

        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS auditoria (
                    id BIGSERIAL PRIMARY KEY,
                    data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    usuario TEXT NOT NULL, tipo TEXT NOT NULL, produto_id INTEGER,
                    descricao TEXT, origem TEXT, valor_anterior DOUBLE PRECISION,
                    valor_novo DOUBLE PRECISION, quantidade_anterior INTEGER,
                    quantidade_movimentada INTEGER, quantidade_nova INTEGER,
                    nf TEXT, destino TEXT, motivo TEXT, observacao TEXT
                )
            """))

            conn.execute(text("""
                ALTER TABLE produtos
                ADD COLUMN IF NOT EXISTS estoque_minimo INTEGER DEFAULT 2
            """))
        return

    # Modo local SQLite.
    with engine.begin() as conn:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origem TEXT NOT NULL DEFAULT 'PNEUS COM NOTA',
            descricao TEXT NOT NULL,
            marca TEXT NOT NULL,
            preco_unitario NUMERIC NOT NULL DEFAULT 0,
            quantidade INTEGER NOT NULL DEFAULT 0,
            ativo INTEGER DEFAULT 1,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS movimentacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            usuario TEXT,
            nf TEXT,
            fornecedor_destino TEXT,
            observacao TEXT,
            estoque_anterior INTEGER,
            estoque_atual INTEGER,
            data_movimento TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT UNIQUE NOT NULL,
            senha TEXT NOT NULL,
            ativo INTEGER DEFAULT 1
        )
        """))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS auditoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_hora TEXT DEFAULT CURRENT_TIMESTAMP,
            usuario TEXT NOT NULL, tipo TEXT NOT NULL, produto_id INTEGER,
            descricao TEXT, origem TEXT, valor_anterior REAL, valor_novo REAL,
            quantidade_anterior INTEGER, quantidade_movimentada INTEGER,
            quantidade_nova INTEGER, nf TEXT, destino TEXT, motivo TEXT, observacao TEXT
        )
        """))

        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(movimentacoes)")).fetchall()}
        extras = {
            "usuario": "TEXT",
            "nf": "TEXT",
            "fornecedor_destino": "TEXT",
            "estoque_anterior": "INTEGER",
            "estoque_atual": "INTEGER",
        }
        for col, tipo in extras.items():
            if col not in cols:
                conn.execute(text(f"ALTER TABLE movimentacoes ADD COLUMN {col} {tipo}"))

        count = conn.execute(text("SELECT COUNT(*) FROM usuarios")).scalar_one()
        if count == 0:
            conn.execute(text("INSERT INTO usuarios(nome,senha,ativo) VALUES ('admin','admin123',1)"))

    with engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(produtos)")).fetchall()
        nomes = {str(c[1]) for c in cols}
        if "estoque_minimo" not in nomes:
            conn.execute(text("ALTER TABLE produtos ADD COLUMN estoque_minimo INTEGER DEFAULT 2"))


init_db()

def seed_operational_users():
    usuarios_padrao = [
        ("gabriel", "0767"),
        ("lucas", "1303"),
        ("eduardo", "chefe"),
    ]
    with engine.begin() as conn:
        for nome, senha in usuarios_padrao:
            existe = conn.execute(
                text("SELECT COUNT(*) FROM usuarios WHERE nome=:nome"),
                {"nome": nome},
            ).scalar_one()
            if existe == 0:
                conn.execute(
                    text("INSERT INTO usuarios(nome,senha,ativo) VALUES (:nome,:senha,:ativo)"),
                    {"nome": nome, "senha": senha, "ativo": True if engine.dialect.name=="postgresql" else 1},
                )

seed_operational_users()

def registrar_auditoria(tipo, produto_id=None, descricao=None, origem=None,
                        valor_anterior=None, valor_novo=None, quantidade_anterior=None,
                        quantidade_movimentada=None, quantidade_nova=None, nf=None,
                        destino=None, motivo=None, observacao=None):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO auditoria (usuario,tipo,produto_id,descricao,origem,
                valor_anterior,valor_novo,quantidade_anterior,quantidade_movimentada,
                quantidade_nova,nf,destino,motivo,observacao)
            VALUES (:u,:t,:pid,:d,:o,:va,:vn,:qa,:qm,:qn,:nf,:dest,:mot,:obs)
        """), {
            "u": st.session_state.get("user","sistema"), "t": tipo, "pid": produto_id,
            "d": descricao, "o": origem, "va": valor_anterior, "vn": valor_novo,
            "qa": quantidade_anterior, "qm": quantidade_movimentada, "qn": quantidade_nova,
            "nf": nf, "dest": destino, "mot": motivo, "obs": observacao
        })

def load_products(active_only=True):
    q = """
        SELECT id, origem, descricao, marca, preco_unitario, quantidade,
               preco_unitario * quantidade AS valor_estoque, ativo, COALESCE(estoque_minimo,2) AS estoque_minimo
        FROM produtos
    """
    if active_only:
        q += f" WHERE {ativo_sql()}"
    q += " ORDER BY descricao"
    return pd.read_sql_query(text(q), engine)

def brl(v):
    s = f"{float(v or 0):,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")

def detect_brand(desc):
    u = str(desc).upper()
    if "MICHELLIN" in u or "MICHELIN" in u:
        return "MICHELIN"
    if "MAXAN" in u or "MAXAM" in u or " MXA " in f" {u} ":
        return "MAXAM"
    if " CEAT " in f" {u} " or " CEA " in f" {u} ":
        return "CEAT"

    brands = [
        "POWER ROAD","ROADGUIDER","FORERRUNER","FORERUNNER","PNEUAÇO","ATLAS",
        "TRELLEBORG","GRIPMASTER","FIRESTONE","WESTLAKE","SPEEDMAX","ALLIANCE",
        "MICHELIN","PIRELLI","ADVANCE","ASCENSO","DURABLE","GOODYEAR","VIKRANT",
        "MAGGION","ARMOUR","APOLLO","CULTORE","KLEBER","MAXAM","OTRMAX","PETLAS",
        "PRIMEX","TITAN","ANTEO","GALAXY","BKT","CEAT","MITAS","MRL","OZKA","SPM","ELITE"
    ]
    for b in sorted(brands, key=len, reverse=True):
        if b in u:
            return b
    return "OUTRA/NAO IDENTIFICADA"

def login():
    if st.session_state.get("auth"):
        return True
    st.title("🔐 Acesso ao Estoque")
    st.caption("Usuário inicial: admin | Senha inicial: admin123")
    user = st.text_input("Usuário")
    pwd = st.text_input("Senha", type="password")
    if st.button("Entrar", type="primary"):
        with engine.begin() as conn:
            row = conn.execute(
                text(f"SELECT nome, COALESCE(perfil,'ADMINISTRADOR') AS perfil FROM usuarios WHERE nome=:u AND senha=:p AND {ativo_sql()}"),
                {"u":user, "p":pwd}
            ).fetchone()
        if row:
            st.session_state["auth"] = True
            st.session_state["user"] = row[0]
            st.session_state["perfil"] = row[1]
            st.rerun()
        else:
            st.error("Usuário ou senha inválidos.")
    return False

def dashboard():
    st.markdown("""
    <style>
      .dash-topline{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;margin-bottom:8px}
      .dash-title{font-size:31px;font-weight:900;color:#15233b;line-height:1.05}
      .dash-sub{color:#64748b;font-size:14px;margin-top:7px}
      .dash-user{font-size:14px;font-weight:700;color:#334155;background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:10px 14px;white-space:nowrap}
      .metric-card{background:#fff;border:1px solid #e1e7ef;border-radius:15px;min-height:165px;padding:18px 12px;text-align:center;box-shadow:0 4px 12px rgba(15,23,42,.06)}
      .metric-title{font-size:13px;font-weight:800;color:#475569;min-height:34px}
      .metric-icon{font-size:34px;margin:5px 0}
      .metric-value{font-size:27px;font-weight:900;color:#13213b;line-height:1.1;white-space:nowrap}
      .metric-foot{font-size:12px;color:#64748b;margin-top:8px}
      .panel{background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:19px;box-shadow:0 4px 13px rgba(15,23,42,.045);margin-top:15px}
      .panel-title{font-size:20px;font-weight:900;color:#17233a;margin-bottom:2px}
      .panel-sub{font-size:13px;color:#64748b;margin-bottom:12px}
      .alert-red{background:#fff1f2;border:1px solid #fda4af;border-radius:12px;padding:17px;color:#991b1b;font-weight:800}
      .alert-yellow{background:#fffbeb;border:1px solid #f6c453;border-radius:12px;padding:17px;color:#92400e;font-weight:800}
      div[data-testid="stButton"] button{border-radius:10px;min-height:39px;font-weight:700}
      .footer-box{background:#11243f;color:#fff;padding:18px 24px;margin-top:22px;display:flex;justify-content:space-between;font-size:13px}
    </style>
    """, unsafe_allow_html=True)

    agora = datetime.now()
    usuario = st.session_state.get("user","Administrador")
    st.markdown(f"""
      <div class="dash-topline">
        <div><div class="dash-title">Painel Gerencial</div>
        <div class="dash-sub">Visão geral do estoque por origem, marca e modelo</div></div>
        <div class="dash-user">📅 {agora.strftime("%d/%m/%Y - %H:%M")} &nbsp;&nbsp; 👤 {usuario}</div>
      </div>
    """, unsafe_allow_html=True)

    df = load_products()
    if df.empty:
        st.warning("Nenhum produto encontrado no estoque.")
        return

    df = df.copy()
    df["quantidade"] = pd.to_numeric(df["quantidade"], errors="coerce").fillna(0)
    df["valor_estoque"] = pd.to_numeric(df["valor_estoque"], errors="coerce").fillna(0)
    df["preco_unitario"] = pd.to_numeric(df["preco_unitario"], errors="coerce").fillna(0)

    origens = ["PNEUS COM NOTA","PNEUS SEM NOTA","DIESEL PNEUS"]
    def valor_origem(nome):
        return float(df.loc[df["origem"]==nome,"valor_estoque"].sum())
    def qtd_origem(nome):
        return int(df.loc[df["origem"]==nome,"quantidade"].sum())
    def modelos_origem(nome):
        return int((df["origem"]==nome).sum())

    valor_total = float(df["valor_estoque"].sum())
    qtd_total = int(df["quantidade"].sum())
    zerados = df[df["quantidade"] <= 0].copy()
    df["estoque_minimo"] = pd.to_numeric(df["estoque_minimo"], errors="coerce").fillna(2)
    baixos = df[(df["quantidade"] > 0) & (df["quantidade"] <= df["estoque_minimo"])].copy()

    # Valores por origem
    c1,c2,c3,c4 = st.columns(4, gap="medium")
    cards = [
        (c1,"Valor total do estoque","💰",brl(valor_total),f"{qtd_total} unidades"),
        (c2,"Pneus com nota","🧾",brl(valor_origem("PNEUS COM NOTA")),f'{qtd_origem("PNEUS COM NOTA")} unidades'),
        (c3,"Pneus sem nota","📦",brl(valor_origem("PNEUS SEM NOTA")),f'{qtd_origem("PNEUS SEM NOTA")} unidades'),
        (c4,"Diesel Pneus","🚚",brl(valor_origem("DIESEL PNEUS")),f'{qtd_origem("DIESEL PNEUS")} unidades'),
    ]
    for col,tit,ico,val,foot in cards:
        with col:
            st.markdown(f"""<div class="metric-card"><div class="metric-title">{tit}</div>
            <div class="metric-icon">{ico}</div><div class="metric-value">{val}</div>
            <div class="metric-foot">{foot}</div></div>""", unsafe_allow_html=True)

    # Modelos / origem
    st.markdown('<div class="panel"><div class="panel-title">📦 Modelos / origem do estoque</div>'
                '<div class="panel-sub">Quantidade de modelos e unidades disponíveis em cada origem</div>',
                unsafe_allow_html=True)
    o1,o2,o3,o4 = st.columns(4)
    o1.metric("Todos", f"{len(df)} modelos", f"{qtd_total} unidades")
    o2.metric("Pneus com nota", f'{modelos_origem("PNEUS COM NOTA")} modelos', f'{qtd_origem("PNEUS COM NOTA")} unidades')
    o3.metric("Pneus sem nota", f'{modelos_origem("PNEUS SEM NOTA")} modelos', f'{qtd_origem("PNEUS SEM NOTA")} unidades')
    o4.metric("Diesel Pneus", f'{modelos_origem("DIESEL PNEUS")} modelos', f'{qtd_origem("DIESEL PNEUS")} unidades')
    st.markdown("</div>", unsafe_allow_html=True)

    # Filtro interativo por origem/modelo
    st.markdown('<div class="panel"><div class="panel-title">🔎 Consultar pneus por origem</div>'
                '<div class="panel-sub">Selecione uma origem e filtre marca/modelo para ver exatamente o estoque disponível</div>',
                unsafe_allow_html=True)

    f1,f2 = st.columns([1,1.3])
    with f1:
        origem_sel = st.selectbox("Origem", ["TODAS"] + origens, key="dash_origem_filtro")
    base = df if origem_sel=="TODAS" else df[df["origem"]==origem_sel]
    with f2:
        marcas = sorted(base["marca"].dropna().astype(str).unique())
        marca_sel = st.multiselect("Marca", marcas, key="dash_marca_filtro")

    filtrado = base if not marca_sel else base[base["marca"].astype(str).isin(marca_sel)]
    busca = st.text_input("Pesquisar modelo / medida", placeholder="Ex.: 295/80R22.5, Pirelli, FR88...", key="dash_modelo_busca")
    if busca.strip():
        filtrado = filtrado[filtrado["descricao"].fillna("").astype(str).str.contains(busca.strip(), case=False, na=False)]

    q1,q2,q3 = st.columns(3)
    q1.metric("Modelos encontrados", len(filtrado))
    q2.metric("Quantidade disponível", int(filtrado["quantidade"].sum()))
    q3.metric("Valor do estoque filtrado", brl(float(filtrado["valor_estoque"].sum())))

    tabela = filtrado[[c for c in ["origem","marca","descricao","quantidade","estoque_minimo","preco_unitario","valor_estoque"] if c in filtrado.columns]].copy()
    tabela = tabela.sort_values(["marca","descricao"]) if not tabela.empty else tabela
    st.dataframe(
        tabela, hide_index=True, use_container_width=True, height=390,
        column_config={
            "preco_unitario": st.column_config.NumberColumn("Preço unitário", format="R$ %.2f"),
            "valor_estoque": st.column_config.NumberColumn("Valor em estoque", format="R$ %.2f"),
            "quantidade": st.column_config.NumberColumn("Quantidade", format="%d"),
        }
    )
    st.markdown("</div>", unsafe_allow_html=True)

    # Top 10 por marca no lugar das movimentações
    left,right = st.columns([1.2,1], gap="medium")
    with left:
        st.markdown('<div class="panel"><div class="panel-title">📊 Quantidade por marca — Top 10</div>', unsafe_allow_html=True)
        top10 = (df.groupby("marca", as_index=False)["quantidade"].sum()
                   .sort_values("quantidade", ascending=False).head(10))
        fig_bar = px.bar(top10.sort_values("quantidade"), x="quantidade", y="marca",
                         orientation="h", text="quantidade")
        fig_bar.update_layout(height=355, margin=dict(l=5,r=10,t=10,b=10),
                              xaxis_title="Quantidade", yaxis_title="",
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        fig_bar.update_traces(textposition="outside")
        st.plotly_chart(fig_bar, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown('<div class="panel"><div class="panel-title">📈 Valor do estoque por origem</div>', unsafe_allow_html=True)
        por_origem = df.groupby("origem",as_index=False)["valor_estoque"].sum()
        fig_pie = px.pie(por_origem,names="origem",values="valor_estoque",hole=.56)
        fig_pie.update_traces(textposition="inside",textinfo="percent")
        fig_pie.update_layout(height=355,margin=dict(l=5,r=5,t=10,b=10),
                              legend_title_text="",paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_pie,use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # Alertas permanecem clicáveis
    st.markdown('<div class="panel"><div class="panel-title">🔔 Alertas de estoque</div>'
                '<div class="panel-sub">Clique para visualizar os produtos relacionados</div>',
                unsafe_allow_html=True)
    a1,a2 = st.columns(2)
    with a1:
        st.markdown(f'<div class="alert-red">🚨 {len(zerados)} produto(s) com estoque zerado.</div>', unsafe_allow_html=True)
        if st.button("Ver produtos zerados ❯",key="v6_zero",use_container_width=True):
            st.session_state["v6_show_zero"] = not st.session_state.get("v6_show_zero",False)
    with a2:
        st.markdown(f'<div class="alert-yellow">⚠️ {len(baixos)} produto(s) estão no limite mínimo definido.</div>',unsafe_allow_html=True)
        if st.button("Ver produtos no limite ❯",key="v6_low",use_container_width=True):
            st.session_state["v6_show_low"] = not st.session_state.get("v6_show_low",False)

    if st.session_state.get("v6_show_zero",False):
        z=zerados[[c for c in ["origem","marca","descricao","quantidade","estoque_minimo","preco_unitario"] if c in zerados.columns]]
        st.dataframe(z,hide_index=True,use_container_width=True,height=330)
    if st.session_state.get("v6_show_low",False):
        b=baixos[[c for c in ["origem","marca","descricao","quantidade","estoque_minimo","preco_unitario"] if c in baixos.columns]].sort_values("quantidade")
        st.dataframe(b,hide_index=True,use_container_width=True,height=390)
    st.markdown("</div>",unsafe_allow_html=True)

    st.markdown('<div class="footer-box"><span><b>PNEUAÇO Estoque</b> — Sistema de Controle de Estoque</span>'
                '<span>Dashboard Gerencial</span><span>Controle e rastreabilidade</span></div>',unsafe_allow_html=True)


def estoque():
    st.title("📦 Estoque — Todas as origens")
    df = load_products()
    q = st.text_input("Pesquisar por descrição ou marca")
    if q and not df.empty:
        mask = df["descricao"].str.contains(q, case=False, na=False) | df["marca"].str.contains(q, case=False, na=False)
        df = df[mask]

    st.dataframe(
        df[["id","origem","descricao","marca","preco_unitario","quantidade","valor_estoque"]],
        hide_index=True, use_container_width=True, height=480,
        column_config={
            "id": st.column_config.NumberColumn("ID"),
            "origem":"Origem","descricao":"Descrição","marca":"Marca",
            "preco_unitario":st.column_config.NumberColumn("Preço Unitário", format="R$ %.2f"),
            "quantidade":"Quantidade",
            "valor_estoque":st.column_config.NumberColumn("Valor em Estoque", format="R$ %.2f"),
        }
    )

    st.markdown("---")
    st.subheader("💰 Alterar valor de pneu")
    st.caption("Selecione o produto, confira o valor atual e informe o novo preço unitário.")

    perfil_preco = str(st.session_state.get("perfil", "")).upper()
    if perfil_preco not in ("ADMINISTRADOR", "GERENTE"):
        st.info("A alteração de preços está disponível somente para ADMINISTRADOR ou GERENTE.")
    else:
        todos_precos = load_products()
        origem_preco = st.selectbox(
            "Filtrar origem para alteração de preço",
            ["TODAS","PNEUS COM NOTA","PNEUS SEM NOTA","DIESEL PNEUS"],
            key="preco_origem"
        )
        base_preco = todos_precos if origem_preco == "TODAS" else todos_precos[todos_precos["origem"] == origem_preco]

        busca_preco = st.text_input(
            "Pesquisar pneu para alterar preço",
            placeholder="Digite medida, marca ou parte da descrição...",
            key="preco_busca"
        ).strip()

        if busca_preco and not base_preco.empty:
            m = (
                base_preco["descricao"].str.contains(busca_preco, case=False, na=False)
                | base_preco["marca"].str.contains(busca_preco, case=False, na=False)
            )
            base_preco = base_preco[m]

        if base_preco.empty:
            st.warning("Nenhum pneu encontrado para esse filtro.")
        else:
            opcoes_preco = {
                f"{int(r.id)} — {r.descricao} | {r.origem} | Atual: {brl(r.preco_unitario)}": int(r.id)
                for r in base_preco.itertuples()
            }

            produto_label = st.selectbox(
                "Produto",
                list(opcoes_preco.keys()),
                key="preco_produto"
            )
            produto_id = opcoes_preco[produto_label]
            produto_row = todos_precos[todos_precos["id"] == produto_id].iloc[0]

            p1,p2,p3 = st.columns([1.2,1.2,1])
            with p1:
                st.metric("Preço atual", brl(produto_row["preco_unitario"]))
            with p2:
                novo_preco = st.number_input(
                    "Novo preço unitário",
                    min_value=0.0,
                    value=float(produto_row["preco_unitario"] or 0),
                    step=10.0,
                    format="%.2f",
                    key=f"novo_preco_{produto_id}"
                )
            with p3:
                st.metric(
                    "Novo valor em estoque",
                    brl(float(novo_preco) * float(produto_row["quantidade"] or 0))
                )

            confirmar_preco = st.checkbox(
                f"Confirmo a alteração do preço do produto ID {produto_id}.",
                key=f"confirmar_preco_{produto_id}"
            )

            if st.button(
                "💾 Salvar novo preço",
                type="primary",
                disabled=not confirmar_preco,
                key=f"salvar_preco_{produto_id}"
            ):
                preco_anterior = float(produto_row["preco_unitario"] or 0)
                if abs(float(novo_preco) - preco_anterior) < 0.0001:
                    st.info("O novo preço é igual ao preço atual. Nenhuma alteração foi feita.")
                else:
                    with engine.begin() as conn:
                        conn.execute(
                            text("""
                                UPDATE produtos
                                SET preco_unitario=:novo,
                                    atualizado_em=CURRENT_TIMESTAMP
                                WHERE id=:id
                            """),
                            {"novo": float(novo_preco), "id": int(produto_id)}
                        )
                    registrar_auditoria(
                        tipo="ALTERAÇÃO DE PREÇO", produto_id=int(produto_id),
                        descricao=str(produto_row["descricao"]), origem=str(produto_row["origem"]),
                        valor_anterior=preco_anterior, valor_novo=float(novo_preco),
                        motivo="Alteração manual de preço",
                        observacao="Alteração realizada pela aba Estoque."
                    )
                    st.success(
                        f"Preço alterado com sucesso: {brl(preco_anterior)} → {brl(novo_preco)}"
                    )
                    st.rerun()


    with st.expander("➕ Cadastrar novo pneu"):
        with st.form("novo_produto"):
            origem_nova = st.selectbox("Origem", ["PNEUS COM NOTA","PNEUS SEM NOTA","DIESEL PNEUS"])
            descricao = st.text_input("Descrição")
            marca_digitada = st.text_input("Marca (opcional)").upper()
            preco = st.number_input("Preço unitário", min_value=0.0, step=10.0)
            qtd = st.number_input("Quantidade inicial", min_value=0, step=1)
            nf = st.text_input("NF")
            fornecedor = st.text_input("Fornecedor")
            if st.form_submit_button("Salvar produto", type="primary"):
                if not descricao.strip():
                    st.error("Informe a descrição.")
                else:
                    marca = marca_digitada.strip() or detect_brand(descricao)
                    with engine.begin() as conn:
                        res = conn.execute(text("""
                            INSERT INTO produtos(origem,descricao,marca,preco_unitario,quantidade,ativo)
                            VALUES (:origem,:d,:m,:p,:q,:a)
                        """), {"origem":origem_nova,"d":descricao.strip(),"m":marca,"p":float(preco),"q":int(qtd),"a":True if is_online_db() else 1})
                        # PostgreSQL can return id with RETURNING, SQLite via lastrowid is not portable here.
                        pid = conn.execute(text("SELECT MAX(id) FROM produtos")).scalar_one()
                        if qtd:
                            conn.execute(text("""
                                INSERT INTO movimentacoes
                                (produto_id,tipo,quantidade,usuario,nf,fornecedor_destino,observacao,estoque_anterior,estoque_atual)
                                VALUES (:pid,'ENTRADA',:q,:u,:nf,:fd,'Estoque inicial',0,:q)
                            """), {"pid":pid,"q":int(qtd),"u":st.session_state["user"],"nf":nf,"fd":fornecedor})
                    st.success("Produto cadastrado.")
                    st.rerun()

    st.markdown("---")
    st.subheader("⚙️ Configurar estoque mínimo")
    st.caption("Defina o limite mínimo individual de cada pneu. A Dashboard usará esse valor nos alertas.")

    if st.session_state.get("perfil") in ["ADMINISTRADOR","GERENTE"]:
        df_min = load_products()
        if not df_min.empty:
            cmin1, cmin2 = st.columns([1,2])
            with cmin1:
                origem_min = st.selectbox(
                    "Origem para configurar",
                    ["TODAS","PNEUS COM NOTA","PNEUS SEM NOTA","DIESEL PNEUS"],
                    key="estoque_min_origem"
                )
            base_min = df_min if origem_min == "TODAS" else df_min[df_min["origem"] == origem_min]

            with cmin2:
                busca_min = st.text_input(
                    "Pesquisar pneu",
                    placeholder="Digite medida, marca ou descrição...",
                    key="estoque_min_busca"
                ).strip()

            if busca_min:
                base_min = base_min[
                    base_min["descricao"].fillna("").astype(str).str.contains(busca_min, case=False, na=False) |
                    base_min["marca"].fillna("").astype(str).str.contains(busca_min, case=False, na=False)
                ]

            if not base_min.empty:
                opcoes_min = {
                    f'{r["descricao"]} | {r["origem"]} | atual: {int(r["quantidade"])} | mínimo: {int(r.get("estoque_minimo",2) or 2)}': int(r["id"])
                    for _, r in base_min.iterrows()
                }
                escolha_min = st.selectbox("Selecione o produto", list(opcoes_min.keys()), key="estoque_min_produto")
                pid_min = opcoes_min[escolha_min]
                linha_min = df_min[df_min["id"] == pid_min].iloc[0]

                novo_min = st.number_input(
                    "Estoque mínimo desejado",
                    min_value=0,
                    step=1,
                    value=int(linha_min.get("estoque_minimo",2) or 2),
                    key="estoque_min_valor"
                )

                if st.button("💾 Salvar estoque mínimo", key="salvar_estoque_min", use_container_width=True):
                    minimo_anterior = int(linha_min.get("estoque_minimo",2) or 2)
                    with engine.begin() as conn:
                        conn.execute(
                            text("UPDATE produtos SET estoque_minimo=:m WHERE id=:id"),
                            {"m": int(novo_min), "id": int(pid_min)}
                        )
                    try:
                        registrar_auditoria(
                            "ALTERAÇÃO DE ESTOQUE MÍNIMO",
                            produto_id=int(pid_min),
                            descricao=str(linha_min["descricao"]),
                            origem=str(linha_min["origem"]),
                            quantidade_anterior=minimo_anterior,
                            quantidade_nova=int(novo_min),
                            observacao="Limite mínimo de estoque alterado."
                        )
                    except Exception:
                        pass
                    st.success(f"Estoque mínimo atualizado para {int(novo_min)} unidade(s).")
                    st.rerun()
        else:
            st.info("Nenhum produto encontrado.")
    else:
        st.info("Somente Administrador ou Gerente pode alterar estoque mínimo.")


def movimentacoes():
    st.title("🔄 Entrada / Saída de Estoque")
    df = load_products()
    if df.empty:
        st.info("Cadastre um produto primeiro.")
        return

    labels = {f'{r.id} — {r.descricao} | Estoque: {r.quantidade}': int(r.id) for r in df.itertuples()}
    escolhido = st.selectbox("Produto", list(labels.keys()))
    tipo = st.radio("Tipo de movimentação", ["ENTRADA","SAIDA","AJUSTE"], horizontal=True)
    qtd = st.number_input("Quantidade", min_value=0, step=1)

    c1,c2 = st.columns(2)
    with c1:
        nf = st.text_input("NF")
    with c2:
        destino = st.text_input("Fornecedor / Destino / Motorista")
    obs = st.text_input("Observação")

    if st.button("Confirmar movimentação", type="primary"):
        pid = labels[escolhido]
        with engine.begin() as conn:
            atual = conn.execute(text("SELECT quantidade FROM produtos WHERE id=:id"), {"id":pid}).scalar_one()

            if tipo == "ENTRADA":
                novo = atual + int(qtd)
            elif tipo == "SAIDA":
                if int(qtd) > atual:
                    st.error(f"Saída maior que o estoque atual ({atual}).")
                    st.stop()
                novo = atual - int(qtd)
            else:
                novo = int(qtd)

            conn.execute(text("""
                UPDATE produtos SET quantidade=:novo, atualizado_em=CURRENT_TIMESTAMP WHERE id=:id
            """), {"novo":novo,"id":pid})

            conn.execute(text("""
                INSERT INTO movimentacoes
                (produto_id,tipo,quantidade,usuario,nf,fornecedor_destino,observacao,estoque_anterior,estoque_atual)
                VALUES (:pid,:tipo,:q,:u,:nf,:fd,:obs,:ant,:novo)
            """), {
                "pid":pid,"tipo":tipo,"q":int(qtd),"u":st.session_state["user"],
                "nf":nf,"fd":destino,"obs":obs,"ant":atual,"novo":novo
            })
        produto_info = df[df["id"] == pid].iloc[0]
        registrar_auditoria(
            tipo=f"MOVIMENTAÇÃO - {tipo}", produto_id=int(pid),
            descricao=str(produto_info["descricao"]), origem=str(produto_info["origem"]),
            quantidade_anterior=int(atual), quantidade_movimentada=int(qtd),
            quantidade_nova=int(novo), nf=nf, destino=destino, motivo=tipo, observacao=obs
        )
        st.success(f"Movimentação registrada. Estoque: {atual} → {novo}")
        st.rerun()

    hist = pd.read_sql_query(text("""
        SELECT m.id, m.data_movimento, m.usuario, p.descricao, p.marca,
               m.tipo, m.quantidade, m.estoque_anterior, m.estoque_atual,
               m.nf, m.fornecedor_destino, m.observacao
        FROM movimentacoes m
        JOIN produtos p ON p.id=m.produto_id
        ORDER BY m.id DESC
        LIMIT 500
    """), engine)
    st.subheader("Histórico de movimentações")
    st.dataframe(hist, hide_index=True, use_container_width=True, height=430)


def ficha_produto():
    st.title("🧾 Ficha do Produto")
    st.caption("Consulte estoque, preço, origem e todo o histórico de um pneu em uma única tela.")

    df = load_products()
    if df.empty:
        st.info("Nenhum produto encontrado.")
        return

    df = df.copy()
    df["quantidade"] = pd.to_numeric(df["quantidade"], errors="coerce").fillna(0)
    if "estoque_minimo" not in df.columns:
        df["estoque_minimo"] = 2
    df["estoque_minimo"] = pd.to_numeric(df["estoque_minimo"], errors="coerce").fillna(2)
    df["preco_unitario"] = pd.to_numeric(df["preco_unitario"], errors="coerce").fillna(0)
    df["valor_estoque"] = pd.to_numeric(df["valor_estoque"], errors="coerce").fillna(0)

    c1, c2 = st.columns([1, 2])
    with c1:
        origem = st.selectbox(
            "Origem",
            ["TODAS", "PNEUS COM NOTA", "PNEUS SEM NOTA", "DIESEL PNEUS"],
            key="ficha_origem"
        )
    base = df if origem == "TODAS" else df[df["origem"] == origem]

    with c2:
        busca = st.text_input(
            "Pesquisar pneu",
            placeholder="Digite medida, marca ou parte da descrição...",
            key="ficha_busca"
        ).strip()

    if busca:
        base = base[
            base["descricao"].fillna("").astype(str).str.contains(busca, case=False, na=False) |
            base["marca"].fillna("").astype(str).str.contains(busca, case=False, na=False)
        ]

    if base.empty:
        st.warning("Nenhum produto encontrado com esse filtro.")
        return

    opcoes = {}
    for _, r in base.sort_values(["marca","descricao"]).iterrows():
        label = f'{r["descricao"]} | {r["origem"]} | Qtd: {int(r["quantidade"])}'
        opcoes[label] = int(r["id"])

    escolha = st.selectbox("Selecione o produto", list(opcoes.keys()), key="ficha_produto_sel")
    produto_id = opcoes[escolha]
    prod = df[df["id"] == produto_id].iloc[0]

    st.markdown("---")
    st.subheader(str(prod["descricao"]))

    k1,k2,k3,k4,k5 = st.columns(5)
    k1.metric("Origem", str(prod["origem"]))
    k2.metric("Quantidade atual", int(prod["quantidade"]))
    k3.metric("Estoque mínimo", int(prod["estoque_minimo"]))
    k4.metric("Preço unitário", brl(float(prod["preco_unitario"])))
    k5.metric("Valor em estoque", brl(float(prod["valor_estoque"])))

    status_qtd = int(prod["quantidade"])
    minimo_qtd = int(prod["estoque_minimo"])
    if status_qtd <= 0:
        st.error("🚨 Este produto está com estoque zerado.")
    elif status_qtd <= minimo_qtd:
        st.warning(f"⚠️ Este produto está no limite mínimo definido ({minimo_qtd}).")
    else:
        st.success("✅ Estoque acima do mínimo.")

    st.markdown("### 📜 Histórico do produto")

    partes = []

    # Movimentações
    try:
        mov = pd.read_sql_query(
            text("SELECT * FROM movimentacoes WHERE produto_id=:pid"),
            engine,
            params={"pid": int(produto_id)}
        )
        if not mov.empty:
            data_col = next((c for c in ["data_hora","data_movimento","criado_em","data"] if c in mov.columns), None)
            qtd_col = next((c for c in ["quantidade","qtd"] if c in mov.columns), None)

            hist_mov = pd.DataFrame()
            hist_mov["data_hora"] = pd.to_datetime(mov[data_col], errors="coerce") if data_col else pd.NaT
            hist_mov["tipo"] = mov["tipo"] if "tipo" in mov.columns else "MOVIMENTAÇÃO"
            hist_mov["usuario"] = mov["usuario"] if "usuario" in mov.columns else ""
            hist_mov["quantidade"] = mov[qtd_col] if qtd_col else None
            hist_mov["valor_anterior"] = None
            hist_mov["valor_novo"] = None
            hist_mov["documento"] = mov["documento"] if "documento" in mov.columns else (mov["nf"] if "nf" in mov.columns else "")
            hist_mov["observacao"] = mov["observacao"] if "observacao" in mov.columns else ""
            hist_mov["fonte"] = "MOVIMENTAÇÃO"
            partes.append(hist_mov)
    except Exception:
        pass

    # Auditoria
    try:
        aud = pd.read_sql_query(
            text("""
                SELECT data_hora, tipo, usuario, quantidade_movimentada AS quantidade,
                       valor_anterior, valor_novo,
                       COALESCE(nf,'') AS documento, observacao
                FROM auditoria
                WHERE produto_id=:pid
            """),
            engine,
            params={"pid": int(produto_id)}
        )
        if not aud.empty:
            aud["data_hora"] = pd.to_datetime(aud["data_hora"], errors="coerce")
            aud["fonte"] = "AUDITORIA"
            partes.append(aud)
    except Exception:
        pass

    if not partes:
        st.info("Ainda não existem registros de histórico para este produto.")
    else:
        hist = pd.concat(partes, ignore_index=True, sort=False)
        hist = hist.sort_values("data_hora", ascending=False, na_position="last")
        hist["data_hora"] = pd.to_datetime(hist["data_hora"], errors="coerce").dt.strftime("%d/%m/%Y %H:%M:%S")
        hist = hist.rename(columns={
            "data_hora":"DATA / HORA",
            "tipo":"OPERAÇÃO",
            "usuario":"USUÁRIO",
            "quantidade":"QUANTIDADE",
            "valor_anterior":"VALOR ANTERIOR",
            "valor_novo":"VALOR NOVO",
            "documento":"DOCUMENTO / NF",
            "observacao":"OBSERVAÇÃO",
            "fonte":"FONTE"
        })

        st.dataframe(
            hist,
            hide_index=True,
            use_container_width=True,
            height=470,
            column_config={
                "VALOR ANTERIOR": st.column_config.NumberColumn("VALOR ANTERIOR", format="R$ %.2f"),
                "VALOR NOVO": st.column_config.NumberColumn("VALOR NOVO", format="R$ %.2f")
            }
        )

        out = io.BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            hist.to_excel(writer, index=False, sheet_name="Ficha Produto")
        st.download_button(
            "⬇️ Exportar ficha/histórico para Excel",
            data=out.getvalue(),
            file_name=f"ficha_produto_{produto_id}_{datetime.now():%Y%m%d_%H%M}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )


def historico_auditoria():
    st.title("📜 Histórico / Auditoria")
    st.caption("Consulta unificada das movimentações antigas e dos novos registros de auditoria.")

    try:
        aud = pd.read_sql_query(text("""
            SELECT id, data_hora, usuario, tipo, produto_id, descricao, origem,
                   valor_anterior, valor_novo, quantidade_anterior,
                   quantidade_movimentada, quantidade_nova, motivo, observacao
            FROM auditoria
        """), engine)
    except Exception:
        aud = pd.DataFrame()

    # Lê a tabela original sem modificar nenhum registro.
    try:
        mov_raw = pd.read_sql_query(text("SELECT * FROM movimentacoes"), engine)
    except Exception:
        mov_raw = pd.DataFrame()

    cols = ["id","data_hora","usuario","tipo","produto_id","descricao","origem",
            "valor_anterior","valor_novo","quantidade_anterior",
            "quantidade_movimentada","quantidade_nova","motivo","observacao"]

    partes = []
    if not aud.empty:
        aud = aud.reindex(columns=cols)
        aud["fonte"] = "AUDITORIA"
        partes.append(aud)

    if not mov_raw.empty:
        mov = pd.DataFrame(index=mov_raw.index)
        for c in cols:
            mov[c] = None
        for c in ["id","data_hora","usuario","tipo","produto_id","descricao","origem","observacao"]:
            if c in mov_raw.columns:
                mov[c] = mov_raw[c]

        # Compatibilidade com os nomes usados pela tabela de movimentações atual.
        if "quantidade" in mov_raw.columns:
            mov["quantidade_movimentada"] = mov_raw["quantidade"]
        elif "qtd" in mov_raw.columns:
            mov["quantidade_movimentada"] = mov_raw["qtd"]

        if "documento" in mov_raw.columns:
            mov["motivo"] = mov_raw["documento"]
        elif "nf" in mov_raw.columns:
            mov["motivo"] = mov_raw["nf"]

        # Busca descrição/origem atual do produto quando a movimentação guarda só produto_id.
        if "produto_id" in mov_raw.columns and ("descricao" not in mov_raw.columns or "origem" not in mov_raw.columns):
            try:
                prods = pd.read_sql_query(text("SELECT id, descricao, origem FROM produtos"), engine)
                prods = prods.rename(columns={"id":"produto_id","descricao":"_desc_prod","origem":"_orig_prod"})
                mov = mov.merge(prods, on="produto_id", how="left")
                mov["descricao"] = mov["descricao"].where(mov["descricao"].notna(), mov["_desc_prod"])
                mov["origem"] = mov["origem"].where(mov["origem"].notna(), mov["_orig_prod"])
                mov = mov.drop(columns=["_desc_prod","_orig_prod"], errors="ignore")
            except Exception:
                pass

        mov = mov.reindex(columns=cols)
        mov["fonte"] = "MOVIMENTAÇÃO"
        partes.append(mov)

    if not partes:
        st.info("Ainda não existem registros de histórico.")
        return

    hist = pd.concat(partes, ignore_index=True)
    hist["data_hora"] = pd.to_datetime(hist["data_hora"], errors="coerce")
    hist = hist.sort_values(["data_hora","id"], ascending=[False,False], na_position="last")

    c1,c2,c3,c4 = st.columns(4)
    with c1:
        op = st.multiselect("Operação", sorted(hist["tipo"].dropna().astype(str).unique()))
    with c2:
        usr = st.multiselect("Usuário", sorted(hist["usuario"].dropna().astype(str).unique()))
    with c3:
        ori = st.multiselect("Origem", sorted(hist["origem"].dropna().astype(str).unique()))
    with c4:
        fonte = st.multiselect("Fonte", sorted(hist["fonte"].dropna().astype(str).unique()))

    busca = st.text_input("Pesquisar pneu / descrição",
                          placeholder="Digite medida, marca ou parte da descrição...").strip()

    f = hist.copy()
    if op: f = f[f["tipo"].astype(str).isin(op)]
    if usr: f = f[f["usuario"].astype(str).isin(usr)]
    if ori: f = f[f["origem"].astype(str).isin(ori)]
    if fonte: f = f[f["fonte"].astype(str).isin(fonte)]
    if busca:
        f = f[f["descricao"].fillna("").astype(str).str.contains(busca, case=False, na=False)]

    k1,k2,k3 = st.columns(3)
    k1.metric("Registros encontrados", len(f))
    k2.metric("Movimentações", int((f["fonte"]=="MOVIMENTAÇÃO").sum()))
    k3.metric("Auditorias", int((f["fonte"]=="AUDITORIA").sum()))

    exib = f.copy()
    exib["data_hora"] = exib["data_hora"].dt.strftime("%d/%m/%Y %H:%M:%S")
    exib = exib.rename(columns={
        "data_hora":"DATA / HORA","usuario":"USUÁRIO","tipo":"OPERAÇÃO",
        "descricao":"PNEU / DESCRIÇÃO","origem":"ORIGEM",
        "valor_anterior":"VALOR ANTERIOR","valor_novo":"VALOR NOVO",
        "quantidade_anterior":"QTD. ANTERIOR","quantidade_movimentada":"MOVIMENTAÇÃO",
        "quantidade_nova":"QTD. FINAL","motivo":"DOCUMENTO / MOTIVO",
        "observacao":"OBSERVAÇÃO","fonte":"FONTE"
    })
    mostrar = ["DATA / HORA","USUÁRIO","OPERAÇÃO","PNEU / DESCRIÇÃO","ORIGEM",
               "MOVIMENTAÇÃO","QTD. ANTERIOR","QTD. FINAL","VALOR ANTERIOR","VALOR NOVO",
               "DOCUMENTO / MOTIVO","OBSERVAÇÃO","FONTE"]
    exib = exib[[c for c in mostrar if c in exib.columns]]

    st.dataframe(exib, hide_index=True, use_container_width=True, height=580,
        column_config={
            "VALOR ANTERIOR": st.column_config.NumberColumn("VALOR ANTERIOR", format="R$ %.2f"),
            "VALOR NOVO": st.column_config.NumberColumn("VALOR NOVO", format="R$ %.2f")
        })

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        exib.to_excel(writer, index=False, sheet_name="Historico Unificado")
    st.download_button("⬇️ Exportar histórico filtrado", out.getvalue(),
        file_name=f"historico_unificado_{datetime.now():%Y%m%d_%H%M}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True)


def relatorios():
    st.title("📊 Relatórios")
    df = load_products()

    c1, c2 = st.columns(2)
    with c1:
        origem_relatorio = st.selectbox(
            "Origem",
            ["TODAS", "PNEUS COM NOTA", "PNEUS SEM NOTA", "DIESEL PNEUS"],
            key="relatorio_origem"
        )

    base = df if origem_relatorio == "TODAS" else df[df["origem"] == origem_relatorio]

    with c2:
        marcas_disponiveis = sorted(base["marca"].dropna().unique()) if not base.empty else []
        marca = st.multiselect("Marca", marcas_disponiveis)

    f = base if not marca else base[base["marca"].isin(marca)]

    resumo = (
        f.groupby("marca", as_index=False)
         .agg(Modelos=("id","count"), Quantidade=("quantidade","sum"), Valor=("valor_estoque","sum"))
         .sort_values("Quantidade", ascending=False)
    ) if not f.empty else pd.DataFrame(columns=["marca","Modelos","Quantidade","Valor"])

    st.dataframe(
        resumo,
        hide_index=True,
        use_container_width=True,
        column_config={"Valor": st.column_config.NumberColumn("Valor", format="R$ %.2f")}
    )

    total_qtd = int(f["quantidade"].sum()) if not f.empty else 0
    total_valor = float(f["valor_estoque"].sum()) if not f.empty else 0

    m1, m2, m3 = st.columns(3)
    m1.metric("Modelos", len(f))
    m2.metric("Quantidade", total_qtd)
    m3.metric("Valor em estoque", brl(total_valor))

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        f.to_excel(writer, index=False, sheet_name="Estoque")
        resumo.to_excel(writer, index=False, sheet_name="Resumo por Marca")

    nomes_arquivo = {
        "TODAS": "todas_origens",
        "PNEUS COM NOTA": "pneus_com_nota",
        "PNEUS SEM NOTA": "pneus_sem_nota",
        "DIESEL PNEUS": "diesel_pneus",
    }

    st.download_button(
        f"⬇️ Exportar {origem_relatorio} para Excel",
        data=output.getvalue(),
        file_name=f"estoque_{nomes_arquivo[origem_relatorio]}_{datetime.now():%Y%m%d_%H%M}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

def usuarios():
    st.title("👥 Usuários")
    st.warning("Troque a senha do usuário admin assim que publicar o sistema online.")
    with st.form("novo_usuario"):
        nome = st.text_input("Novo usuário")
        senha = st.text_input("Senha", type="password")
        perfil_novo = st.selectbox("Perfil", ["VENDEDOR","GERENTE","ADMINISTRADOR"])
        if st.form_submit_button("Criar usuário", type="primary"):
            if not nome.strip() or not senha:
                st.error("Informe usuário e senha.")
            else:
                try:
                    with engine.begin() as conn:
                        conn.execute(
                            text("INSERT INTO usuarios(nome,senha,ativo,perfil) VALUES (:n,:s,:a,:p)"),
                            {"n":nome.strip(),"s":senha,"a":True if is_online_db() else 1,"p":perfil_novo}
                        )
                    st.success("Usuário criado.")
                except Exception as e:
                    st.error(f"Não foi possível criar: {e}")

    users = pd.read_sql_query(text("SELECT id,nome,ativo,COALESCE(perfil,'ADMINISTRADOR') AS perfil FROM usuarios ORDER BY nome"), engine)
    st.dataframe(users, hide_index=True, use_container_width=True)

if not login():
    st.stop()

st.sidebar.title("🛞 PNEUAÇO")
st.sidebar.markdown("**ESTOQUE**")
st.sidebar.markdown(f"👤 **{st.session_state.get('user','')}**  \\n{st.session_state.get('perfil','').title()}")
perfil_atual = str(st.session_state.get("perfil", "")).upper()
menu_opcoes = ["Dashboard","Estoque","Movimentações","Relatórios"]
if perfil_atual in ("ADMINISTRADOR","GERENTE"):
    menu_opcoes.append("Histórico")
    menu_opcoes.append("Aprovações")
if perfil_atual == "ADMINISTRADOR":
    menu_opcoes.append("Usuários")

pagina = st.sidebar.radio("Menu", menu_opcoes)

if st.sidebar.button("Sair"):
    st.session_state.clear()
    st.rerun()

if pagina == "Dashboard":
    dashboard()
elif pagina == "Estoque":
    estoque()
elif pagina == "Movimentações":
    movimentacoes()
elif pagina == "Relatórios":
    relatorios()
elif pagina == "Ficha do Produto":
    ficha_produto()
elif pagina == "Histórico":
    historico_auditoria()
elif pagina == "Aprovações":
    aprovacoes()
elif pagina == "Usuários":
    usuarios()
