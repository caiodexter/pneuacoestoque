
import os
import base64
from datetime import datetime
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from streamlit_autorefresh import st_autorefresh
from pathlib import Path
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image

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
        SELECT id AS produto_id, origem, descricao, marca, preco_unitario, quantidade
        FROM produtos
        WHERE ativo IS TRUE
        ORDER BY marca, descricao
    """), engine)

def brl(v):
    s = f"{float(v or 0):,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")



def salvar_orcamento(vendedor, cliente_nome, cliente_cnpj, cliente_telefone, cliente_email, cliente_endereco, observacoes, desconto_percentual):
    carrinho = st.session_state.get("orcamento_carrinho", {})
    subtotal = sum(float(i["quantidade"]) * float(i["valor_unitario"]) for i in carrinho.values())
    desconto_percentual = float(desconto_percentual or 0)
    desconto_valor = round(subtotal * desconto_percentual / 100, 2)
    total = round(subtotal - desconto_valor, 2)
    status = "APROVADO" if desconto_percentual <= 3 else "PENDENTE_APROVACAO"
    aprovado_por = vendedor if status == "APROVADO" else None
    motivo = None if status == "APROVADO" else f"Desconto de {desconto_percentual:.2f}% requer aprovação."
    with engine.begin() as conn:
        numero = conn.execute(text("SELECT COALESCE(MAX(numero), 7800) + 1 FROM orcamentos")).scalar_one()
        oid = conn.execute(text("""
        INSERT INTO orcamentos
        (numero,vendedor,cliente_nome,cliente_cnpj,cliente_telefone,cliente_email,cliente_endereco,
         subtotal,desconto_percentual,desconto_valor,total,status,observacoes,aprovado_por,aprovado_em,motivo_aprovacao)
        VALUES (:numero,:vendedor,:cliente_nome,:cliente_cnpj,:cliente_telefone,:cliente_email,:cliente_endereco,
         :subtotal,:dp,:dv,:total,:status,:obs,:aprovado_por,
         CASE WHEN :status='APROVADO' THEN CURRENT_TIMESTAMP ELSE NULL END,:motivo)
        RETURNING id
        """), dict(numero=numero,vendedor=vendedor,cliente_nome=cliente_nome,cliente_cnpj=cliente_cnpj,
        cliente_telefone=cliente_telefone,cliente_email=cliente_email,cliente_endereco=cliente_endereco,
        subtotal=subtotal,dp=desconto_percentual,dv=desconto_valor,total=total,status=status,obs=observacoes,
        aprovado_por=aprovado_por,motivo=motivo)).scalar_one()
        for item in carrinho.values():
            conn.execute(text("""
            INSERT INTO orcamento_itens (orcamento_id,produto_id,descricao,quantidade,valor_unitario,valor_total)
            VALUES (:oid,:pid,:desc,:qtd,:vu,:vt)
            """),dict(oid=oid,pid=item["produto_id"],desc=item["descricao"],qtd=item["quantidade"],
                       vu=item["valor_unitario"],vt=item["quantidade"]*item["valor_unitario"]))
    return numero,status,total

if "orcamento_carrinho" not in st.session_state:
    st.session_state.orcamento_carrinho = {}


def carregar_orcamento(numero):
    with engine.connect() as conn:
        cab = conn.execute(text("""
            SELECT id, numero, criado_em, vendedor, cliente_nome, cliente_cnpj,
                   cliente_telefone, cliente_email, cliente_endereco,
                   subtotal, desconto_percentual, desconto_valor, total,
                   status, observacoes, aprovado_por, aprovado_em
            FROM orcamentos
            WHERE numero=:numero
        """), {"numero": int(numero)}).mappings().fetchone()
        if not cab:
            return None, []
        itens = conn.execute(text("""
            SELECT descricao, quantidade, valor_unitario, valor_total
            FROM orcamento_itens
            WHERE orcamento_id=:oid
            ORDER BY id
        """), {"oid": cab["id"]}).mappings().fetchall()
    return dict(cab), [dict(x) for x in itens]

def gerar_pdf_orcamento(cab, itens, logo_b64=None):
    # PDF comercial PNEUAÇO - versão premium.
    # Desconto permanece apenas na regra interna do sistema:
    # no PDF do cliente aparecem os produtos e somente o TOTAL FINAL.
    buffer = BytesIO()

    azul = colors.HexColor("#062E68")
    azul2 = colors.HexColor("#0B56B3")
    azul_claro = colors.HexColor("#EAF3FF")
    azul_muito_claro = colors.HexColor("#F7FAFF")
    borda = colors.HexColor("#C9D8EC")
    verde = colors.HexColor("#198A3B")
    verde_claro = colors.HexColor("#ECF8EF")
    texto = colors.HexColor("#14213D")
    cinza = colors.HexColor("#5B677A")

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=10*mm,
        leftMargin=10*mm,
        topMargin=8*mm,
        bottomMargin=22*mm
    )

    styles = getSampleStyleSheet()
    normal = ParagraphStyle(
        "PNormal", parent=styles["Normal"], fontName="Helvetica",
        fontSize=9.0, leading=11.5, textColor=texto
    )
    small = ParagraphStyle(
        "PSmall", parent=normal, fontSize=8.0, leading=10
    )
    tiny = ParagraphStyle(
        "PTiny", parent=normal, fontSize=7.0, leading=8.5
    )
    center = ParagraphStyle(
        "PCenter", parent=small, alignment=TA_CENTER
    )
    white = ParagraphStyle(
        "PWhite", parent=small, fontName="Helvetica-Bold",
        textColor=colors.white, fontSize=8.4, leading=10
    )
    title = ParagraphStyle(
        "PTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=21, leading=24, textColor=azul, alignment=TA_CENTER,
        spaceBefore=0, spaceAfter=0
    )
    story = []

    # ---------- CABEÇALHO ----------
    logo_flow = Paragraph(
        "<b>PNEUAÇO</b><br/><font size=6>EXCELÊNCIA EM PNEUS E RODAS AGRÍCOLAS</font>",
        ParagraphStyle("LogoFallback2", parent=normal, fontSize=20, leading=14, textColor=azul)
    )
    if logo_b64:
        try:
            logo_flow = Image(
                BytesIO(base64.b64decode(logo_b64)),
                width=67*mm, height=18*mm
            )
        except Exception:
            pass

    selo = Table([[
        Paragraph(
            "<font color='white'><b>✓  QUALIDADE E CONFIANÇA</b><br/>"
            "<font size=7>PARA O SEU CAMPO</font></font>",
            center
        )
    ]], colWidths=[66*mm], rowHeights=[18*mm])
    selo.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),azul2),
        ("BOX",(0,0),(-1,-1),0.8,azul),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("LEFTPADDING",(0,0),(-1,-1),7),
        ("RIGHTPADDING",(0,0),(-1,-1),7),
    ]))

    head = Table([[logo_flow, selo]], colWidths=[118*mm, 72*mm])
    head.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("ALIGN",(1,0),(1,0),"RIGHT"),
        ("LEFTPADDING",(0,0),(-1,-1),0),
        ("RIGHTPADDING",(0,0),(-1,-1),0),
    ]))
    story += [head, Spacer(1, 3*mm), Paragraph("ORÇAMENTO / PROPOSTA COMERCIAL", title)]

    # Linha decorativa
    linha = Table([[""]], colWidths=[82*mm], rowHeights=[1.2*mm], hAlign="CENTER")
    linha.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),azul2)]))
    story += [Spacer(1, 1.5*mm), linha, Spacer(1, 3*mm)]

    emissao = cab.get("criado_em")
    emissao_txt = emissao.strftime("%d/%m/%Y às %H:%M") if hasattr(emissao, "strftime") else str(emissao or "-")
    status = str(cab.get("status") or "").upper()
    status_txt = "APROVADO" if status == "APROVADO" else status.replace("_", " ")

    meta_left = Paragraph(
        f"<b>Orçamento Nº</b> &nbsp;<font color='#0B56B3'><b>{int(cab['numero'])}</b></font>"
        f"&nbsp;&nbsp;&nbsp; | &nbsp;&nbsp;&nbsp;<b>Emissão:</b> {emissao_txt}",
        normal
    )
    status_bg = verde_claro if status == "APROVADO" else colors.HexColor("#FFF7DF")
    status_fg = verde if status == "APROVADO" else colors.HexColor("#A66A00")
    status_cell = Table([[Paragraph(f"<font color='{status_fg.hexval()}'><b>● {status_txt}</b></font>", center)]],
                        colWidths=[38*mm], rowHeights=[9*mm])
    status_cell.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),status_bg),
        ("BOX",(0,0),(-1,-1),0.7,status_fg),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ]))
    meta = Table([[meta_left, status_cell]], colWidths=[150*mm, 40*mm])
    meta.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),0),
        ("RIGHTPADDING",(0,0),(-1,-1),0),
    ]))
    story += [meta, Spacer(1, 4*mm)]

    # ---------- DADOS ----------
    def campo(rotulo, valor):
        return Paragraph(
            f"<b>{rotulo}:</b>&nbsp;&nbsp; {str(valor or '-')}",
            small
        )

    cliente = [
        [Paragraph("👤  DADOS DO CLIENTE", white)],
        [campo("Cliente / Razão Social", cab.get("cliente_nome"))],
        [campo("CNPJ / CPF", cab.get("cliente_cnpj"))],
        [campo("Telefone", cab.get("cliente_telefone"))],
        [campo("E-mail", cab.get("cliente_email"))],
        [campo("Endereço", cab.get("cliente_endereco"))],
    ]
    vendedor = [
        [Paragraph("👤  DADOS DO VENDEDOR", white)],
        [campo("Vendedor", cab.get("vendedor"))],
        [campo("Telefone", "-")],
        [campo("E-mail", "-")],
        [campo("Atendimento", "PNEUAÇO LTDA")],
        [campo("Unidade", "Lucas do Rio Verde - MT")],
    ]

    def card(data):
        t = Table(data, colWidths=[91*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),azul2),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("BOX",(0,0),(-1,-1),0.8,borda),
            ("INNERGRID",(0,1),(-1,-1),0.35,colors.HexColor("#E4EBF5")),
            ("BACKGROUND",(0,1),(-1,-1),colors.white),
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("LEFTPADDING",(0,0),(-1,-1),8),
            ("RIGHTPADDING",(0,0),(-1,-1),8),
            ("TOPPADDING",(0,0),(-1,-1),5.5),
            ("BOTTOMPADDING",(0,0),(-1,-1),5.5),
        ]))
        return t

    cards = Table([[card(cliente), card(vendedor)]], colWidths=[95*mm,95*mm])
    cards.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,0),(-1,-1),0),
        ("RIGHTPADDING",(0,0),(-1,-1),0),
    ]))
    story += [cards, Spacer(1, 5*mm)]

    # ---------- PRODUTOS ----------
    linhas = [[
        Paragraph("PRODUTO", white),
        Paragraph("QTD.", white),
        Paragraph("VALOR UNIT.", white),
        Paragraph("VALOR TOTAL", white)
    ]]
    for item in itens:
        qtd = float(item.get("quantidade") or 0)
        qtd_txt = f"{qtd:.0f}" if qtd.is_integer() else f"{qtd:.2f}".replace(".", ",")
        linhas.append([
            Paragraph(str(item.get("descricao") or ""), small),
            qtd_txt,
            brl(item.get("valor_unitario")),
            brl(item.get("valor_total"))
        ])

    produtos = Table(linhas, colWidths=[105*mm,17*mm,32*mm,36*mm], repeatRows=1)
    produtos.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),azul),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("GRID",(0,0),(-1,-1),0.45,borda),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("ALIGN",(1,1),(-1,-1),"RIGHT"),
        ("FONTSIZE",(0,1),(-1,-1),8.2),
        ("LEFTPADDING",(0,0),(-1,-1),7),
        ("RIGHTPADDING",(0,0),(-1,-1),7),
        ("TOPPADDING",(0,0),(-1,-1),6.2),
        ("BOTTOMPADDING",(0,0),(-1,-1),6.2),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,azul_muito_claro]),
    ]))
    story += [produtos, Spacer(1, 6*mm)]

    # ---------- TOTAL FINAL ----------
    total_box = Table([[
        Paragraph("TOTAL", ParagraphStyle("TotalLabelV2", parent=white, alignment=TA_CENTER, fontSize=15, leading=18)),
        Paragraph(brl(cab.get("total")), ParagraphStyle("TotalValueV2", parent=white, alignment=TA_RIGHT, fontSize=20, leading=22))
    ]], colWidths=[50*mm,72*mm], rowHeights=[17*mm], hAlign="RIGHT")
    total_box.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),azul),
        ("TEXTCOLOR",(0,0),(-1,-1),colors.white),
        ("BOX",(0,0),(-1,-1),0.9,azul),
        ("LINEAFTER",(0,0),(0,0),0.8,colors.HexColor("#8FAED5")),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),10),
        ("RIGHTPADDING",(0,0),(-1,-1),10),
    ]))
    story += [total_box, Spacer(1, 6*mm)]

    # ---------- CONDIÇÕES ----------
    cond = [[
        Paragraph("<font color='#0B56B3'><b>◉</b></font><br/><b>CONDIÇÃO DE PAGAMENTO</b><br/>A combinar", tiny),
        Paragraph("<font color='#0B56B3'><b>▣</b></font><br/><b>PRAZO DE ENTREGA</b><br/>A combinar", tiny),
        Paragraph("<font color='#0B56B3'><b>▦</b></font><br/><b>VALIDADE DA PROPOSTA</b><br/>7 dias", tiny),
        Paragraph("<font color='#0B56B3'><b>▤</b></font><br/><b>FRETE</b><br/>A combinar", tiny),
    ]]
    ct = Table(cond, colWidths=[47.5*mm]*4, rowHeights=[21*mm])
    ct.setStyle(TableStyle([
        ("BOX",(0,0),(-1,-1),0.8,borda),
        ("INNERGRID",(0,0),(-1,-1),0.5,borda),
        ("BACKGROUND",(0,0),(-1,-1),colors.white),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("LEFTPADDING",(0,0),(-1,-1),4),
        ("RIGHTPADDING",(0,0),(-1,-1),4),
    ]))
    story += [ct, Spacer(1, 5*mm)]

    # ---------- OBSERVAÇÕES ----------
    obs = str(cab.get("observacoes") or "").strip()
    obs_linhas = []
    if obs:
        obs_linhas.append(obs)
    obs_linhas += [
        "Proposta sujeita à disponibilidade de estoque até a confirmação do pedido.",
        "Valores expressos em Reais (R$)."
    ]
    obs_html = "<br/>".join(f"• {x}" for x in obs_linhas)
    obs_table = Table([
        [Paragraph("▣  OBSERVAÇÕES", white)],
        [Paragraph(obs_html, small)]
    ], colWidths=[190*mm])
    obs_table.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),azul2),
        ("BACKGROUND",(0,1),(-1,1),azul_claro),
        ("BOX",(0,0),(-1,-1),0.7,borda),
        ("LEFTPADDING",(0,0),(-1,-1),8),
        ("RIGHTPADDING",(0,0),(-1,-1),8),
        ("TOPPADDING",(0,0),(-1,-1),6),
        ("BOTTOMPADDING",(0,0),(-1,-1),6),
    ]))
    story += [obs_table, Spacer(1, 5*mm)]

    # ---------- APROVAÇÃO ----------
    aprovado_em = cab.get("aprovado_em")
    aprovado_txt = aprovado_em.strftime("%d/%m/%Y às %H:%M") if hasattr(aprovado_em, "strftime") else str(aprovado_em or "-")

    if status == "APROVADO":
        aprov_html = (
            "<font color='#198A3B'><b>✓ STATUS: APROVADO</b></font><br/>"
            f"<b>Aprovado por:</b> {cab.get('aprovado_por') or '-'}<br/>"
            f"<b>Data da aprovação:</b> {aprovado_txt}"
        )
    else:
        aprov_html = f"<b>STATUS: {status_txt}</b><br/>Aguardando conclusão do fluxo de aprovação."

    aprov = Table([[
        Paragraph(aprov_html, small),
        Paragraph("<br/><b>PNEUAÇO LTDA</b><br/><font size=7>Excelência em Pneus e Rodas Agrícolas</font>", center)
    ]], colWidths=[118*mm,72*mm], rowHeights=[24*mm])
    aprov.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),verde_claro if status=="APROVADO" else colors.HexColor("#FFF8E1")),
        ("BOX",(0,0),(-1,-1),0.9,verde if status=="APROVADO" else colors.HexColor("#D89B00")),
        ("LINEAFTER",(0,0),(0,0),0.6,colors.HexColor("#A9C9B1")),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),10),
        ("RIGHTPADDING",(0,0),(-1,-1),10),
    ]))
    story.append(aprov)

    # ---------- RODAPÉ ----------
    def rodape(canvas, _doc):
        canvas.saveState()
        w, _h = A4
        canvas.setFillColor(azul)
        canvas.rect(0, 0, w, 20*mm, stroke=0, fill=1)

        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 7.6)
        canvas.drawString(11*mm, 13.2*mm, "PNEUAÇO LTDA")
        canvas.setFont("Helvetica", 6.8)
        canvas.drawString(11*mm, 9.3*mm, "Av. da Produção, 622 - Bandeirantes - Lucas do Rio Verde/MT - CEP 78460-500")

        canvas.setFont("Helvetica-Bold", 7.2)
        canvas.drawString(109*mm, 13.2*mm, "☎  (65) 3549-1686")
        canvas.drawString(109*mm, 9.3*mm, "✉  contato@pneuaco.com.br")

        canvas.drawRightString(w-11*mm, 13.2*mm, "PNEUAÇO")
        canvas.setFont("Helvetica", 6.8)
        canvas.drawRightString(w-11*mm, 9.3*mm, "CNPJ 33.070.181/0001-81")
        canvas.restoreState()

    doc.build(story, onFirstPage=rodape, onLaterPages=rodape)
    return buffer.getvalue()

st.markdown("""
<style>
#MainMenu, footer, header {visibility:hidden}
[data-testid="stSidebar"], [data-testid="collapsedControl"] {display:none}
[data-testid="stAppViewContainer"]{background:#f5f8fc}
.block-container{max-width:1500px;padding-top:.6rem;padding-bottom:3rem}

.hero{background:white;border:1px solid #dfe7f1;border-radius:18px;padding:18px 24px;box-shadow:0 4px 16px rgba(15,35,70,.06);display:grid;grid-template-columns:minmax(260px,1fr) auto;align-items:center;gap:24px;margin-bottom:18px}
.hero-left{display:flex;flex-direction:column;gap:8px}.hero h1{margin:0;color:#082b59;font-size:clamp(24px,3vw,38px);font-weight:900}.hero p{margin:0;color:#526174}.logo{width:min(520px,100%);height:auto;display:block}.update{background:#eaf8ee;color:#177a38;border:1px solid #c5ead0;border-radius:12px;padding:11px 14px;font-weight:700;white-space:nowrap}
.public-badge{display:inline-block;background:#e8f8ed;color:#16833a;border:1px solid #bde7ca;padding:7px 11px;border-radius:8px;font-weight:800;margin-bottom:12px}
.metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:8px 0 18px}
.metric{background:#fff;border:1px solid #dfe7f1;border-radius:16px;padding:17px 18px;box-shadow:0 3px 12px rgba(15,35,70,.04)}
.metric .label{font-size:12px;font-weight:900;margin-bottom:8px}.metric .value{color:#0a2447;font-size:29px;font-weight:900}.metric .sub{color:#64748b;font-size:13px}.blue{color:#075bd8}.green{color:#0a8f34}.orange{color:#f05b08}.purple{color:#7132b9}
.section{background:#fff;border:1px solid #dfe7f1;border-radius:16px;padding:16px 18px;margin-bottom:16px;box-shadow:0 3px 12px rgba(15,35,70,.04)}
.section-title{font-size:15px;font-weight:900;color:#0a2447;margin-bottom:8px}
.results-head{display:flex;justify-content:space-between;align-items:center;gap:14px;margin:12px 0 10px;color:#334155;font-weight:700}
.product-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.product-card{background:#fff;border:1px solid #dfe7f1;border-radius:16px;padding:16px 18px;box-shadow:0 3px 12px rgba(15,35,70,.05);display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;min-height:165px}
.badge{display:inline-block;border-radius:8px;padding:5px 9px;font-size:11px;font-weight:900;margin-bottom:9px}.badge-nota{background:#e8f5ff;color:#0754a5}.badge-diesel{background:#e9f8ee;color:#0a8f34}
.desc{color:#0a2447;font-size:18px;line-height:1.25;font-weight:900;margin-bottom:10px}.meta{color:#64748b;font-size:13px;line-height:1.55}.stock-box{min-width:140px;text-align:right;align-self:center}.qty{color:#0a9939;font-size:18px;font-weight:900;margin-bottom:8px}.price{color:#064ca5;font-size:24px;font-weight:900}.price-label{color:#64748b;font-size:11px;font-weight:700}.footer-note{background:#eaf3ff;border:1px solid #d6e6fa;border-radius:12px;padding:12px 14px;color:#24476d;margin-top:16px;font-size:13px}

div[data-testid="stTextInput"] input, div[data-testid="stSelectbox"]>div>div{background:white}
@media (max-width:900px){.block-container{padding:.4rem .7rem 2rem}.hero{grid-template-columns:1fr;text-align:center;padding:14px;gap:12px}.logo{width:min(470px,96%);margin:0 auto}.update{justify-self:center;font-size:12px;padding:9px 11px}.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.metric{padding:14px}.metric .value{font-size:24px}.product-grid{grid-template-columns:1fr}.product-card{grid-template-columns:1fr auto;min-height:auto;padding:14px}}
@media (max-width:560px){.hero h1{font-size:27px}.hero p{font-size:14px}.metric .label{font-size:11px}.metric .value{font-size:22px}.section{padding:13px}.product-card{grid-template-columns:1fr;gap:8px}.stock-box{min-width:0;text-align:left;border-top:1px solid #edf2f7;padding-top:10px;display:flex;justify-content:space-between;gap:10px;align-items:end}.qty{font-size:17px;margin:0}.price{font-size:22px;text-align:right}.price-label{text-align:right}.results-head{align-items:flex-start;flex-direction:column;gap:4px}}


/* ===== AJUSTE DEFINITIVO MOBILE / IOS ===== */
:root {
    color-scheme: light !important;
}

/* Texto dos rótulos */
div[data-testid="stTextInput"] label,
div[data-testid="stSelectbox"] label,
div[data-testid="stCheckbox"] label,
div[data-testid="stCheckbox"] p {
    color: #0a2447 !important;
    -webkit-text-fill-color: #0a2447 !important;
    opacity: 1 !important;
    font-weight: 700 !important;
}

/* Campo de pesquisa */
div[data-testid="stTextInput"] input {
    color: #0a2447 !important;
    -webkit-text-fill-color: #0a2447 !important;
    background-color: #ffffff !important;
    caret-color: #0a2447 !important;
    opacity: 1 !important;
}
div[data-testid="stTextInput"] input::placeholder {
    color: #7b8798 !important;
    -webkit-text-fill-color: #7b8798 !important;
    opacity: 1 !important;
}

/* Selectbox: caixa, valor selecionado, setas e textos internos */
div[data-testid="stSelectbox"] [data-baseweb="select"],
div[data-testid="stSelectbox"] [data-baseweb="select"] > div,
div[data-testid="stSelectbox"] [role="combobox"],
div[data-testid="stSelectbox"] [role="button"] {
    background: #ffffff !important;
    color: #0a2447 !important;
    -webkit-text-fill-color: #0a2447 !important;
    opacity: 1 !important;
}

div[data-testid="stSelectbox"] [data-baseweb="select"] *,
div[data-testid="stSelectbox"] [role="combobox"] *,
div[data-testid="stSelectbox"] [role="button"] * {
    color: #0a2447 !important;
    -webkit-text-fill-color: #0a2447 !important;
    opacity: 1 !important;
}

/* Valor selecionado de BaseWeb / Streamlit */
div[data-testid="stSelectbox"] div[class*="singleValue"],
div[data-testid="stSelectbox"] div[class*="valueContainer"],
div[data-testid="stSelectbox"] div[class*="placeholder"],
div[data-testid="stSelectbox"] span {
    color: #0a2447 !important;
    -webkit-text-fill-color: #0a2447 !important;
    opacity: 1 !important;
}

/* Dropdown aberto */
ul[role="listbox"],
div[role="listbox"],
li[role="option"],
div[role="option"] {
    background: #ffffff !important;
    color: #0a2447 !important;
    -webkit-text-fill-color: #0a2447 !important;
}
li[role="option"] *,
div[role="option"] * {
    color: #0a2447 !important;
    -webkit-text-fill-color: #0a2447 !important;
}

/* Checkbox */
div[data-testid="stCheckbox"] span,
div[data-testid="stCheckbox"] p {
    color: #0a2447 !important;
    -webkit-text-fill-color: #0a2447 !important;
    opacity: 1 !important;
}

/* Oculta o máximo de elementos próprios do Streamlit dentro do app */
#MainMenu,
header,
footer,
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
[data-testid="stHeader"],
[data-testid="stMainMenu"] {
    display: none !important;
    visibility: hidden !important;
}

/* Mobile */
@media (max-width: 700px) {
    div[data-testid="stTextInput"] input,
    div[data-testid="stSelectbox"] [data-baseweb="select"] > div,
    div[data-testid="stSelectbox"] [role="combobox"] {
        min-height: 50px !important;
        font-size: 16px !important;
    }

    div[data-testid="stSelectbox"] [data-baseweb="select"] *,
    div[data-testid="stSelectbox"] [role="combobox"] *,
    div[data-testid="stTextInput"] input {
        font-size: 16px !important;
        line-height: 1.3 !important;
    }
}


/* ===== MOBILE V3: CONTRASTE + CARRINHO FLUTUANTE ===== */
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
[data-testid="stMainBlockContainer"] {
    color:#0a2447 !important;
}

div[data-testid="stMarkdownContainer"] h1,
div[data-testid="stMarkdownContainer"] h2,
div[data-testid="stMarkdownContainer"] h3,
div[data-testid="stMarkdownContainer"] h4,
div[data-testid="stMarkdownContainer"] p,
div[data-testid="stMarkdownContainer"] li,
div[data-testid="stMetric"] *,
label, .stCaption {
    color:#0a2447 !important;
    -webkit-text-fill-color:#0a2447 !important;
    opacity:1 !important;
}

/* Inputs: texto sempre escuro e fundo branco, inclusive iPhone/iOS */
div[data-testid="stNumberInput"] input,
div[data-testid="stTextInput"] input,
div[data-testid="stTextArea"] textarea {
    background:#ffffff !important;
    color:#0a2447 !important;
    -webkit-text-fill-color:#0a2447 !important;
    caret-color:#0a2447 !important;
    opacity:1 !important;
}

div[data-testid="stNumberInput"] [data-baseweb="input"],
div[data-testid="stTextInput"] [data-baseweb="input"],
div[data-testid="stTextArea"] [data-baseweb="textarea"] {
    background:#ffffff !important;
    color:#0a2447 !important;
}

/* Controles + e - dos campos numéricos */
div[data-testid="stNumberInput"] button {
    background:#eef4fb !important;
    color:#0a2447 !important;
    border-color:#cbd8e8 !important;
}
div[data-testid="stNumberInput"] button * {
    color:#0a2447 !important;
    fill:#0a2447 !important;
}

/* Alertas legíveis */
div[data-testid="stAlert"] {
    color:#0a2447 !important;
}
div[data-testid="stAlert"] * {
    opacity:1 !important;
}

/* Carrinho flutuante */
.st-key-floating_cart {
    position:fixed !important;
    right:22px !important;
    bottom:22px !important;
    width:min(390px, calc(100vw - 32px)) !important;
    z-index:999999 !important;
    background:rgba(255,255,255,.97) !important;
    border:1px solid #cbd8e8 !important;
    border-radius:18px !important;
    padding:10px !important;
    box-shadow:0 12px 35px rgba(5,34,73,.25) !important;
    backdrop-filter:blur(8px);
}
.st-key-floating_cart button {
    width:100% !important;
    min-height:52px !important;
    background:linear-gradient(100deg,#062b59,#0b5fc1) !important;
    border:0 !important;
    border-radius:13px !important;
    color:#ffffff !important;
    font-weight:900 !important;
    font-size:16px !important;
}
.st-key-floating_cart button * {
    color:#ffffff !important;
    -webkit-text-fill-color:#ffffff !important;
}

/* Dialog/carrinho */
div[role="dialog"] {
    background:#f5f8fc !important;
}
div[role="dialog"] h1,
div[role="dialog"] h2,
div[role="dialog"] h3,
div[role="dialog"] p,
div[role="dialog"] label {
    color:#0a2447 !important;
    -webkit-text-fill-color:#0a2447 !important;
}
div[role="dialog"] input,
div[role="dialog"] textarea {
    background:#ffffff !important;
    color:#0a2447 !important;
    -webkit-text-fill-color:#0a2447 !important;
}


/* ===== V4: MODAL DO CARRINHO CLARO E LEGÍVEL ===== */
/* Fundo do modal */
div[role="dialog"],
div[data-baseweb="modal"] > div,
div[data-baseweb="modal"] [data-testid="stDialog"] {
    background:#ffffff !important;
    color:#172033 !important;
}

/* Títulos e textos principais */
div[role="dialog"] h1,
div[role="dialog"] h2,
div[role="dialog"] h3,
div[role="dialog"] h4,
div[role="dialog"] p,
div[role="dialog"] label,
div[role="dialog"] span,
div[role="dialog"] small,
div[role="dialog"] .stCaption,
div[role="dialog"] [data-testid="stMarkdownContainer"] * {
    color:#172033 !important;
    -webkit-text-fill-color:#172033 !important;
    opacity:1 !important;
}

/* Separadores suaves */
div[role="dialog"] hr {
    border-color:#dbe4ef !important;
}

/* Campos */
div[role="dialog"] input,
div[role="dialog"] textarea,
div[role="dialog"] [data-baseweb="input"],
div[role="dialog"] [data-baseweb="textarea"] {
    background:#ffffff !important;
    color:#172033 !important;
    -webkit-text-fill-color:#172033 !important;
    border-color:#c8d4e3 !important;
}

/* +/- dos campos numéricos */
div[role="dialog"] div[data-testid="stNumberInput"] button {
    background:#eef4fb !important;
    color:#12345b !important;
    border-color:#c8d4e3 !important;
}
div[role="dialog"] div[data-testid="stNumberInput"] button *,
div[role="dialog"] div[data-testid="stNumberInput"] button svg {
    color:#12345b !important;
    fill:#12345b !important;
    -webkit-text-fill-color:#12345b !important;
}

/* Botões normais: claros, mantendo texto legível */
div[role="dialog"] .stButton > button:not([kind="primary"]) {
    background:#f7f9fc !important;
    color:#12345b !important;
    border:1px solid #c8d4e3 !important;
}
div[role="dialog"] .stButton > button:not([kind="primary"]) * {
    color:#12345b !important;
    -webkit-text-fill-color:#12345b !important;
}

/* Botão principal continua destacado */
div[role="dialog"] .stButton > button[kind="primary"] {
    background:#0b4f9c !important;
    color:#ffffff !important;
    border:0 !important;
}
div[role="dialog"] .stButton > button[kind="primary"] * {
    color:#ffffff !important;
    -webkit-text-fill-color:#ffffff !important;
}

/* Alertas e caixas internas em tons suaves */
div[role="dialog"] div[data-testid="stAlert"] {
    background:#eef6ff !important;
    color:#172033 !important;
    border-color:#cfe0f3 !important;
}
div[role="dialog"] div[data-testid="stAlert"] * {
    color:#172033 !important;
    -webkit-text-fill-color:#172033 !important;
}

/* Mobile: modal mais leve visualmente */
@media (max-width:700px){
    div[role="dialog"] {
        background:#ffffff !important;
        border:1px solid #dbe4ef !important;
        box-shadow:0 12px 34px rgba(18,52,91,.18) !important;
    }
}

@media (max-width:700px){
    .block-container{
        padding-left:.65rem !important;
        padding-right:.65rem !important;
        padding-bottom:7.5rem !important;
    }
    /*
       iPhone/PWA: position:fixed pode desaparecer por causa do viewport
       do Safari/WebApp. No mobile usamos sticky no topo, que acompanha
       a rolagem de forma muito mais estável.
    */
    .st-key-floating_cart{
        position:-webkit-sticky !important;
        position:sticky !important;
        top:calc(8px + env(safe-area-inset-top)) !important;
        left:auto !important;
        right:auto !important;
        bottom:auto !important;
        width:100% !important;
        margin:8px 0 12px !important;
        border-radius:16px !important;
        z-index:999999 !important;
    }
    .st-key-floating_cart button{
        min-height:58px !important;
        font-size:15px !important;
        box-shadow:0 8px 24px rgba(5,34,73,.22) !important;
    }
    div[data-testid="stNumberInput"] input,
    div[data-testid="stTextInput"] input,
    div[data-testid="stTextArea"] textarea{
        font-size:16px !important;
        min-height:48px !important;
    }
}


.quote-search-card{
    background:linear-gradient(100deg,#ffffff,#f3f8ff);
    border:1px solid #d7e4f3;
    border-radius:16px;
    padding:13px 16px;
    display:flex;
    align-items:center;
    gap:12px;
    box-shadow:0 4px 14px rgba(10,36,71,.06);
    margin:4px 0 8px;
}
.quote-search-icon{
    width:42px;height:42px;border-radius:12px;
    display:flex;align-items:center;justify-content:center;
    background:#eaf3ff;font-size:22px;
}
.quote-search-title{
    color:#082b59;
    font-size:18px;
    font-weight:900;
    line-height:1.1;
}
.quote-search-sub{
    color:#64748b;
    font-size:12px;
    margin-top:4px;
}
@media(max-width:700px){
    .quote-search-card{padding:11px 12px;border-radius:14px}
    .quote-search-icon{width:38px;height:38px;font-size:20px}
    .quote-search-title{font-size:16px}
    .quote-search-sub{font-size:11px}
}


/* ===== V5 - CARRINHO CINZA + FONTE PRETA ===== */
/* Regra final e mais específica para sobrescrever o tema escuro anterior. */
div[role="dialog"],
div[data-baseweb="modal"],
div[data-baseweb="modal"] > div,
div[data-baseweb="modal"] [data-testid="stDialog"],
section[data-testid="stDialog"] {
    background-color:#e5e7eb !important;
    color:#000000 !important;
}

/* Todo texto do carrinho/modal em preto */
div[role="dialog"] *,
div[data-baseweb="modal"] *,
section[data-testid="stDialog"] * {
    color:#000000 !important;
    -webkit-text-fill-color:#000000 !important;
    opacity:1 !important;
}

/* Área interna e blocos */
div[role="dialog"] [data-testid="stVerticalBlock"],
div[role="dialog"] [data-testid="stForm"],
div[role="dialog"] [data-testid="stElementContainer"],
section[data-testid="stDialog"] [data-testid="stVerticalBlock"] {
    background-color:transparent !important;
}

/* Inputs brancos para destacar no fundo cinza */
div[role="dialog"] input,
div[role="dialog"] textarea,
div[role="dialog"] [data-baseweb="input"],
div[role="dialog"] [data-baseweb="textarea"],
section[data-testid="stDialog"] input,
section[data-testid="stDialog"] textarea {
    background:#ffffff !important;
    color:#000000 !important;
    -webkit-text-fill-color:#000000 !important;
    border-color:#9ca3af !important;
}

/* Botões +/- claros e texto preto */
div[role="dialog"] div[data-testid="stNumberInput"] button,
section[data-testid="stDialog"] div[data-testid="stNumberInput"] button {
    background:#d1d5db !important;
    color:#000000 !important;
    border-color:#9ca3af !important;
}
div[role="dialog"] div[data-testid="stNumberInput"] button *,
div[role="dialog"] div[data-testid="stNumberInput"] button svg,
section[data-testid="stDialog"] div[data-testid="stNumberInput"] button *,
section[data-testid="stDialog"] div[data-testid="stNumberInput"] button svg {
    color:#000000 !important;
    fill:#000000 !important;
    -webkit-text-fill-color:#000000 !important;
}

/* Botões comuns */
div[role="dialog"] .stButton > button,
section[data-testid="stDialog"] .stButton > button {
    background:#f3f4f6 !important;
    color:#000000 !important;
    border:1px solid #9ca3af !important;
}
div[role="dialog"] .stButton > button *,
section[data-testid="stDialog"] .stButton > button * {
    color:#000000 !important;
    -webkit-text-fill-color:#000000 !important;
}

/* Separadores */
div[role="dialog"] hr,
section[data-testid="stDialog"] hr {
    border-color:#9ca3af !important;
}

/* MOBILE: força especificamente o painel visível do carrinho */
@media (max-width:700px){
    div[role="dialog"],
    div[data-baseweb="modal"] > div,
    section[data-testid="stDialog"] {
        background:#e5e7eb !important;
        color:#000000 !important;
        border:1px solid #9ca3af !important;
        box-shadow:0 10px 30px rgba(0,0,0,.20) !important;
    }
}

</style>
""", unsafe_allow_html=True)

df = load_stock()



st.markdown('<div class="public-badge">🌐 ACESSO PÚBLICO — NÃO É NECESSÁRIO LOGIN</div>', unsafe_allow_html=True)

logo64 = """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DRs2KKNGjVKysrIUm82mvPPOO0pkZKQSGhqqJCYmKmlpaUrPnj2V9evXKw888IAyceJEJSMjQ5k3b54SFxenDBs2TFm7dq0ycuRI5c0331Rqa2uViRMnKsnJyUpxcbEiy7JSV1enTJs2TenevbuSkJCgLFy4UJk9e7ZyxRVXKMePH1eysrKU5ORkZebMmYqiKEplZaXSr18/JT4+Xhk6dKiSlpamfPrpp8qQIUOULVu2KLfffrvy17/+VVm1apUSFxenxMfHK0OGDFG+/PJLZfjw4crx48eVq6++Wlm0aJGyefNmJSkpSenWrZsydepUpba2VmloaFDmzZunxMfHK3FxccrChQsVs9msHD16VBk0aJASHx+vjBs3TsnIyFCOHz+uDB06VImLi1Pmz5+v1NXVKWPGjFF69Oih9OnTR1mzZo1isViUXbt2KQMHDlQefvhhpaqqSvnggw+Unj17KnFxccqf/vQnpaGhQZFlWTGZTMo111yjDB8+XCksLFQKCgqUa665RomLi1P69++vfPvtt8o999yjxMfHKz179lTeffddpaioSOnXr5/y6aefKu+9957St29fJSEhQXn00UeV9evXe+7VihUrlJKSEuWKK65QVq9erdhsNkVRFM8zcPfddyuVlZXKF198ofTu3VuJi4tTFi1apFgsllZP138fv1kPhSavd/PkvFGjRjFmzBiKi4u57rrryMvLQ6VStZhzo9fr6dGjB9988w3XX389LpeLkydPMm/ePF5++WVGjhxJeXk5+/bto7KykgkTJrBy5UqMRiO5ubksWLAAk8nEsGHDiI2NZcaMGe2O6jSjKAqZmZkUFBQwfvx4brzxRkaMGEF1dTXPPPMMmzdv5qqrruLFF19ElmUef/xxbrvtNtatW0dNTQ3z589n8eLF5OfnU1ZW5slElpaWhizLLFmyhOXLl1NaWkpWVhavvvoqGRkZ6PV61qxZw+HDh7n33ntZvHgxktSYlCo8PJwDBw6wb98+cnNzPZnqTSYTBw8eJCoqiuuvv54FCxZQVFREVlYWa9eu5YUXXiA7O9sTjl9fX09hYSEjR44kJyeHZ599lo8//pjMzExPqonmZTxcLhcLFizg5ptv5uuvv6awsBBBEMjIyMBut3PXXXdhNpu56aabmDx5MlqtFrfbzYEDB9BoNCxYsIBbbrkFtVpNamoqJSUljBs3juzsbNatW8df/vIXFEVh3LhxrF+/nqysLNLT0xkzZgxqtZqXX36ZkpIS3njjDTIzM/n222+prKzkjTfeIDw8nPnz5zNmzBhPvNKmTZvYs2cPWVlZFBcX89FHH3Hs2DGWLl3K9OnTiY2NZe/evfj4+BAYGMhzzz1HWlqaZ1rFyy+/TPfu3bn33nsZP348jzzyCF26dKF///6sXLmSo0ePkpWV5ZliYLPZ+Oijj8jKyiIzM5OioiJeeOEFoqOjmTt3LikpKRd81v4b+E0FhSah8PPz46abbqJnz56MHz+evLw8brnlFjIzM1sMJzeP2sTGxvLSSy/x1FNPodfrKS4u5q233mLx4sUUFhYydOhQ5s2bxz/+8Q8CAwM5c+YM119/PWfPniUlJYWEhATuvPNOdDrdBbufiqKwZ88eZFnmp59+oqKigpCQEK699lry8/MZOXIkV155JVlZWYwcOZLZs2eTkpJCeno6DofDk2KytLQUPz8/fH19cTgcVFZW0tDQwLZt25AkiZ9++gm1Ws3hw4fJzs4mISGBPXv20K1bN+bMmcOf/vQnMjIyUKlUxMXF8f7779O5c2ePv0lpWtrD4XB4koKHhYV5lhX99ttv2bx5MxqNhpkzZ3qGzV0uFwaDAUVR0Gq1ZGdno9fr+fzzzykvLycyMpJt27ZRV1fHpk2bPKLftWtXysvLEQSBKVOmkJycTENDA+vXrycsLAxRFKmsrMRkMlFdXc2OHTs8M7wrKipwuVwUFRUhyzI+Pj7k5OQwduxYhgwZgtvtprq6GqvVysyZM4mOjsZoNHLgwAHS0tK46aabcLsbs8537dqVU6dOsWPHDk8KjIaGBl5//XXGjRuHTqcjLy+PLVu2IIoiP/74I6mpqeTl5VFaWoosy1RVVWE0GtmyZYtnBNBqtbJ8+XIWLlxIUFAQ9fX1zJ49m969eyNJErW1tahUKqKiohBFkaNHj7J//35GjhyJ1WpFaFpj6siRI+zevZuQkJBflKPm/3d+c0FpJjQ0lNtvv53AwEBGjRrFqVOnWL58OUePHm0zQU5sygWybNkyPvjgA7p27YrZbObHH3/kySefpLa2lrFjx+Lv78/Jkye54YYbyMrKIiUlhe7du3P//ffj4/PLEvW6m1JGhoSEMHPmTEaOHElxcTFr1qxBrVZTV1eHxWLB6XTSuXNnysvLsVgs1NTUkJKSwtSpU+nVqxeHDh1CkiQsFgsVFRUUFBQwaNAgpk2bRt++fdm0aRPx8fEYjUby8/Px9fUlOzsbtVqNyWSitraWtLQ0JEkiKyuLLVu2YLfbcTgcHDlyBEVRPNMPFixYwOTJkzGbzVitViZPnkxxcTEDBgxArVYzduxYAL777jtPI7v66qu57bbb0Gg03HnnnZw+fRqApKQkqpqWYZ06dSoajQaz2UzPnj356aefcLvd9OjRg7Fjx7J8+XKqqqp48803sdls5OTkYLFYWLRoEVOmTMHf3x+n00l+fj5arZbdu3czduxYkpKScDgc+Pn5kZOTQ3BwMIIgIMsyLpeL7OxsunfvzjfffENNTQ179+7FarVSWVnJzJkzWbp0KSdPnuTVV19FURTPTPSTJ09iNps5fPgw5eXlhIaGEhERQWpqKgUFBZhMJmw2GzU1Nbz++utkZmYSGhrqmZQpSRKlpaUcOXIEp9OJwWDg2LFjdOvWjTNnzmAwGKivr6eiooK///3vVFZWkpubS0lJCXV1dSxcuJAlS5aQl5fHunXr2sRa/TfyuwmKIAhERUXxyCOP4OPjw4ABA0hPT+f2229vd+U8X19frr76alatWsWECRNITEzkwQcfZMiQIdhsNvbt28dNN91Eeno6o0aNIioqivvvv79F+gJvKIqC2+3GYrHgcrlYt24d3377La+99hqSJLF8+XJycnKora0lKCiI9957j7lz55KdnY3FYiErK4t169axc+dOTp06RVFREYsXL/b0dPLy8li7di1btmyhvr6eKVOmkJSURGBgIMnJyfTr14/09HQWLVrEP/7xD2w2G4mJiWzevJnIyEgmTJiA0Whk+/btKIpCdnY2kiSxfv16vv76a0wmE76+vtxyyy387W9/Y8yYMfj6+uLv74+iKFRWVjJixAi++uorXn/9ddxuN1qtlgEDBtC9e3fPTGZJksjNzWXdunXYbDYiIiLYsmULK1euZODAgZjNZt555x3WrFkDwKRJk1CpVNTX16PRaNiwYQPr1q2juroau91Oeno6gwcPJjExkbNnzxISEkJISAjvvfceq1evZvbs2Z6e0l/+8hfcbjdRUVEcPnyYsWPHEh8fjyiKrF27lueff55vvvkGHx8fJk6ciNPp5LHHHiMuLo5BgwYRFBREZWUlsbGxnD17lq1btxIfH09dXR1arZa7774bjUZDQEAAdXV1jB07ln79+qHX67njjjtYunQpkZGRGI1GHnnkEY4dO8asWbM4duwYdrudRYsW8cwzz3hScCQkJOB0OklNTeXFF1/km2++Qa1W079//1/0zP3/zm82bNwe7qY8KI899hhlZWWkpaUREBDAk08+2WZZjXO/07zAd0BAABaLhY0bN/Loo49SX1/PlVdeSUhICE8++eQFR3TORWmK1v366689meQjIyOprKwkISGB6OhofvrpJxITE3E4HGzbto3AwEAmTZrEpk2bcLvdiKLIoEGDOHLkCA6HA61WS1JSEseOHcPhcKDRaBg6dCipqamMGjWKuro6jh49yjXXXENVVZXnzZaSkkJxcTEBAQEUFRURFhbGsGHDWLduHWq1munTp7Njxw5ycnI8o2M9evTg5MmTTJkyBYPBQEZGBunp6cycORONRsOaNWuIj48nKSkJtVrtWUA+JSWFY8eOYTabSUpK8kQpi6LInDlzMJlMfP311xiNRo8fat++faSlpZGYmMjo0aPx8/Pj9OnTbNu2DZoSP82dOxdJkvj222+JiopCr9d7TJ28vDy2bdtGXFwc48aN49SpUxw/fhyhad1ls9lMTk4OEyZMwO12s23bNpKSkjh16hS5ubkkJiYybtw4VCoVa9asITk5mZiYGHbv3o1WqyUmJoaNGzei0WgYN24cNTU1ZGVlMW7cOL777juGDx/OkSNHSE5OpnPnzvz444+cOHGChIQEhgwZ4un1DBw4kMGDB7Nz506Ki4tRFIWwsDCqq6uZPHkyLpeLPXv20KdPH9LT08nLyyMpKYmUlBT8/f1bPWH/ffzugkJTjEZZWRl/+9vfyM/P56effgJg4cKF3HXXXR4bvTV2u52SkhLefvtt3nvvPbRaLZMmTUKtVvPCCy90/KAddPAH84cICk29g+rqatasWcP69evJy8ujqKiILl268Pbbb5OUlITBYEAURVwuFyaTiVOnTrFs2TLy8vKIjY3liiuuoG/fvp7csh100MEfyx8mKM1YLBaOHj3KI488Qo8ePfjXv/6FTqdj3LhxPP7444SGhlJaWsqKFSvYtWsXclMS6traWh5++GEGDRrU4V3voIP/EP5wQaHJR1JSUsJHH33E9u3bAdi9ezf+/v6EhYVRVFSE3W5nxIgRaDQahg8fzk033XTeNIQddNDBH8d/hKA0Y7fbOXLkCO+++y6lpaVYrVaOHDnCwIEDMRgMREZGctNNN9G/f/82uUc76KCDP57/KEFpxul0snv3blavXk1VVRURERHMmzePIUOGdEQjdtDBfzD/kYLSQQcd/N+k7dhsBx100MEl0iEoHXTQwWWjQ1A66KCDy0aHoHTQQQeXjQ5B6aCDDi4bHYLSQQcdXDb+HxWVvV69gJc0AAAAAElFTkSuQmCC"""
agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
st.markdown(f"""
<div class="hero">
  <div class="hero-left">
    <img class="logo" src="data:image/png;base64,{logo64}">
    <h1>CONSULTA DE ESTOQUE</h1>
    <p>Consulte pneus disponíveis, quantidade e valor unitário.</p>
  </div>
  <div class="update">↻ Última atualização: {agora}</div>
</div>
""", unsafe_allow_html=True)

# ===== CONSULTA RÁPIDA DE ORÇAMENTOS =====
st.markdown("""
<div class="quote-search-card">
  <div class="quote-search-icon">📋</div>
  <div>
    <div class="quote-search-title">Consultar orçamento</div>
    <div class="quote-search-sub">Veja rapidamente se a proposta está aprovada, pendente ou recusada.</div>
  </div>
</div>
""", unsafe_allow_html=True)

with st.expander("🔎 Abrir consulta de orçamentos", expanded=False):
    tipo_busca = st.radio(
        "Buscar por",
        ["Vendedor", "Número do orçamento"],
        horizontal=True,
        key="tipo_busca_orcamento_topo",
    )

    if tipo_busca == "Vendedor":
        termo_orc = st.text_input(
            "Nome do vendedor",
            placeholder="Ex.: clecio",
            key="consulta_vendedor_topo",
        ).strip()

        if termo_orc:
            meus = pd.read_sql_query(text("""
                SELECT numero, criado_em, cliente_nome, desconto_percentual, total, status,
                       aprovado_por, aprovado_em, motivo_aprovacao, vendedor
                FROM orcamentos
                WHERE LOWER(TRIM(vendedor)) = LOWER(TRIM(:termo))
                ORDER BY numero DESC
                LIMIT 100
            """), engine, params={"termo": termo_orc})
        else:
            meus = pd.DataFrame()

    else:
        termo_num = st.text_input(
            "Número do orçamento",
            placeholder="Ex.: 7803",
            key="consulta_numero_topo",
        ).strip()

        if termo_num.isdigit():
            meus = pd.read_sql_query(text("""
                SELECT numero, criado_em, cliente_nome, desconto_percentual, total, status,
                       aprovado_por, aprovado_em, motivo_aprovacao, vendedor
                FROM orcamentos
                WHERE numero = :numero
                ORDER BY numero DESC
            """), engine, params={"numero": int(termo_num)})
        elif termo_num:
            st.warning("Digite apenas o número do orçamento.")
            meus = pd.DataFrame()
        else:
            meus = pd.DataFrame()

    if not meus.empty:
        for o in meus.itertuples():
            status = str(o.status or "").upper()
            if status == "APROVADO":
                icone = "🟢"
                status_label = "APROVADO"
            elif status == "RECUSADO":
                icone = "🔴"
                status_label = "RECUSADO"
            else:
                icone = "🟠"
                status_label = "AGUARDANDO APROVAÇÃO"

            with st.expander(
                f"{icone} Nº {int(o.numero)} • {o.cliente_nome} • {brl(o.total)} • {status_label}"
            ):
                c1, c2, c3 = st.columns(3)
                c1.metric("Vendedor", str(o.vendedor))
                c2.metric("Total", brl(o.total))
                c3.metric("Status", status_label)

                if status == "RECUSADO" and o.motivo_aprovacao:
                    st.error(f"Motivo da recusa: {o.motivo_aprovacao}")

                if status == "APROVADO":
                    cab, itens_pdf = carregar_orcamento(int(o.numero))
                    if cab:
                        st.success(
                            f"✅ Aprovado"
                            + (f" por {cab.get('aprovado_por')}" if cab.get("aprovado_por") else "")
                        )
                        pdf = gerar_pdf_orcamento(cab, itens_pdf, logo64)
                        st.download_button(
                            "📄 Baixar PDF",
                            data=pdf,
                            file_name=f"orcamento_pneuaco_{int(o.numero)}.pdf",
                            mime="application/pdf",
                            key=f"pdf_top_{int(o.numero)}",
                            use_container_width=True,
                        )
                else:
                    st.info("O PDF definitivo será liberado quando o orçamento for aprovado.")

    elif (
        (tipo_busca == "Vendedor" and termo_orc)
        or (tipo_busca == "Número do orçamento" and 'termo_num' in locals() and termo_num)
    ):
        st.info("Nenhum orçamento encontrado.")


total = int(df["quantidade"].sum()) if not df.empty else 0
nota = int(df.loc[df["origem"]=="PNEUS COM NOTA","quantidade"].sum()) if not df.empty else 0
sem_nota = int(df.loc[df["origem"]=="PNEUS SEM NOTA","quantidade"].sum()) if not df.empty else 0
diesel = int(df.loc[df["origem"]=="DIESEL PNEUS","quantidade"].sum()) if not df.empty else 0
modelos = len(df)

st.markdown(f"""
<div class="metric-grid" style="grid-template-columns:repeat(5,minmax(0,1fr))">
  <div class="metric"><div class="label blue">TOTAL DE PNEUS</div><div class="value">{total:,}</div><div class="sub">unidades</div></div>
  <div class="metric"><div class="label green">PNEUS COM NOTA</div><div class="value">{nota:,}</div><div class="sub">unidades</div></div>
  <div class="metric"><div class="label" style="color:#9a5b00">PNEUS SEM NOTA</div><div class="value">{sem_nota:,}</div><div class="sub">unidades</div></div>
  <div class="metric"><div class="label orange">DIESEL PNEUS</div><div class="value">{diesel:,}</div><div class="sub">unidades</div></div>
  <div class="metric"><div class="label purple">TOTAL DE MODELOS</div><div class="value">{modelos}</div><div class="sub">modelos</div></div>
</div>
""".replace(",","."), unsafe_allow_html=True)

st.markdown('<div class="section"><div class="section-title">🔎 PESQUISAR ESTOQUE</div>', unsafe_allow_html=True)
busca = st.text_input("Pesquisar por medida, modelo ou descrição", placeholder="Ex.: 600/65R28, PIRELLI, TM95...", label_visibility="collapsed")

c1,c2,c3 = st.columns([1,1,1])
with c1:
    origem = st.selectbox("Origem", ["TODAS","PNEUS COM NOTA","PNEUS SEM NOTA","DIESEL PNEUS"])
base = df if origem=="TODAS" else df[df["origem"]==origem]
with c2:
    marca = st.selectbox("Marca", ["TODAS"] + sorted(base["marca"].dropna().unique().tolist()))
with c3:
    mostrar_zero = st.checkbox("Mostrar itens sem estoque", value=False)
st.markdown("</div>", unsafe_allow_html=True)

f = base.copy()
if marca != "TODAS":
    f = f[f["marca"]==marca]
if busca.strip():
    t = busca.strip()
    f = f[f["descricao"].str.contains(t, case=False, na=False) | f["marca"].str.contains(t, case=False, na=False)]
if not mostrar_zero:
    f = f[f["quantidade"] > 0]
f = f.sort_values(["marca","descricao"])

st.markdown(f'<div class="results-head"><div>🛞 <b>{len(f)}</b> modelos encontrados</div><div>{"Somente itens disponíveis" if not mostrar_zero else "Incluindo itens sem estoque"}</div></div>', unsafe_allow_html=True)


carrinho = st.session_state.orcamento_carrinho

def _conteudo_carrinho():
    carrinho = st.session_state.orcamento_carrinho
    st.markdown(f"### 🛒 Orçamento atual — {len(carrinho)} modelo(s)")

    if not carrinho:
        st.info("Seu carrinho está vazio. Feche esta janela e adicione pneus ao orçamento.")
        return

    remover = []
    for k, item in list(carrinho.items()):
        st.markdown(
            f"**{item['descricao']}**  \n"
            f"Marca: {item['marca']} • Estoque disponível: {int(item['estoque'])}"
        )
        q1, q2, q3 = st.columns([1.15, 1.55, .55])
        with q1:
            item["quantidade"] = st.number_input(
                "Quantidade",
                min_value=1,
                max_value=max(1, int(item["estoque"])),
                value=int(item["quantidade"]),
                step=1,
                key=f"qdlg_{k}",
            )
        with q2:
            item["valor_unitario"] = st.number_input(
                "Valor unitário",
                min_value=0.0,
                value=float(item["valor_unitario"]),
                step=10.0,
                format="%.2f",
                key=f"vdlg_{k}",
            )
        with q3:
            st.write("")
            st.write("")
            if st.button("🗑️", key=f"rdlg_{k}", help="Remover item"):
                remover.append(k)
        st.caption(f"Total do item: {brl(item['quantidade'] * item['valor_unitario'])}")
        st.divider()

    for k in remover:
        carrinho.pop(k, None)
        st.rerun()

    subtotal = sum(i["quantidade"] * i["valor_unitario"] for i in carrinho.values())
    st.markdown(f"### Subtotal: {brl(subtotal)}")

    with st.form("orcamento_dialog"):
        st.markdown("### 👤 Dados do cliente")

        vendedor = st.text_input("Vendedor *", key="dlg_vendedor")
        cliente = st.text_input("Cliente / Razão Social *", key="dlg_cliente")
        cnpj = st.text_input("CNPJ / CPF", key="dlg_cnpj")
        telefone = st.text_input("Telefone", key="dlg_telefone")
        email = st.text_input("E-mail", key="dlg_email")
        endereco = st.text_input("Endereço", key="dlg_endereco")
        desconto = st.number_input(
            "Desconto (%)",
            min_value=0.0,
            max_value=5.0,
            value=0.0,
            step=0.5,
            format="%.2f",
            key="dlg_desconto",
        )
        obs = st.text_area("Observações", key="dlg_obs")

        total = subtotal * (1 - desconto / 100)
        if desconto <= 3:
            st.success("✅ Até 3%: aprovação automática.")
        else:
            st.warning("🟠 Acima de 3% até 5%: enviado para aprovação.")

        t1, t2 = st.columns(2)
        t1.metric("Subtotal", brl(subtotal))
        t2.metric("Total final", brl(total))

        salvar = st.form_submit_button(
            "💾 Finalizar e salvar orçamento",
            use_container_width=True,
            type="primary",
        )
        if salvar:
            if not vendedor.strip() or not cliente.strip():
                st.error("Informe o vendedor e o cliente.")
            else:
                try:
                    numero, status, total_salvo = salvar_orcamento(
                        vendedor.strip(), cliente.strip(), cnpj.strip(),
                        telefone.strip(), email.strip(), endereco.strip(),
                        obs.strip(), desconto
                    )
                    st.session_state.orcamento_carrinho = {}
                    if status == "APROVADO":
                        st.success(
                            f"✅ Orçamento Nº {numero} salvo e aprovado automaticamente — {brl(total_salvo)}"
                        )
                    else:
                        st.warning(
                            f"🟠 Orçamento Nº {numero} enviado para aprovação — {brl(total_salvo)}"
                        )
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao salvar orçamento: {e}")

# Streamlit moderno: abre o carrinho como janela/modal.
if hasattr(st, "dialog"):
    _abrir_dialog = st.dialog("🛒 Finalizar orçamento", width="large")(_conteudo_carrinho)
else:
    _abrir_dialog = None

if carrinho:
    with st.container(key="floating_cart"):
        qtd_modelos = len(carrinho)
        qtd_unidades = sum(int(i["quantidade"]) for i in carrinho.values())
        subtotal_flutuante = sum(
            i["quantidade"] * i["valor_unitario"] for i in carrinho.values()
        )

        texto_botao = (
            f"🛒 {qtd_modelos} modelo(s) • {qtd_unidades} un. • "
            f"{brl(subtotal_flutuante)}  |  FINALIZAR ORÇAMENTO"
        )

        if st.button(
            texto_botao,
            key="abrir_carrinho_flutuante",
            use_container_width=True,
        ):
            if _abrir_dialog is not None:
                _abrir_dialog()
            else:
                st.session_state["mostrar_carrinho_fallback"] = True

# Fallback para instalações antigas do Streamlit.
if st.session_state.get("mostrar_carrinho_fallback") and _abrir_dialog is None:
    with st.expander("🛒 Finalizar orçamento", expanded=True):
        _conteudo_carrinho()


st.markdown("### 🛞 Selecione os pneus")
st.caption("Toque em **Adicionar ao orçamento**. No celular, o carrinho ficará fixo no topo enquanto você navega pelos pneus.")
rows = list(f.itertuples())
for pos in range(0, len(rows), 2):
    cols = st.columns(2)
    for off,row in enumerate(rows[pos:pos+2]):
        with cols[off]:
            origem_txt=str(row.origem); qtd=int(row.quantidade)
            st.markdown(f"""<div class="product-card"><div><span class="badge {'badge-diesel' if origem_txt=='DIESEL PNEUS' else 'badge-nota'}">{origem_txt}</span><div class="desc">{row.descricao}</div><div class="meta"><b>Marca:</b> {row.marca}<br><b>Origem:</b> {origem_txt}</div></div><div class="stock-box"><div class="qty">✓ {qtd} {'unidade' if qtd==1 else 'unidades'}</div><div class="price">{brl(row.preco_unitario)}</div><div class="price-label">VALOR UNITÁRIO</div></div></div>""",unsafe_allow_html=True)
            if qtd>0 and st.button("🛒 Adicionar ao orçamento",key=f"add_{int(row.produto_id)}",use_container_width=True):
                k=str(int(row.produto_id))
                if k in st.session_state.orcamento_carrinho:
                    st.session_state.orcamento_carrinho[k]["quantidade"]=min(qtd,st.session_state.orcamento_carrinho[k]["quantidade"]+1)
                else:
                    st.session_state.orcamento_carrinho[k]={"produto_id":int(row.produto_id),"descricao":str(row.descricao),"marca":str(row.marca),"quantidade":1,"estoque":qtd,"valor_unitario":float(row.preco_unitario or 0)}
                st.rerun()


st.markdown(f'<div class="footer-note">ⓘ Estoque atualizado automaticamente a cada 60 segundos. Última consulta: <b>{agora}</b>.</div>', unsafe_allow_html=True)


