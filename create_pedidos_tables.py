# Crie um arquivo: migrations/create_pedidos_tables.py
# ou execute diretamente no shell Flask

from apps import db

def create_pedidos_tables():
    """Cria as tabelas para pedidos de compra"""
    
    # SQL para criar a tabela de pedidos
    sql_pedidos = '''
    CREATE TABLE IF NOT EXISTS pedidos_compra (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        obra VARCHAR(100) NOT NULL DEFAULT 'FAGA',
        responsavel VARCHAR(100) NOT NULL,
        prioridade VARCHAR(20) NOT NULL,
        data_necessidade DATE NOT NULL,
        status VARCHAR(20) DEFAULT 'solicitado',
        observacoes TEXT,
        data_criacao DATETIME DEFAULT CURRENT_TIMESTAMP,
        usuario_id INTEGER NOT NULL,
        FOREIGN KEY (usuario_id) REFERENCES Users (id)
    );
    '''
    
    # SQL para criar a tabela de itens
    sql_itens = '''
    CREATE TABLE IF NOT EXISTS itens_pedido (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pedido_id INTEGER NOT NULL,
        codigo_item VARCHAR(50) NOT NULL,
        nome_item VARCHAR(200) NOT NULL,
        quantidade REAL NOT NULL,
        unidade VARCHAR(10) NOT NULL,
        FOREIGN KEY (pedido_id) REFERENCES pedidos_compra (id) ON DELETE CASCADE
    );
    '''
    
    try:
        # Executar os comandos SQL
        db.engine.execute(sql_pedidos)
        db.engine.execute(sql_itens)
        
        print("✅ Tabelas criadas com sucesso!")
        print("- pedidos_compra")
        print("- itens_pedido")
        
    except Exception as e:
        print(f"❌ Erro ao criar tabelas: {e}")

# Para executar no shell Flask:
# flask shell
# >>> from migrations.create_pedidos_tables import create_pedidos_tables
# >>> create_pedidos_tables()

# Ou usando Flask-Migrate (recomendado):
# flask db init
# flask db migrate -m "Add pedidos_compra tables"
# flask db upgrade