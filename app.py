
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
.stApp { background:#fff; }
.block-container { padding-top:1.1rem; padding-bottom:2rem; }
.hero {
  background:linear-gradient(100deg,#031f45,#073a77);
  color:white; padding:24px 28px; border-radius:14px; margin-bottom:16px;
}
.hero h1 { margin:0; font-size:34px; }
.hero p { margin:7px 0 0; opacity:.9; font-size:15px; }
.kpi {
  border:1px solid #d7e0ec; border-radius:14px; padding:18px 20px;
  background:white; min-height:120px;
}
.kpi .lbl { font-weight:700; font-size:13px; color:#111827; }
.kpi .val { font-weight:800; font-size:26px; color:#061f43; margin-top:10px; }
.section-title {
  background:linear-gradient(100deg,#062b59,#073a77);
  color:white; padding:10px 14px; border-radius:10px 10px 0 0;
  font-weight:800; margin-top:8px;
}
.okbox {
  background:#edf8f1; border:1px solid #b7e0c4; padding:12px 14px;
  border-radius:10px; color:#155d2f; margin-bottom:12px;
}
.warnbox {
  background:#fff7e6; border:1px solid #f2d59b; padding:12px 14px;
  border-radius:10px; color:#7a5200; margin-bottom:12px;
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
        return create_engine(url, pool_pre_ping=True, future=True)
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

def load_products(active_only=True):
    q = """
        SELECT id, origem, descricao, marca, preco_unitario, quantidade,
               preco_unitario * quantidade AS valor_estoque, ativo
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
    df = load_products()
    st.markdown("""
    <div class="hero">
      <h1>🛞 DASHBOARD — ESTOQUE DE PNEUS</h1>
      <p>Base integrada com identificação de origem: PNEUS COM NOTA e DIESEL PNEUS.</p>
    </div>
    """, unsafe_allow_html=True)

    if is_online_db():
        st.markdown('<div class="okbox">🟢 Banco online PostgreSQL/Supabase conectado.</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="warnbox">🟡 Modo local: configure DATABASE_URL para usar PostgreSQL/Supabase online.</div>', unsafe_allow_html=True)

    total_pneus = int(df["quantidade"].sum()) if not df.empty else 0
    valor_total = float(df["valor_estoque"].sum()) if not df.empty else 0
    nota = df[df["origem"] == "PNEUS COM NOTA"]
    diesel = df[df["origem"] == "DIESEL PNEUS"]

    c1,c2,c3,c4 = st.columns(4)
    cards = [
        (c1, "TOTAL DE PNEUS", f"{total_pneus:,}".replace(",","."), "unidades"),
        (c2, "VALOR TOTAL EM ESTOQUE", brl(valor_total), ""),
        (c3, "PNEUS COM NOTA", f"{int(nota['quantidade'].sum()):,}".replace(",","."), f"{len(nota)} modelos"),
        (c4, "DIESEL PNEUS", f"{int(diesel['quantidade'].sum()):,}".replace(",","."), f"{len(diesel)} modelos"),
    ]
    for col,label,value,suffix in cards:
        with col:
            st.markdown(
                f'<div class="kpi"><div class="lbl">{label}</div>'
                f'<div class="val">{value}</div><div>{suffix}</div></div>',
                unsafe_allow_html=True
            )

    f1,f2 = st.columns(2)
    with f1:
        origem = st.selectbox("Origem do estoque", ["TODAS","PNEUS COM NOTA","DIESEL PNEUS"])
    base = df if origem == "TODAS" else df[df["origem"] == origem]
    with f2:
        marcas = ["TODAS"] + sorted(base["marca"].dropna().unique().tolist()) if not base.empty else ["TODAS"]
        marca = st.selectbox("Marca", marcas)

    filtro = base if marca == "TODAS" else base[base["marca"] == marca]

    col_graf, col_tab = st.columns([0.9,1.1], gap="large")
    with col_graf:
        st.markdown('<div class="section-title">QUANTIDADE POR MARCA (TOP 10)</div>', unsafe_allow_html=True)
        if not filtro.empty:
            top = (filtro.groupby("marca", as_index=False)["quantidade"].sum()
                         .sort_values("quantidade", ascending=False).head(10)
                         .sort_values("quantidade", ascending=True))
            fig = px.bar(top, x="quantidade", y="marca", orientation="h",
                         text="quantidade", labels={"marca":"","quantidade":"Quantidade"})
            fig.update_layout(height=500, margin=dict(l=10,r=10,t=15,b=20),
                              showlegend=False, plot_bgcolor="white", paper_bgcolor="white")
            fig.update_traces(marker_color="#2f78d0", textposition="outside")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Nenhum produto encontrado para o filtro.")

    with col_tab:
        st.markdown('<div class="section-title">MODELOS / ORIGEM DO ESTOQUE</div>', unsafe_allow_html=True)
        show = filtro[["origem","descricao","marca","quantidade","valor_estoque"]].copy()
        show.columns = ["ORIGEM","MODELO / DESCRIÇÃO","MARCA","QUANTIDADE","VALOR EM ESTOQUE"]
        if not show.empty:
            show["VALOR EM ESTOQUE"] = show["VALOR EM ESTOQUE"].map(brl)
        st.dataframe(show, hide_index=True, use_container_width=True, height=500)
        st.caption(f"Total de modelos encontrados: **{len(show)}**")

def estoque():
    st.title("📦 Estoque — PNEUS COM NOTA + DIESEL PNEUS")
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

    with st.expander("➕ Cadastrar novo pneu"):
        with st.form("novo_produto"):
            origem_nova = st.selectbox("Origem", ["PNEUS COM NOTA","DIESEL PNEUS"])
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

def relatorios():
    st.title("📊 Relatórios")
    df = load_products()
    marca = st.multiselect("Marca", sorted(df["marca"].dropna().unique()) if not df.empty else [])
    f = df if not marca else df[df["marca"].isin(marca)]

    resumo = (f.groupby("marca", as_index=False)
               .agg(Modelos=("id","count"), Quantidade=("quantidade","sum"), Valor=("valor_estoque","sum"))
               .sort_values("Quantidade", ascending=False)) if not f.empty else pd.DataFrame(columns=["marca","Modelos","Quantidade","Valor"])
    st.dataframe(resumo, hide_index=True, use_container_width=True,
                 column_config={"Valor":st.column_config.NumberColumn("Valor", format="R$ %.2f")})

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        f.to_excel(writer, index=False, sheet_name="PNEUS COM NOTA")
        resumo.to_excel(writer, index=False, sheet_name="Resumo por Marca")
    st.download_button(
        "⬇️ Exportar relatório para Excel",
        data=output.getvalue(),
        file_name=f"pneus_com_nota_{datetime.now():%Y%m%d_%H%M}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def aprovacoes():
    st.title("📋 Aprovações de Orçamentos")

    perfil = str(st.session_state.get("perfil", "")).upper()
    if perfil not in ("ADMINISTRADOR", "GERENTE"):
        st.error("Seu usuário não possui permissão para aprovar orçamentos.")
        return

    pendentes = pd.read_sql_query(text("""
        SELECT id, numero, criado_em, vendedor, cliente_nome,
               subtotal, desconto_percentual, desconto_valor, total, status
        FROM orcamentos
        WHERE status IN ('PENDENTE_APROVACAO','AGUARDANDO_APROVACAO')
        ORDER BY criado_em ASC, numero ASC
    """), engine)

    if pendentes.empty:
        st.success("✅ Nenhum orçamento aguardando aprovação.")
    else:
        st.info(f"🔔 {len(pendentes)} orçamento(s) aguardando aprovação.")

        for o in pendentes.itertuples():
            titulo = (
                f"Orçamento Nº {int(o.numero)} — {o.cliente_nome} — "
                f"{float(o.desconto_percentual or 0):.2f}% de desconto — {brl(o.total)}"
            )
            with st.expander(titulo):
                a, b, c, d = st.columns(4)
                a.metric("Vendedor", str(o.vendedor))
                b.metric("Subtotal", brl(o.subtotal))
                c.metric("Desconto", f"{float(o.desconto_percentual or 0):.2f}%")
                d.metric("Total", brl(o.total))

                itens = pd.read_sql_query(text("""
                    SELECT descricao, quantidade, valor_unitario, valor_total
                    FROM orcamento_itens
                    WHERE orcamento_id=:oid
                    ORDER BY id
                """), engine, params={"oid": int(o.id)})

                if not itens.empty:
                    st.dataframe(
                        itens,
                        hide_index=True,
                        use_container_width=True,
                        column_config={
                            "descricao": "Produto",
                            "quantidade": st.column_config.NumberColumn("Quantidade", format="%.0f"),
                            "valor_unitario": st.column_config.NumberColumn("Valor unitário", format="R$ %.2f"),
                            "valor_total": st.column_config.NumberColumn("Valor total", format="R$ %.2f"),
                        },
                    )

                motivo = st.text_input(
                    "Observação da decisão",
                    key=f"motivo_aprovacao_{int(o.id)}",
                    placeholder="Opcional para aprovação; recomendado em caso de recusa."
                )

                ca, cr = st.columns(2)
                with ca:
                    if st.button("✅ Aprovar", key=f"aprovar_{int(o.id)}", use_container_width=True):
                        with engine.begin() as conn:
                            conn.execute(text("""
                                UPDATE orcamentos
                                SET status='APROVADO',
                                    aprovado_por=:usuario,
                                    aprovado_em=CURRENT_TIMESTAMP,
                                    motivo_aprovacao=:motivo
                                WHERE id=:id
                                  AND status IN ('PENDENTE_APROVACAO','AGUARDANDO_APROVACAO')
                            """), {
                                "usuario": st.session_state.get("user",""),
                                "motivo": motivo.strip() or "Aprovado",
                                "id": int(o.id)
                            })
                        st.success(f"Orçamento Nº {int(o.numero)} aprovado.")
                        st.rerun()

                with cr:
                    if st.button("❌ Recusar", key=f"recusar_{int(o.id)}", use_container_width=True):
                        if not motivo.strip():
                            st.error("Informe o motivo da recusa.")
                        else:
                            with engine.begin() as conn:
                                conn.execute(text("""
                                    UPDATE orcamentos
                                    SET status='RECUSADO',
                                        aprovado_por=:usuario,
                                        aprovado_em=CURRENT_TIMESTAMP,
                                        motivo_aprovacao=:motivo
                                    WHERE id=:id
                                      AND status IN ('PENDENTE_APROVACAO','AGUARDANDO_APROVACAO')
                                """), {
                                    "usuario": st.session_state.get("user",""),
                                    "motivo": motivo.strip(),
                                    "id": int(o.id)
                                })
                            st.warning(f"Orçamento Nº {int(o.numero)} recusado.")
                            st.rerun()

    st.markdown("---")
    st.subheader("Histórico recente de decisões")
    historico = pd.read_sql_query(text("""
        SELECT numero, criado_em, vendedor, cliente_nome, desconto_percentual,
               total, status, aprovado_por, aprovado_em, motivo_aprovacao
        FROM orcamentos
        WHERE status IN ('APROVADO','RECUSADO')
        ORDER BY COALESCE(aprovado_em, criado_em) DESC
        LIMIT 100
    """), engine)

    if historico.empty:
        st.caption("Ainda não há decisões registradas.")
    else:
        st.dataframe(historico, hide_index=True, use_container_width=True, height=380)


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

st.sidebar.title("🛞 ESTOQUE DE PNEUS")
st.sidebar.caption(f"Usuário: {st.session_state.get('user','')} | Perfil: {st.session_state.get('perfil','')}")
perfil_atual = str(st.session_state.get("perfil", "")).upper()
menu_opcoes = ["Dashboard","Estoque","Movimentações","Relatórios"]
if perfil_atual in ("ADMINISTRADOR","GERENTE"):
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
elif pagina == "Aprovações":
    aprovacoes()
elif pagina == "Usuários":
    usuarios()
