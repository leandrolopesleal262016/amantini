# 🚀 GUIA COMPLETO: Flask-Migrate para PythonAnywhere

# ===== NO SEU AMBIENTE LOCAL =====

# 1. Backup do banco atual (IMPORTANTE!)
cp apps/db.sqlite3 apps/db.sqlite3.backup

# 2. Inicializar Flask-Migrate
flask db init

# 3. Criar migration inicial (captura estado atual do banco)
flask db migrate -m "Initial migration"

# 4. Aplicar migration (não deve mudar nada, mas confirma que funciona)
flask db upgrade

# 5. Atualizar o modelo ItemPedido em apps/home/models.py
# Adicionar: observacao = db.Column(db.String(500), nullable=True)

# 6. Criar migration para o novo campo
flask db migrate -m "Adicionar campo observacao na tabela itens_pedido"

# 7. Aplicar a nova migration
flask db upgrade

# 8. Testar se tudo funciona localmente

# 9. Commit e push para o repositório
git add .
git commit -m "Adicionar campo observacao e configurar migrations"
git push origin main

# ===== NO PYTHONANYWHERE =====

# 1. Fazer pull das mudanças
git pull origin main

# 2. Ativar ambiente virtual
source /home/seuusuario/venv/bin/activate

# 3. Aplicar migrations no servidor
flask db upgrade

# 4. Reiniciar aplicação web no dashboard do PythonAnywhere

# ===== COMANDOS ÚTEIS PARA O FUTURO =====

# Ver histórico de migrations
flask db history

# Ver migration atual
flask db current

# Reverter para migration anterior (se necessário)
flask db downgrade

# Criar nova migration (sempre que alterar modelos)
flask db migrate -m "Descrição da mudança"
flask db upgrade