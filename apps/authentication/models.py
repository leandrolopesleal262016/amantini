# apps/authentication/models.py
# SUBSTITUA ESTE ARQUIVO COMPLETO

from flask_login import UserMixin
from apps import db, login_manager
from apps.authentication.util import hash_pass
from datetime import datetime

class Users(db.Model, UserMixin):
    __tablename__ = 'Users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True)
    email = db.Column(db.String(64), unique=True)
    password = db.Column(db.LargeBinary)

    def __init__(self, **kwargs):
        for property, value in kwargs.items():
            if hasattr(value, '__iter__') and not isinstance(value, str):
                value = value[0]
            if property == 'password':
                value = hash_pass(value)
            setattr(self, property, value)

    def __repr__(self):
        return str(self.username)

    # Relacionamento para tarefas. Permite acessar tasks via user.tasks
    tasks = db.relationship('Task', backref='usuario', lazy=True, cascade='all, delete-orphan')
    # Relacionamento para obras do usuário
    obras = db.relationship('Obra', backref='usuario', lazy=True, cascade='all, delete-orphan')

class Contact(db.Model):
    __tablename__ = 'Contacts'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=False)

    def __repr__(self):
        return f'<Contact {self.name}>'


class Obra(db.Model):
    __tablename__ = 'obras'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    endereco = db.Column(db.String(255), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)

    pedidos = db.relationship('PedidoCompra', backref='obra_rel', lazy=True)

    def __repr__(self):
        return f'<Obra {self.id} - {self.nome}>'
# ⭐ MODELOS DE PEDIDO DE COMPRA - VERSÃO CORRIGIDA

class PedidoCompra(db.Model):
    __tablename__ = 'pedidos_compra'
    
    id = db.Column(db.Integer, primary_key=True)
    obra = db.Column(db.String(150), nullable=False, default='FAGA')
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=True)
    obra_endereco = db.Column(db.String(255), nullable=True)
    responsavel = db.Column(db.String(100), nullable=False)
    prioridade = db.Column(db.String(20), nullable=False)  # baixa, media, alta, urgente
    data_necessidade = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='solicitado')  # solicitado, aprovado, em_compra, entregue
    # Nova coluna para armazenar a posição do cartão dentro de cada coluna do Kanban
    posicao = db.Column(db.Integer, nullable=False, default=0)
    observacoes = db.Column(db.Text)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    usuario_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    
    # ✅ RELACIONAMENTO CORRETO - SEM CONFLITO
    itens = db.relationship('ItemPedido', backref='pedido_compra', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<PedidoCompra {self.id} - {self.obra}>'

class ItemPedido(db.Model):
    __tablename__ = 'itens_pedido'
    
    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey('pedidos_compra.id'), nullable=False)
    codigo_item = db.Column(db.String(50), nullable=False)
    nome_item = db.Column(db.String(200), nullable=False)
    observacao = db.Column(db.String(500), nullable=True)  # ⭐ CAMPO OBSERVAÇÃO
    quantidade = db.Column(db.Float, nullable=False)
    unidade = db.Column(db.String(20), nullable=False)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    
    # ✅ NÃO DEFINIR RELACIONAMENTO AQUI - EVITA CONFLITO
    
    def __repr__(self):
        return f'<ItemPedido {self.nome_item} - {self.quantidade} {self.unidade}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'codigo_item': self.codigo_item,
            'nome_item': self.nome_item,
            'observacao': self.observacao,
            'quantidade': self.quantidade,
            'unidade': self.unidade,
            'data_criacao': self.data_criacao.isoformat() if self.data_criacao else None
        }

# ================================================================
# MODELO DE TAREFA (TASK)
# Define um quadro de tarefas independente do módulo de pedidos de compra.
# Cada tarefa pertence a um usuário e possui um status que corresponde às colunas
# existentes na interface de tarefas: Pendente, Em Progresso, Entregue, Aguardando Nota/Boleto.

class Task(db.Model):
    __tablename__ = 'tasks'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    # Observações adicionais da tarefa
    observations = db.Column(db.Text, nullable=True)
    priority = db.Column(db.String(20), default='Média')
    assignee = db.Column(db.String(100), nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(50), default='Pendente')
    # posição dentro da coluna do Kanban; inicializada em zero
    posicao = db.Column(db.Integer, nullable=False, default=0)
    usuario_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)

    # Data/hora de criação da tarefa. Útil para calcular o tempo de conclusão.
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Task {self.id} - {self.title}>'


# =================================================================
# MODELO DE TAREFA CONCLUÍDA (CompletedTask)
# Armazena tarefas removidas do quadro após conclusão. Mantém as
# informações originais da tarefa, inclusive os horários de criação e
# conclusão, bem como a duração em segundos para cálculo de tempo
# gasto.

class CompletedTask(db.Model):
    __tablename__ = 'completed_tasks'

    id = db.Column(db.Integer, primary_key=True)
    # Identificador da tarefa original, útil para rastrear origem
    original_task_id = db.Column(db.Integer, nullable=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    observations = db.Column(db.Text, nullable=True)
    priority = db.Column(db.String(20), nullable=True)
    assignee = db.Column(db.String(100), nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(50), nullable=True)
    # Data/hora de criação da tarefa original
    data_criacao = db.Column(db.DateTime, nullable=True)
    # Data/hora em que foi concluída
    data_conclusao = db.Column(db.DateTime, nullable=True)
    # Duração em segundos desde a criação até a conclusão
    duration_seconds = db.Column(db.Integer, nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)

    # Caminho do arquivo anexo (nota/boleta) relativo à pasta de upload.  
    # Este campo é opcional porque apenas tarefas no status "Aguardando Nota/Boleto"
    # exigem um anexo. Quando preenchido, o valor é o nome do arquivo salvo na
    # pasta de uploads, permitindo que a aplicação gere links de download.
    attachment_path = db.Column(db.String(255), nullable=True)

    # Caminho do arquivo de nota/ boleto anexado (relativo ao diretório de mídia)
    attachment_path = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f'<CompletedTask {self.id} - {self.title}>'


# ================================================================
# MODELOS DE FORNECEDOR E COMPRA (ORÇAMENTO)
#
# O modelo Fornecedor permite armazenar informações de fornecedores
# (nome, email, telefone) associadas ao usuário atual. O modelo
# Compra (ou Orcamento) armazena orçamentos cadastrados na nova
# página "Compras", vinculando cada compra a um fornecedor, ao
# usuário que a cadastrou e ao arquivo de orçamento anexado.

class Fornecedor(db.Model):
    __tablename__ = 'fornecedores'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=True)
    telefone = db.Column(db.String(20), nullable=True)
    # Campos adicionais para armazenar dados completos do fornecedor
    razao_social = db.Column(db.String(150), nullable=True)
    # Nome fantasia do fornecedor (pode ser diferente da razão social). Se não fornecido, será igual a ``nome``.
    nome_fantasia = db.Column(db.String(150), nullable=True)
    cnpj = db.Column(db.String(32), nullable=True)
    ie = db.Column(db.String(64), nullable=True)
    im = db.Column(db.String(64), nullable=True)
    celular = db.Column(db.String(20), nullable=True)
    cep = db.Column(db.String(12), nullable=True)
    logradouro = db.Column(db.String(150), nullable=True)
    numero = db.Column(db.String(20), nullable=True)
    bairro = db.Column(db.String(100), nullable=True)
    cidade = db.Column(db.String(100), nullable=True)
    estado = db.Column(db.String(2), nullable=True)
    obs = db.Column(db.Text, nullable=True)
    # Cada fornecedor pertence a um usuário (organização)
    usuario_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    # Relacionamento para acessar compras deste fornecedor
    compras = db.relationship('Compra', backref='fornecedor', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Fornecedor {self.id} - {self.nome}>'


class Compra(db.Model):
    __tablename__ = 'compras'
    id = db.Column(db.Integer, primary_key=True)
    # Referência ao fornecedor vinculado a esta compra
    fornecedor_id = db.Column(db.Integer, db.ForeignKey('fornecedores.id'), nullable=False)
    # Valor do orçamento da compra
    valor = db.Column(db.Float, nullable=False)
    # Caminho relativo do arquivo de orçamento anexado (PDF/imagem)
    attachment_path = db.Column(db.String(255), nullable=True)
    # Data informada para o orçamento. Permite registrar a data de emissão do orçamento
    # conforme selecionado pelo usuário no formulário de compras. Caso não seja
    # informado, permanece nulo.
    data_orcamento = db.Column(db.Date, nullable=True)
    # Data de criação do registro no sistema
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    # Usuário que criou a compra
    usuario_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)

    def __repr__(self):
        return f'<Compra {self.id} - {self.valor}>'

@login_manager.user_loader
def user_loader(id):
    return Users.query.filter_by(id=id).first()

@login_manager.request_loader
def request_loader(request):
    username = request.form.get('username')
    user = Users.query.filter_by(username=username).first()
    return user if user else None
