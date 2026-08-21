# Estoque de Pneus Online

Esta versão está preparada para funcionar online com PostgreSQL/Supabase.

## O que já faz
- Login de usuários
- Dashboard
- Cadastro de novos pneus
- Entrada de estoque
- Saída/baixa de estoque
- Ajuste de quantidade
- Bloqueio de saída maior que o estoque
- Histórico com usuário, NF, fornecedor/destino/motorista e observação
- Relatórios e exportação para Excel
- Base exclusiva PNEUS COM NOTA
- Continua funcionando localmente com SQLite quando DATABASE_URL não está configurada

## Publicação recomendada
1. Crie um banco PostgreSQL no Supabase.
2. Copie a Connection String do banco.
3. Defina uma variável/secreto chamada `DATABASE_URL`.
4. Rode `migrar_para_postgres.py` uma única vez para carregar o estoque atual.
5. Publique a pasta no Streamlit Community Cloud, Render ou Railway.
6. Configure `DATABASE_URL` também no serviço onde o app será publicado.

## Login inicial
Usuário: admin
Senha: admin123

Troque a senha após publicar.

## Execução local
Dê dois cliques em `INICIAR_APP.bat`.

## Estrutura
- `app.py`: aplicativo
- `estoque.db`: base local atual
- `migrar_para_postgres.py`: envia a base atual para PostgreSQL
- `.streamlit/secrets.toml.example`: exemplo da configuração do banco


## Correção desta versão
Esta versão inclui migração automática do banco antigo.
Se o arquivo `estoque.db` já existia, o sistema cria automaticamente as colunas:
`usuario`, `nf`, `fornecedor_destino`, `estoque_anterior` e `estoque_atual`.
