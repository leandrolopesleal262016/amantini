# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from apps.home import blueprint

import csv
import io
import json
import os
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import abort, flash, jsonify, redirect, render_template, request, send_file, send_from_directory, url_for
from flask_login import current_user, login_required
from jinja2 import TemplateNotFound
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError, ProgrammingError
from werkzeug.utils import secure_filename
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


from apps import db
from apps.authentication.models import (
    Contact,
    Obra,
    PedidoCompra,
    ItemPedido,
    Task,
    CompletedTask,
    Fornecedor,
    Compra,
    Material,
)

DATA_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data'))
FORNECEDORES_CSV = os.path.join(DATA_FOLDER, 'fornecedores.csv')
os.makedirs(DATA_FOLDER, exist_ok=True)


def obras_feature_enabled():
    """Check if the optional 'obras' table exists and can be queried."""
    try:
        inspector = inspect(db.engine)
        if not inspector.has_table('obras'):
            return False
        return True
    except (OperationalError, ProgrammingError):
        db.session.rollback()
        return False


def safe_obras_list(usuario_id=None):
    """Return all obras when the feature is available."""
    if not obras_feature_enabled():
        return [], False
    try:
        obras = (Obra.query
                 .order_by(Obra.nome)
                 .all())
        return obras, True
    except (OperationalError, ProgrammingError):
        db.session.rollback()
        return [], False


def _normalize_cell(value):
    return value.strip() if isinstance(value, str) else ''


def _truncate(value, max_length):
    if not value:
        return value
    value = value.strip()
    return value if len(value) <= max_length else value[:max_length]


def load_csv_fornecedores():
    if not os.path.isfile(FORNECEDORES_CSV):
        return []
    encodings = ('utf-8-sig', 'cp1252', 'latin-1')
    for encoding in encodings:
        try:
            with open(FORNECEDORES_CSV, newline='', encoding=encoding) as csvfile:
                reader = csv.DictReader(csvfile, delimiter=';')
                rows = []
                for row in reader:
                    def pick(*keys):
                        for key in keys:
                            val = row.get(key)
                            if val:
                                return val
                        return ''
                    rows.append({
                        'razao_social': _normalize_cell(pick('RAZÃO SOCIAL', 'RAZAO SOCIAL', 'Razão Social', 'Razao Social')),
                        'nome_fantasia': _normalize_cell(pick('NOME FANTASIA', 'Nome Fantasia')),
                        'cnpj': _normalize_cell(pick('CNPJ')),
                        'contato': _normalize_cell(pick('CONTATO (WhatsApp)', 'CONTATO', 'WhatsApp', 'TELEFONE')),
                        'email': _normalize_cell(pick('E-MAIL', 'EMAIL')),
                        'cidade': _normalize_cell(pick('CIDADE', 'Cidade')),
                        'estado': _normalize_cell(pick('ESTADO', 'Estado', 'UF')),
                    })
                return rows
        except UnicodeDecodeError:
            continue
    return []


def normalize_cnpj(value):
    raw = (value or '').strip()
    if not raw:
        return ''
    digits = re.sub(r'\D', '', raw)
    upper = raw.upper()
    if 'E' in upper or (',' in raw and len(digits) < 14):
        candidate = raw.replace('.', '').replace('/', '').replace('-', '').replace(' ', '').replace(',', '.')
        try:
            digits = f"{int(Decimal(candidate)):014d}"
        except (InvalidOperation, ValueError):
            digits = re.sub(r'\D', '', candidate)
    if len(digits) > 14:
        digits = digits[-14:]
    return digits


def sync_csv_fornecedores(usuario_id):
    rows = load_csv_fornecedores()
    if not rows:
        return 0, 0
    existing = Fornecedor.query.all()
    by_cnpj = {}
    by_name = {}
    for fornecedor in existing:
        if fornecedor.cnpj:
            by_cnpj[fornecedor.cnpj] = fornecedor
        key = (fornecedor.nome or fornecedor.nome_fantasia or '').strip().lower()
        if key:
            by_name[key] = fornecedor
    created = 0
    updated = 0
    for row in rows:
        display_name_source = row['nome_fantasia'] or row['razao_social']
        display_name = display_name_source.strip() if display_name_source else ''
        if not display_name:
            continue
        cnpj = normalize_cnpj(row['cnpj'])
        fornecedor = by_cnpj.get(cnpj) if cnpj else None
        if not fornecedor:
            fornecedor = by_name.get(display_name.lower())
        if fornecedor:
            changed = False
            if not fornecedor.nome:
                fornecedor.nome = _truncate(display_name, 100)
                changed = True
            if row['razao_social'] and not fornecedor.razao_social:
                fornecedor.razao_social = _truncate(row['razao_social'], 150)
                changed = True
            if row['nome_fantasia'] and not fornecedor.nome_fantasia:
                fornecedor.nome_fantasia = _truncate(row['nome_fantasia'], 150)
                changed = True
            if cnpj and not fornecedor.cnpj:
                fornecedor.cnpj = cnpj
                by_cnpj[cnpj] = fornecedor
                changed = True
            if row['email'] and not fornecedor.email:
                fornecedor.email = _truncate(row['email'], 100)
                changed = True
            contato = _truncate(row['contato'], 20)
            if contato:
                if not fornecedor.telefone:
                    fornecedor.telefone = contato
                    changed = True
                if not fornecedor.celular:
                    fornecedor.celular = contato
                    changed = True
            if row['cidade'] and not fornecedor.cidade:
                fornecedor.cidade = _truncate(row['cidade'], 100)
                changed = True
            if row['estado']:
                estado = row['estado'].strip().upper()[:2]
                if estado and fornecedor.estado != estado:
                    fornecedor.estado = estado
                    changed = True
            if changed:
                updated += 1
            continue
        contato = _truncate(row['contato'], 20)
        novo = Fornecedor(
            nome=_truncate(display_name, 100),
            razao_social=_truncate(row['razao_social'] or display_name, 150),
            nome_fantasia=_truncate(row['nome_fantasia'] or display_name, 150),
            cnpj=cnpj or None,
            telefone=contato,
            email=_truncate(row['email'], 100),
            cidade=_truncate(row['cidade'], 100),
            estado=row['estado'].strip().upper()[:2] if row['estado'] else None,
            celular=contato,
            usuario_id=usuario_id,
        )
        db.session.add(novo)
        if cnpj:
            by_cnpj[cnpj] = novo
        by_name[display_name.lower()] = novo
        created += 1
    if created or updated:
        db.session.commit()
    return created, updated

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

    Prioriza os anexos salvos em ``UPLOAD_FOLDER`` e oferece um fallback
    para o diretório legado ``apps/static/uploads`` usado anteriormente.
    """
    if os.path.isfile(os.path.join(UPLOAD_FOLDER, filename)):
        return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)

    legacy_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads'))
    if os.path.isfile(os.path.join(legacy_folder, filename)):
        return send_from_directory(legacy_folder, filename, as_attachment=True)

    abort(404)

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
    pedidos = (PedidoCompra.query
               .order_by(PedidoCompra.data_criacao.desc())
               .all())
    return render_template('home/pedidos_compra_lista.html', pedidos=pedidos, segment='pedidos')

@blueprint.route('/pedidos-compra/novo')
@login_required
def novo_pedido_compra():
    """Formulário para novo pedido de compra"""
    materiais = (Material.query
                 .order_by(Material.nome)
                 .all())
    obras, obras_enabled = safe_obras_list()
    return render_template(
        'home/pedido_compra_form.html',
        obras=obras,
        obras_enabled=obras_enabled,
        materiais=materiais,
        obra_nome_padrao='FAGA',
        segment='pedidos'
    )

@blueprint.route('/pedidos-compra/criar', methods=['POST'])
@login_required
def criar_pedido_compra():
    """Cria um novo pedido de compra"""
    try:
        use_obras = obras_feature_enabled()

        if use_obras:
            obra_id_raw = request.form.get('obra_id')
            if not obra_id_raw:
                raise ValueError('Selecione uma obra válida.')
            try:
                obra_id = int(obra_id_raw)
            except (TypeError, ValueError):
                raise ValueError('Obra selecionada é inválida.')
            obra = Obra.query.filter_by(id=obra_id).first()
            if not obra:
                raise ValueError('Obra selecionada não encontrada.')

            obra_nome = obra.nome
            obra_id_final = obra.id
            obra_endereco = obra.endereco
        else:
            obra_nome = (request.form.get('obra_nome_manual') or request.form.get('obra') or 'FAGA').strip()
            if not obra_nome:
                obra_nome = 'FAGA'
            obra_id_final = None
            obra_endereco = request.form.get('obra_endereco_manual', '').strip() or None

        data_necessidade_str = request.form.get('data_necessidade')
        if not data_necessidade_str:
            raise ValueError('Informe a data de necessidade do pedido.')

        data_necessidade = datetime.strptime(data_necessidade_str, '%Y-%m-%d').date()

        pedido = PedidoCompra(
            obra=obra_nome,
            obra_id=obra_id_final,
            obra_endereco=obra_endereco,
            responsavel=request.form.get('responsavel'),
            prioridade=request.form.get('prioridade'),
            data_necessidade=data_necessidade,
            status=request.form.get('status', 'solicitado'),
            observacoes=request.form.get('observacoes', ''),
            usuario_id=current_user.id
        )

        db.session.add(pedido)
        db.session.flush()  # Para obter o ID

        itens_json = request.form.get('itens', '[]')
        itens = json.loads(itens_json)

        for item_data in itens:
            item = ItemPedido(
                pedido_id=pedido.id,
                codigo_item=item_data['codigo'],
                nome_item=item_data['nome'],
                observacao=item_data.get('observacao', ''),
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
    pedido = PedidoCompra.query.filter_by(id=pedido_id).first_or_404()
    dias_decorridos = None
    if pedido.data_criacao:
        try:
            dias_decorridos = (datetime.utcnow().date() - pedido.data_criacao.date()).days
        except AttributeError:
            dias_decorridos = None
    if dias_decorridos is not None and dias_decorridos < 0:
        dias_decorridos = 0
    return render_template('home/pedido_compra_detalhes.html', pedido=pedido, dias_decorridos=dias_decorridos, segment='pedidos')

@blueprint.route('/pedidos-compra/<int:pedido_id>/pdf')
@login_required
def pedido_compra_pdf(pedido_id):
    """Gera um PDF com os dados completos do pedido de compra."""
    pedido = PedidoCompra.query.filter_by(id=pedido_id).first_or_404()

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 30
    y = height - margin

    def write_line(text, *, size=11, leading=16, bold=False):
        nonlocal y
        font_name = 'Helvetica-Bold' if bold else 'Helvetica'
        if y <= margin:
            pdf.showPage()
            y = height - margin
        pdf.setFont(font_name, size)
        pdf.drawString(margin, y, text)
        y -= leading

    def write_key_value(label, value):
        write_line(f"{label}: {value}", size=11, leading=15)

    pdf.setTitle(f"Pedido de Compra #{pedido.id}")

    write_line("Pedido de Compra", size=16, bold=True)
    write_line(f"Número: {pedido.id}", size=12, leading=18)
    write_line("")

    obra_nome = pedido.obra or (pedido.obra_rel.nome if pedido.obra_rel else '-')
    obra_endereco = pedido.obra_endereco or (pedido.obra_rel.endereco if pedido.obra_rel else '')

    write_line("Informações da Obra", size=13, bold=True)
    write_key_value("Obra", obra_nome)
    if obra_endereco:
        write_key_value("Endereço", obra_endereco)
    write_line("")

    write_line("Detalhes do Pedido", size=13, bold=True)
    write_key_value("Responsável", pedido.responsavel or '-')
    write_key_value("Prioridade", (pedido.prioridade or '-').title())
    write_key_value("Status", (pedido.status or '-').replace('_', ' ').title())
    write_key_value("Data de necessidade", pedido.data_necessidade.strftime('%d/%m/%Y'))
    write_key_value("Data de criação", pedido.data_criacao.strftime('%d/%m/%Y %H:%M'))
    write_line("")

    if pedido.observacoes:
        write_line("Observações", size=13, bold=True)
        for linha in pedido.observacoes.splitlines():
            write_line(linha)
        write_line("")

    write_line("Itens", size=13, bold=True)
    write_line("Código / Descrição / Quantidade / Unidade", bold=True, size=11, leading=14)
    for item in pedido.itens:
        descricao = f"{item.codigo_item} - {item.nome_item}"
        quantidade = f"{item.quantidade:g}"
        write_line(descricao)
        detalhes = f"Qtd: {quantidade} {item.unidade}"
        if item.observacao:
            detalhes += f" | Obs: {item.observacao}"
        write_line(detalhes, size=10)
        write_line("")

    if not pedido.itens:
        write_line("(Nenhum item cadastrado)")

    pdf.save()
    buffer.seek(0)

    filename = f"pedido_compra_{pedido.id}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')

@blueprint.route('/pedidos-compra/<int:pedido_id>/editar')
@login_required
def editar_pedido_compra(pedido_id):

    """Edita um pedido de compra"""

    pedido = PedidoCompra.query.filter_by(id=pedido_id).first_or_404()
    materiais = (Material.query
                 .order_by(Material.nome)
                 .all())

    obras, obras_enabled = safe_obras_list()

    return render_template(

        'home/pedido_compra_form.html',

        pedido=pedido,

        obras=obras,

        obras_enabled=obras_enabled,

        materiais=materiais,

        obra_atual=pedido.obra_rel,

        obra_nome_padrao=pedido.obra or 'FAGA',

        segment='pedidos'

    )





@blueprint.route('/pedidos-compra/<int:pedido_id>/atualizar', methods=['POST'])
@login_required
def atualizar_pedido_compra(pedido_id):
    """Atualiza um pedido de compra"""
    try:
        pedido = PedidoCompra.query.filter_by(id=pedido_id).first_or_404()
        use_obras = obras_feature_enabled()

        if use_obras:
            obra_id_raw = request.form.get('obra_id')
            if not obra_id_raw:
                raise ValueError('Selecione uma obra válida.')
            try:
                obra_id = int(obra_id_raw)
            except (TypeError, ValueError):
                raise ValueError('Obra selecionada é inválida.')
            obra = Obra.query.filter_by(id=obra_id).first()
            if not obra:
                raise ValueError('Obra selecionada não encontrada.')

            pedido.obra = obra.nome
            pedido.obra_id = obra.id
            pedido.obra_endereco = obra.endereco
        else:
            obra_nome = (request.form.get('obra_nome_manual') or request.form.get('obra') or pedido.obra or 'FAGA').strip()
            pedido.obra = obra_nome or 'FAGA'
            pedido.obra_id = None
            manual_endereco = request.form.get('obra_endereco_manual', '').strip()
            if manual_endereco:
                pedido.obra_endereco = manual_endereco

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
                observacao=item_data.get('observacao', ''),
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
        dados = request.get_json() or {}

        use_obras = obras_feature_enabled()

        if use_obras:
            obra_id_raw = dados.get('obra_id')
            if not obra_id_raw:
                raise ValueError('Selecione uma obra válida.')
            try:
                obra_id = int(obra_id_raw)
            except (TypeError, ValueError):
                raise ValueError('Obra selecionada é inválida.')
            obra = Obra.query.filter_by(id=obra_id).first()
            if not obra:
                raise ValueError('Obra selecionada não encontrada.')

            obra_nome = obra.nome
            obra_id_final = obra.id
            obra_endereco = obra.endereco
        else:
            obra_nome = (dados.get('obra_nome') or dados.get('obra') or 'FAGA').strip()
            if not obra_nome:
                obra_nome = 'FAGA'
            obra_id_final = None
            obra_endereco = (dados.get('obra_endereco') or '').strip() or None

        data_necessidade_str = dados.get('dataNecessidade')
        if not data_necessidade_str:
            raise ValueError('Informe a data de necessidade do pedido.')
        data_necessidade = datetime.strptime(data_necessidade_str, '%Y-%m-%d').date()

        pedido = PedidoCompra(
            obra=obra_nome,
            obra_id=obra_id_final,
            obra_endereco=obra_endereco,
            responsavel=dados['responsavel'],
            prioridade=dados['prioridade'],
            data_necessidade=data_necessidade,
            status=dados.get('status', 'solicitado'),
            observacoes=dados.get('observacoes', ''),
            usuario_id=current_user.id
        )

        db.session.add(pedido)
        db.session.flush()

        itens = dados.get('itens', [])
        for item_data in itens:
            item = ItemPedido(
                pedido_id=pedido.id,
                codigo_item=item_data['codigo'],
                nome_item=item_data['nome'],
                observacao=item_data.get('observacao', ''),
                quantidade=float(item_data['quantidade']),
                unidade=item_data['unidade']
            )
            db.session.add(item)

        db.session.commit()
        return jsonify({'success': True, 'pedido_id': pedido.id})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400


@blueprint.route('/api/tasks', methods=['POST'])
@login_required
def api_create_task():
    """Cria uma nova tarefa via requisição AJAX."""
    try:
        data = request.get_json() or {}
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
    task = Task.query.filter_by(id=task_id).first_or_404()
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
    task = Task.query.filter_by(id=task_id).first_or_404()
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


    # Busca a tarefa do usuário logado
    task = Task.query.filter_by(id=task_id).first_or_404()

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
        upload_dir = UPLOAD_FOLDER
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
    """Exibe a página de compras (orçamentos) com todos os registros disponíveis."""
    sync_csv_fornecedores(current_user.id)
    # Recupera todas as compras do usuário atual
    compras = (Compra.query
               .order_by(Compra.data_criacao.desc())
               .all())
    # Recupera fornecedores do usuário atual para popular o formulário
    fornecedores = (Fornecedor.query
                    .order_by(Fornecedor.nome)
                    .all())
    return render_template('home/compras.html', compras=compras, fornecedores=fornecedores, segment='compras')


@blueprint.route('/api/obras', methods=['POST'])
@login_required
def api_criar_obra():
    """Cria uma nova obra (projeto) a partir dos dados enviados via formulário ou JSON."""
    data = request.form if request.form else (request.get_json() or {})
    nome = (data.get('nome') or data.get('nome_obra') or '').strip()
    endereco = (data.get('endereco') or data.get('endereco_obra') or '').strip()

    if not nome:
        return jsonify({'success': False, 'message': 'Informe o nome da obra.'}), 400

    nome = nome[:150]
    endereco = endereco[:255] if endereco else None

    existente = (Obra.query
                 .filter(Obra.nome.ilike(nome))
                 .first())
    if existente:
        return jsonify({
            'success': True,
            'obra_id': existente.id,
            'nome': existente.nome,
            'endereco': existente.endereco or ''
        })

    obra = Obra(nome=nome, endereco=endereco, usuario_id=current_user.id)
    db.session.add(obra)
    db.session.commit()

    return jsonify({
        'success': True,
        'obra_id': obra.id,
        'nome': obra.nome,
        'endereco': obra.endereco or ''
    })

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


@blueprint.route('/api/materiais', methods=['GET', 'POST'])
@login_required
def api_materiais():
    """Lista materiais ou cadastra um novo material para uso no combo de itens."""
    try:
        if request.method == 'GET':
            materiais = (Material.query
                         .order_by(Material.nome)
                         .all())
            return jsonify({
                'success': True,
                'materiais': [
                    {
                        'id': m.id,
                        'nome': m.nome,
                        'unidade': m.unidade or 'un'
                    } for m in materiais
                ]
            })

        data = request.get_json() or {}
        nome = (data.get('nome') or '').strip()
        unidade = (data.get('unidade') or 'un').strip() or 'un'

        if not nome:
            return jsonify({'success': False, 'message': 'Nome do material é obrigatório.'}), 400

        existente = (Material.query
                     .filter(Material.nome.ilike(nome))
                     .first())
        if existente:
            if unidade and not existente.unidade:
                existente.unidade = unidade
                db.session.commit()
            return jsonify({
                'success': True,
                'material_id': existente.id,
                'nome': existente.nome,
                'unidade': existente.unidade or 'un',
                'ja_existia': True
            })

        material = Material(nome=nome, unidade=unidade)
        db.session.add(material)
        db.session.commit()

        return jsonify({
            'success': True,
            'material_id': material.id,
            'nome': material.nome,
            'unidade': material.unidade or 'un',
            'ja_existia': False
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


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
        fornecedor = Fornecedor.query.filter_by(id=int(fornecedor_id)).first()
        if not fornecedor:
            return jsonify({'success': False, 'message': 'Fornecedor não encontrado.'}), 404
    # Processa arquivo de anexo, se houver
    attachment_file = request.files.get('anexo') if request.files else None
    attachment_path = None
    if attachment_file and attachment_file.filename:
        filename = secure_filename(attachment_file.filename)
        timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        filename = f"{current_user.id}_{timestamp}_{filename}"
        save_path = os.path.join(ORCAMENTO_FOLDER, filename)
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
    pedido = PedidoCompra.query.filter_by(id=pedido_id).first_or_404()
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
    As tarefas são carregadas do banco de dados e ordenadas pela posição.
    """
    tasks = (Task.query
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


@blueprint.route('/financeiro')
@login_required
def financeiro():
    """Lista tarefas concluídas que aguardam nota ou boleto."""
    aguardando = (CompletedTask.query
                  .filter_by(status='Aguardando Nota/Boleto')
                  .order_by(CompletedTask.data_conclusao.desc())
                  .all())
    for tarefa in aguardando:
        if getattr(tarefa, 'data_criacao', None) and tarefa.data_conclusao:
            duration_days = (tarefa.data_conclusao.date() - tarefa.data_criacao.date()).days
            if duration_days < 0:
                duration_days = 0
            tarefa.duration_display = f"{duration_days} dia{'s' if duration_days != 1 else ''}"
        else:
            tarefa.duration_display = ''
    return render_template('home/financeiro.html', tarefas=aguardando, segment='financeiro')
# Helper - Extract current page name from request
def get_segment(request):
    try:
        segment = request.path.split('/')[-1]

        if segment == '':
            segment = 'index'

        return segment

    except:
        return None
