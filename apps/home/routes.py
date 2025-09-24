# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from apps.home import blueprint
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from jinja2 import TemplateNotFound
from apps import db
from apps.authentication.models import Contact
# Adicione essas rotas ao arquivo apps/home/routes.py

from apps.authentication.models import PedidoCompra, ItemPedido, Task, CompletedTask, Fornecedor, Compra
from flask_login import current_user
from datetime import datetime
import os
from werkzeug.utils import secure_filename
from flask import current_app, send_from_directory
import json
import os
from werkzeug.utils import secure_filename
from flask import current_app, send_from_directory

# -----------------------------------------------------------------------------
# Upload configuration
# Define the directory where attachment files (notas/boletos) will be stored.
# This path is resolved relative to the project root, ending up in
# amantini-main/media/attachments. Files saved here are served by the
# download_attachment route defined below.
UPLOAD_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'media', 'attachments'))
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
# Diretório separado para arquivos de orçamentos (compras)
ORCAMENTO_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'media', 'orcamentos'))
os.makedirs(ORCAMENTO_FOLDER, exist_ok=True)

@blueprint.route('/uploads/<path:filename>')
@login_required
def download_attachment(filename):
    """Serve um arquivo anexado a uma tarefa concluída.

    Os arquivos são armazenados em ``UPLOAD_FOLDER`` com nomes únicos.
    Este endpoint usa ``send_from_directory`` para entregar o arquivo como
    download. Requer que o usuário esteja logado.
    """
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)

# Novo endpoint para baixar anexos de orçamentos.
@blueprint.route('/orcamentos/<path:filename>')
@login_required
def download_orcamento(filename):
    """Serve um arquivo anexo de orçamento armazenado em ORCAMENTO_FOLDER."""
    return send_from_directory(ORCAMENTO_FOLDER, filename, as_attachment=True)

@blueprint.route('/pedidos-compra')
@login_required
def pedidos_compra():
    """Lista todos os pedidos de compra"""
    pedidos = PedidoCompra.query.filter_by(usuario_id=current_user.id).order_by(PedidoCompra.data_criacao.desc()).all()
    return render_template('home/pedidos_compra_lista.html', pedidos=pedidos, segment='pedidos')

@blueprint.route('/pedidos-compra/novo')
@login_required
def novo_pedido_compra():
    """Formulário para novo pedido de compra"""
    return render_template('home/pedido_compra_form.html', segment='pedidos')

@blueprint.route('/pedidos-compra/criar', methods=['POST'])
@login_required
def criar_pedido_compra():
    """Cria um novo pedido de compra"""
    try:
        # Criar o pedido
        pedido = PedidoCompra(
            obra=request.form.get('obra', 'FAGA'),
            responsavel=request.form.get('responsavel'),
            prioridade=request.form.get('prioridade'),
            data_necessidade=datetime.strptime(request.form.get('data_necessidade'), '%Y-%m-%d').date(),
            status=request.form.get('status', 'solicitado'),
            observacoes=request.form.get('observacoes', ''),
            usuario_id=current_user.id
        )
        
        db.session.add(pedido)
        db.session.flush()  # Para obter o ID
        
        # Adicionar itens
        itens_json = request.form.get('itens', '[]')
        itens = json.loads(itens_json)
        
        for item_data in itens:
            item = ItemPedido(
                pedido_id=pedido.id,
                codigo_item=item_data['codigo'],
                nome_item=item_data['nome'],
                observacao=item_data.get('observacao', ''),  # NOVO CAMPO
                quantidade=float(item_data['quantidade']),
                unidade=item_data['unidade']
            )
            db.session.add(item)
        
        db.session.commit()
        flash('Pedido de compra criado com sucesso!', 'success')
        return redirect(url_for('home_blueprint.pedidos_compra'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao criar pedido: {str(e)}', 'error')
        return redirect(url_for('home_blueprint.novo_pedido_compra'))
    
@blueprint.route('/pedidos-compra/<int:pedido_id>')
@login_required
def ver_pedido_compra(pedido_id):
    """Visualiza um pedido específico"""
    pedido = PedidoCompra.query.filter_by(id=pedido_id, usuario_id=current_user.id).first_or_404()
    return render_template('home/pedido_compra_detalhes.html', pedido=pedido, segment='pedidos')

@blueprint.route('/pedidos-compra/<int:pedido_id>/editar')
@login_required
def editar_pedido_compra(pedido_id):
    """Edita um pedido de compra"""
    pedido = PedidoCompra.query.filter_by(id=pedido_id, usuario_id=current_user.id).first_or_404()
    return render_template('home/pedido_compra_form.html', pedido=pedido, segment='pedidos')

@blueprint.route('/pedidos-compra/<int:pedido_id>/atualizar', methods=['POST'])
@login_required
def atualizar_pedido_compra(pedido_id):
    """Atualiza um pedido de compra"""
    try:
        pedido = PedidoCompra.query.filter_by(id=pedido_id, usuario_id=current_user.id).first_or_404()
        
        # Atualizar dados do pedido
        pedido.responsavel = request.form.get('responsavel')
        pedido.prioridade = request.form.get('prioridade')
        pedido.data_necessidade = datetime.strptime(request.form.get('data_necessidade'), '%Y-%m-%d').date()
        pedido.status = request.form.get('status')
        pedido.observacoes = request.form.get('observacoes', '')
        
        # Remover itens existentes
        ItemPedido.query.filter_by(pedido_id=pedido.id).delete()
        
        # Adicionar novos itens
        itens_json = request.form.get('itens', '[]')
        itens = json.loads(itens_json)
        
        for item_data in itens:
            item = ItemPedido(
                pedido_id=pedido.id,
                codigo_item=item_data['codigo'],
                nome_item=item_data['nome'],
                observacao=item_data.get('observacao', ''),  # NOVO CAMPO
                quantidade=float(item_data['quantidade']),
                unidade=item_data['unidade']
            )
            db.session.add(item)
        
        db.session.commit()
        flash('Pedido atualizado com sucesso!', 'success')
        return redirect(url_for('home_blueprint.ver_pedido_compra', pedido_id=pedido.id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao atualizar pedido: {str(e)}', 'error')
        return redirect(url_for('home_blueprint.editar_pedido_compra', pedido_id=pedido_id))

@blueprint.route('/api/pedidos-compra', methods=['POST'])
@login_required
def api_criar_pedido():
    """API endpoint para criar pedido via AJAX"""
    try:
        dados = request.get_json()
        
        # Criar o pedido
        pedido = PedidoCompra(
            obra=dados.get('obra', 'FAGA'),
            responsavel=dados['responsavel'],
            prioridade=dados['prioridade'],
            data_necessidade=datetime.strptime(dados['dataNecessidade'], '%Y-%m-%d').date(),
            status=dados.get('status', 'solicitado'),
            observacoes=dados.get('observacoes', ''),
            usuario_id=current_user.id
        )
        
        db.session.add(pedido)
        db.session.flush()
        
        # Adicionar itens
        for item_data in dados['itens']:
            item = ItemPedido(
                pedido_id=pedido.id,
                codigo_item=item_data['codigo'],
                nome_item=item_data['nome'],
                observacao=item_data.get('observacao', ''),  # NOVO CAMPO
                quantidade=float(item_data['quantidade']),
                unidade=item_data['unidade']
            )
            db.session.add(item)
        
        db.session.commit()
        
        return {'success': True, 'message': 'Pedido criado com sucesso!', 'pedido_id': pedido.id}
        
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'message': f'Erro: {str(e)}'}, 400


# -----------------------------------------------------------------------------
# API de Tarefas
# Endpoints para criar e atualizar tarefas no painel Kanban de tarefas.

@blueprint.route('/api/tasks', methods=['POST'])
@login_required
def api_create_task():
    """Cria uma nova tarefa via requisição AJAX."""
    try:
        data = request.get_json() or {}
        # Parse campos básicos
        title = data.get('title')
        if not title:
            return jsonify({'success': False, 'message': 'Título é obrigatório'}), 400
        description = data.get('description', '')
        observations = data.get('observations', '')
        priority = data.get('priority', 'Média')
        assignee = data.get('assignee', '')
        due_date_str = data.get('dueDate')
        if due_date_str:
            try:
                due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
            except ValueError:
                return jsonify({'success': False, 'message': 'Data de vencimento inválida'}), 400
        else:
            due_date = None
        # Determine a posição inicial (fim da coluna "Pendente")
        posicao = data.get('posicao', 0)
        nova_tarefa = Task(
            title=title,
            description=description,
            observations=observations,
            priority=priority,
            assignee=assignee,
            due_date=due_date,
            status='Pendente',
            posicao=posicao,
            usuario_id=current_user.id
        )
        db.session.add(nova_tarefa)
        db.session.commit()
        return jsonify({'success': True, 'task_id': nova_tarefa.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@blueprint.route('/api/tasks/<int:task_id>/status', methods=['PATCH'])
@login_required
def api_update_task_status(task_id):
    """Atualiza o status e a posição de uma tarefa via requisição AJAX."""
    data = request.get_json() or {}
    new_status = data.get('status')
    new_position = data.get('posicao', 0)
    task = Task.query.filter_by(id=task_id, usuario_id=current_user.id).first_or_404()
    # Validar status válido
    valid_statuses = ['Pendente', 'Em Progresso', 'Entregue', 'Aguardando Nota/Boleto']
    if new_status not in valid_statuses:
        return jsonify({'success': False, 'message': 'Status inválido'}), 400
    task.status = new_status
    try:
        task.posicao = int(new_position)
    except (TypeError, ValueError):
        task.posicao = 0
    db.session.commit()
    return jsonify({'success': True})


# Endpoint para atualizar os campos de uma tarefa existente (título, descrição,
# prioridade, responsável, data de vencimento, observações e status). É
# utilizado pelo modal de edição de tarefas no painel Kanban.
@blueprint.route('/api/tasks/<int:task_id>', methods=['PATCH'])
@login_required
def api_update_task(task_id):
    data = request.get_json() or {}
    task = Task.query.filter_by(id=task_id, usuario_id=current_user.id).first_or_404()
    # Campos permitidos para atualização
    title = data.get('title')
    description = data.get('description')
    observations = data.get('observations')
    priority = data.get('priority')
    assignee = data.get('assignee')
    due_date_str = data.get('dueDate') or data.get('due_date')
    status = data.get('status')
    # Atualiza cada campo se fornecido
    if title is not None:
        task.title = title.strip()
    if description is not None:
        task.description = description.strip()
    if observations is not None:
        task.observations = observations.strip()
    if priority is not None:
        task.priority = priority
    if assignee is not None:
        task.assignee = assignee.strip()
    if due_date_str is not None:
        if due_date_str == '':
            task.due_date = None
        else:
            try:
                task.due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
            except ValueError:
                return jsonify({'success': False, 'message': 'Data de vencimento inválida'}), 400
    if status is not None:
        valid_statuses = ['Pendente', 'Em Progresso', 'Entregue', 'Aguardando Nota/Boleto']
        if status not in valid_statuses:
            return jsonify({'success': False, 'message': 'Status inválido'}), 400
        task.status = status
    db.session.commit()
    return jsonify({'success': True})


# Endpoint para concluir uma tarefa. Move a tarefa da tabela tasks para
# completed_tasks, preservando seus dados originais e registrando o
# horário de conclusão e a duração. Após completar, remove a
# tarefa original.

@blueprint.route('/api/tasks/<int:task_id>/complete', methods=['POST'])
@login_required
def api_complete_task(task_id):
    import os
    from datetime import datetime
    from werkzeug.utils import secure_filename

    # Busca a tarefa do usuário logado
    task = Task.query.filter_by(id=task_id, usuario_id=current_user.id).first_or_404()

    # Dados podem vir via multipart/form-data (com arquivo) ou JSON
    data = request.form if request.form else (request.get_json() or {})

    # Campos opcionais para atualização antes de concluir
    title = data.get('title')
    description = data.get('description')
    observations = data.get('observations')
    priority = data.get('priority')
    assignee = data.get('assignee')
    due_date_str = data.get('due_date')
    status = data.get('status') or task.status

    if title is not None:
        task.title = title.strip()
    if description is not None:
        task.description = description.strip()
    if observations is not None:
        task.observations = observations.strip()
    if priority is not None:
        task.priority = priority
    if assignee is not None:
        task.assignee = assignee.strip()
    if due_date_str is not None:
        if due_date_str == '':
            task.due_date = None
        else:
            try:
                task.due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
            except ValueError:
                return jsonify({'success': False, 'message': 'Data de vencimento inválida'}), 400

    # Valida status
    valid_statuses = ['Pendente', 'Em Progresso', 'Entregue', 'Aguardando Nota/Boleto']
    if status not in valid_statuses:
        return jsonify({'success': False, 'message': 'Status inválido'}), 400
    task.status = status

    # Arquivo opcional
    attachment_file = request.files.get('attachment') if 'attachment' in request.files else None
    attachment_path = None

    # Regras por coluna:
    # - Aguardando Nota/Boleto -> exige anexo (fluxo Financeiro inalterado)
    # - Entregue -> não exige anexo (vai para Tarefas Concluídas)
    if status == 'Aguardando Nota/Boleto':
        if not attachment_file or attachment_file.filename == '':
            return jsonify({'success': False, 'message': 'É necessário anexar a nota ou boleto para concluir a tarefa.'}), 400
        # Salva arquivo
        filename = secure_filename(attachment_file.filename)
        timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        filename = f"{task.id}_{timestamp}_{filename}"
        upload_dir = os.path.join(os.getcwd(), 'apps', 'static', 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        file_full = os.path.join(upload_dir, filename)
        attachment_file.save(file_full)
        attachment_path = filename

    # Monta registro em CompletedTask (usamos a mesma tabela; páginas diferentes exibem fluxos diferentes)
    completion_time = datetime.utcnow()
    duration_seconds = int((completion_time - task.data_criacao).total_seconds()) if getattr(task, 'data_criacao', None) else None

    completed = CompletedTask(
        original_task_id=task.id,
        title=task.title,
        description=task.description,
        observations=getattr(task, 'observations', None),
        priority=task.priority,
        assignee=task.assignee,
        due_date=task.due_date,
        status=task.status,
        data_criacao=getattr(task, 'data_criacao', None),
        data_conclusao=completion_time,
        duration_seconds=duration_seconds,
        usuario_id=task.usuario_id,
        attachment_path=attachment_path
    )

    # Remove a tarefa original e salva a concluída
    db.session.delete(task)
    db.session.add(completed)
    db.session.commit()

    return jsonify({'success': True, 'completed_id': completed.id})

# Página que lista todas as tarefas concluídas do usuário atual.
@blueprint.route('/tarefas-concluidas')
@login_required
def tarefas_concluidas():
    """
    Página que lista todas as tarefas concluídas do usuário. O tempo gasto
    é exibido em dias inteiros (diferença de data entre criação e conclusão).
    """
    # Buscar tarefas concluídas ordenadas por data de conclusão decrescente
    completadas = (CompletedTask.query
                   .filter_by(usuario_id=current_user.id)
                   .order_by(CompletedTask.data_conclusao.desc())
                   .all())
    # Converter duração para dias inteiros em vez de HH:MM:SS
    for t in completadas:
        if t.data_criacao and t.data_conclusao:
            # Calcula diferença em dias completos entre as datas
            duration_days = (t.data_conclusao.date() - t.data_criacao.date()).days
            # Garante pelo menos 0 dias se mesma data
            if duration_days < 0:
                duration_days = 0
            t.duration_display = f"{duration_days} dia{'s' if duration_days != 1 else ''}"
        else:
            t.duration_display = ''
    return render_template('home/tasks_completed.html', completadas=completadas, segment='tarefas_concluidas')


# -----------------------------------------------------------------------------
# Página e APIs de Compras (Orçamentos)
#
# A página de "Compras" exibe uma lista de orçamentos cadastrados e permite
# adicionar novos registros. Cada compra está vinculada a um fornecedor e
# possui um valor e um arquivo de orçamento anexado.

@blueprint.route('/compras')
@login_required
def compras():
    """Exibe a página de compras (orçamentos) com todos os registros do usuário."""
    # Recupera todas as compras do usuário atual
    compras = (Compra.query
               .filter_by(usuario_id=current_user.id)
               .order_by(Compra.data_criacao.desc())
               .all())
    # Recupera fornecedores do usuário atual para popular o formulário
    fornecedores = (Fornecedor.query
                    .filter_by(usuario_id=current_user.id)
                    .order_by(Fornecedor.nome)
                    .all())
    return render_template('home/compras.html', compras=compras, fornecedores=fornecedores, segment='compras')


@blueprint.route('/api/fornecedores', methods=['POST'])
@login_required
def api_criar_fornecedor():
    """
    Cria um novo fornecedor a partir de dados enviados via JSON ou formulário.

    Além do campo obrigatório ``nome`` (nome fantasia), aceita diversos campos opcionais
    como razão social, CNPJ, IE, IM, telefones, endereço completo e observações.
    Estes valores são persistidos nos campos correspondentes da tabela ``fornecedores``.
    """
    data = request.form if request.form else (request.get_json() or {})
    nome = data.get('nome') or data.get('nome_fantasia')
    if not nome:
        return jsonify({'success': False, 'message': 'Nome do fornecedor é obrigatório.'}), 400
    fornecedor = Fornecedor(
        nome=nome.strip(),
        email=data.get('email'),
        telefone=data.get('telefone'),
        razao_social=data.get('razao_social'),
        nome_fantasia=data.get('nome_fantasia') or data.get('nome'),
        cnpj=data.get('cnpj'),
        ie=data.get('ie'),
        im=data.get('im'),
        celular=data.get('celular'),
        cep=data.get('cep'),
        logradouro=data.get('logradouro'),
        numero=data.get('numero'),
        bairro=data.get('bairro'),
        cidade=data.get('cidade'),
        estado=(data.get('estado') or '').upper() if data.get('estado') else None,
        obs=data.get('obs'),
        usuario_id=current_user.id
    )
    db.session.add(fornecedor)
    db.session.commit()
    return jsonify({'success': True, 'fornecedor_id': fornecedor.id, 'nome': fornecedor.nome})


@blueprint.route('/api/compras', methods=['POST'])
@login_required
def api_criar_compra():
    """Cria uma nova compra (orçamento) com anexo opcional de orçamento."""
    # Permite envio via form-data ou JSON; form-data é usado quando há arquivo
    data = request.form if request.form else (request.get_json() or {})
    fornecedor_id = data.get('fornecedor_id') or data.get('fornecedorId')
    valor = data.get('valor') or data.get('value')
    # Nome do novo fornecedor, se fornecido
    novo_fornecedor_nome = data.get('novo_fornecedor') or data.get('novoFornecedor')
    # Data do orçamento (formato YYYY-MM-DD). Este campo é opcional e, quando
    # presente, será convertido para um objeto date. O front‑end utiliza
    # ``id="compra-data"`` para capturar essa informação.
    data_orcamento_str = data.get('data') or data.get('data_orcamento') or data.get('dataOrcamento')
    # Validação do valor
    try:
        valor_float = float(valor)
        if valor_float <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Valor inválido para orçamento.'}), 400
    # Cria fornecedor se necessário
    fornecedor = None
    if novo_fornecedor_nome:
        fornecedor = Fornecedor(nome=novo_fornecedor_nome.strip(), usuario_id=current_user.id)
        db.session.add(fornecedor)
        db.session.flush()  # obtém id
        fornecedor_id = fornecedor.id
    else:
        if not fornecedor_id:
            return jsonify({'success': False, 'message': 'Fornecedor é obrigatório.'}), 400
        fornecedor = Fornecedor.query.filter_by(id=int(fornecedor_id), usuario_id=current_user.id).first()
        if not fornecedor:
            return jsonify({'success': False, 'message': 'Fornecedor não encontrado.'}), 404
    # Processa arquivo de anexo, se houver
    attachment_file = request.files.get('anexo') if request.files else None
    attachment_path = None
    if attachment_file and attachment_file.filename:
        filename = secure_filename(attachment_file.filename)
        timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        filename = f"{current_user.id}_{timestamp}_{filename}"
        upload_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'media', 'orcamentos'))
        os.makedirs(upload_dir, exist_ok=True)
        save_path = os.path.join(upload_dir, filename)
        attachment_file.save(save_path)
        attachment_path = filename
    # Converte a data do orçamento, se fornecida
    data_orcamento = None
    if data_orcamento_str:
        try:
            # espera formato YYYY-MM-DD
            data_orcamento = datetime.strptime(data_orcamento_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'message': 'Data do orçamento inválida.'}), 400
    # Cria registro de compra
    compra = Compra(
        fornecedor_id=int(fornecedor_id),
        valor=valor_float,
        attachment_path=attachment_path,
        data_orcamento=data_orcamento,
        usuario_id=current_user.id
    )
    db.session.add(compra)
    db.session.commit()
    return jsonify({'success': True, 'compra_id': compra.id})


@blueprint.route('/pedidos-compra/kanban')
@login_required
def pedidos_compra_kanban():
    """Exibe o quadro Kanban de pedidos de compra"""
    # Obtém todos os pedidos do usuário atual ordenados por posição para cada status
    pedidos = (PedidoCompra.query
               .filter_by(usuario_id=current_user.id)
               .order_by(PedidoCompra.posicao)
               .all())
    return render_template('home/pedidos_compra_kanban.html', pedidos=pedidos, segment='pedidos')


@blueprint.route('/api/pedidos-compra/<int:pedido_id>/status', methods=['PATCH'])
@login_required
def atualizar_status_pedido(pedido_id):
    """Atualiza o status e a posição de um pedido de compra (Kanban)"""
    data = request.get_json() or {}
    novo_status = data.get('status')
    nova_posicao = data.get('posicao', 0)
    # Garantir que o pedido existe e pertence ao usuário atual
    pedido = PedidoCompra.query.filter_by(id=pedido_id, usuario_id=current_user.id).first_or_404()
    # Validar o status
    if novo_status not in ['solicitado', 'aprovado', 'em_compra', 'entregue']:
        return jsonify({'success': False, 'message': 'Status inválido'}), 400
    # Atualizar status e posição
    pedido.status = novo_status
    try:
        pedido.posicao = int(nova_posicao)
    except (TypeError, ValueError):
        pedido.posicao = 0
    db.session.commit()
    return jsonify({'success': True})


@blueprint.route('/index')
@login_required
def index():
    return render_template('home/index.html', segment='index')


@blueprint.route('/contacts', methods=['GET', 'POST'])
@login_required
def contacts():
    if request.method == 'POST':
        # Manter a lógica existente de POST
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')

        new_contact = Contact(name=name, email=email, phone=phone)

        try:
            db.session.add(new_contact)
            db.session.commit()
            flash('Contato adicionado com sucesso!', 'success')
        except Exception as e:
            db.session.rollback()
            flash('Erro ao adicionar contato: ' + str(e), 'danger')

        return redirect(url_for('home_blueprint.contacts'))

    # Adicionar lógica de busca para método GET
    search = request.args.get('search', '')
    
    if search:
        # Busca por nome, email ou telefone
        contacts = Contact.query.filter(
            db.or_(
                Contact.name.ilike(f'%{search}%'),
                Contact.email.ilike(f'%{search}%'),
                Contact.phone.ilike(f'%{search}%')
            )
        ).all()
    else:
        # Se não houver busca, retorna todos os contatos
        contacts = Contact.query.all()

    return render_template('home/contacts.html', contacts=contacts, segment='contacts')


@blueprint.route('/tasks')
@login_required
def tasks():
    """
    Exibe o painel de tarefas com suporte a movimentação persistente.
    As tarefas são carregadas do banco de dados e filtradas por usuário, ordenadas pela posição.
    """
    tasks = (Task.query
             .filter_by(usuario_id=current_user.id)
             .order_by(Task.posicao)
             .all())
    return render_template('home/tasks.html', tasks=tasks, segment='tasks')


@blueprint.route('/opportunities')
@login_required
def opportunities():
    return render_template('home/opportunities.html', segment='opportunities')


@blueprint.route('/reports')
@login_required
def reports():
    return render_template('home/reports.html', segment='reports')


@blueprint.route('/<template>')
@login_required
def route_template(template):
    try:
        if not template.endswith('.html'):
            template += '.html'

        # Detect the current page
        segment = get_segment(request)

        # Serve the file (if exists) from app/templates/home/FILE.html
        return render_template("home/" + template, segment=segment)

    except TemplateNotFound:
        return render_template('home/page-404.html'), 404

    except:
        return render_template('home/page-500.html'), 500
    
@blueprint.route('/contacts/edit/<int:id>', methods=['POST'])
@login_required
def edit_contact(id):
    contact = Contact.query.get(id)

    if contact:
        contact.name = request.form.get('name')
        contact.email = request.form.get('email')
        contact.phone = request.form.get('phone')

        db.session.commit()
        flash('Contato atualizado com sucesso!', 'success')
    else:
        flash('Contato não encontrado.', 'danger')

    return redirect(url_for('home_blueprint.contacts'))

@blueprint.route('/contacts/delete/<int:id>', methods=['GET'])
@login_required
def delete_contact(id):
    contact = Contact.query.get(id)
    if contact:
        db.session.delete(contact)
        db.session.commit()
        flash('Contato excluído com sucesso!', 'success')
    else:
        flash('Contato não encontrado.', 'danger')

    return redirect(url_for('home_blueprint.contacts'))

# Helper - Extract current page name from request
def get_segment(request):
    try:
        segment = request.path.split('/')[-1]

        if segment == '':
            segment = 'index'

        return segment

    except:
        return None
