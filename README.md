# PNEUACOESTOQUE — REPOSITÓRIO LIMPO

Mantenha SOMENTE estes arquivos no GitHub:

- app.py
- vendedores_app.py
- requirements.txt
- atualizar_base_online.py
- README.md

## App administrativo
Main file path: `app.py`
URL sugerida: `pneuacoestoque.streamlit.app`
Exige login.

## App público de vendedores
Main file path: `vendedores_app.py`
URL sugerida: `pneuacoestoque-vendedores.streamlit.app`
NÃO exige login.

## Secrets nos dois apps
Configure o mesmo secret no Streamlit:

DATABASE_URL = "sua conexão do Supabase"

Não coloque a senha no GitHub.

## Importante
Apague do GitHub arquivos antigos como:
- Consulta_Vendedores.py
- Consulta_Vendedores.cpython-*.pyc
- vendedores_app_CORRIGIDO.py
- logo_pneuaco.png
- estoque.db
- migrar_para_postgres.py
- .devcontainer

A logo já está embutida em `vendedores_app.py`.
O estoque online vem do Supabase.
