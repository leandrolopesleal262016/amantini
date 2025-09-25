# GUIA COMPLETO: Flask-Migrate para PythonAnywhere

## ===== NO SEU AMBIENTE LOCAL =====

1. Faca backup do banco MySQL (ex.: `mysqldump -u usuario -p amantini > backup.sql`).
2. Inicialize o Flask-Migrate se ainda nao existir: `flask db init`.
3. Crie a migration inicial que representa o estado atual: `flask db migrate -m "Initial migration"`.
4. Aplique a migration para confirmar: `flask db upgrade`.
5. Faca suas alteracoes de modelo normalmente.
6. Gere novas migrations sempre que mudar os modelos: `flask db migrate -m "Descricao da mudanca"`.
7. Aplique as migrations localmente: `flask db upgrade`.
8. Teste a aplicacao local com o banco MySQL.
9. Faca commit e push das mudancas para o repositorio.

## ===== NO PYTHONANYWHERE =====

1. Faca pull das mudancas: `git pull origin main`.
2. Ative o ambiente virtual: `source /home/seuusuario/venv/bin/activate`.
3. Defina as variaveis `DB_ENGINE`, `DB_USERNAME`, `DB_PASS`, `DB_HOST`, `DB_PORT` e `DB_NAME`.
4. Aplique as migrations no servidor: `flask db upgrade`.
5. Reinicie a aplicacao web pelo painel do PythonAnywhere.

## ===== COMANDOS UTEIS PARA O FUTURO =====

- Ver historico de migrations: `flask db history`
- Ver a migration atual: `flask db current`
- Reverter uma migration: `flask db downgrade`
- Criar nova migration: `flask db migrate -m "Resumo"` e depois `flask db upgrade`
