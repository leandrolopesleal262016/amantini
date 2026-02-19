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
import zipfile
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import abort, flash, jsonify, redirect, render_template, request, send_file, send_from_directory, url_for
from flask_login import current_user, login_required
from jinja2 import TemplateNotFound
from sqlalchemy import func, inspect
from sqlalchemy.exc import OperationalError, ProgrammingError
from werkzeug.utils import secure_filename
from decouple import config
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


from apps import db
from apps.authentication.models import (
    Contact,
    Obra,
    PedidoCompra,
    PedidoCompraAttachment,
    ItemPedido,
    Task,
    CompletedTask,
    CompletedTaskAttachment,
    Fornecedor,
    Compra,
    CompraAttachment,
    CompraWorkflow,
    Material,
    RecadoMural,
    Users,
)

DATA_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data'))
FORNECEDORES_CSV = os.path.join(DATA_FOLDER, 'fornecedores.csv')
os.makedirs(DATA_FOLDER, exist_ok=True)


def _resolve_local_timezone():
    tz_name = config('APP_TIMEZONE', default='America/Sao_Paulo')
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        # Fallback for environments without tzdata installed.
        return timezone(timedelta(hours=-3))


LOCAL_TIMEZONE = _resolve_local_timezone()


def utc_naive_to_local(dt_value):
    """Convert UTC-naive datetime stored in DB to local timezone."""
    if not dt_value:
        return None
    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=timezone.utc)
    else:
        dt_value = dt_value.astimezone(timezone.utc)
    return dt_value.astimezone(LOCAL_TIMEZONE)


def attach_local_datetime_fields(record, field_names, fmt='%d/%m/%Y %H:%M'):
    """Attach `<field>_local` and `<field>_local_str` attributes to a record."""
    for field_name in field_names:
        raw_value = getattr(record, field_name, None)
        local_value = utc_naive_to_local(raw_value)
        setattr(record, f'{field_name}_local', local_value)
        setattr(record, f'{field_name}_local_str', local_value.strftime(fmt) if local_value else '')
    return record


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
        query = Obra.query
        if usuario_id is not None:
            query = query.filter_by(usuario_id=usuario_id)
        obras = query.order_by(Obra.nome).all()
        return obras, True
    except (OperationalError, ProgrammingError):
        db.session.rollback()
        return [], False


PEDIDO_STATUS_VALID = {'pendente', 'em_cotacao', 'entregue'}
PEDIDO_STATUS_LEGACY_MAP = {
    'solicitado': 'pendente',
    'aprovado': 'em_cotacao',
    'em_compra': 'em_cotacao',
}


def normalize_pedido_status(raw_status):
    status = (raw_status or '').strip().lower()
    if status in PEDIDO_STATUS_VALID:
        return status
    return PEDIDO_STATUS_LEGACY_MAP.get(status)


def _build_obra_card(nome, endereco, pedidos):
    status_map = {
        'solicitado': 0,
        'aprovado': 0,
        'em_compra': 0,
        'entregue': 0,
        'pendente': 0,
        'em_cotacao': 0,
    }
    total_itens = 0

    for pedido in pedidos:
        total_itens += len(pedido.itens or [])
        normalized = normalize_pedido_status(pedido.status)
        if normalized == 'pendente':
            status_map['pendente'] += 1
            status_map['solicitado'] += 1
        elif normalized == 'em_cotacao':
            status_map['em_cotacao'] += 1
            status_map['aprovado'] += 1
            status_map['em_compra'] += 1
        elif normalized == 'entregue':
            status_map['entregue'] += 1

    return {
        'nome': nome or 'Obra sem nome',
        'endereco': endereco,
        'total_pedidos': len(pedidos),
        'total_itens': total_itens,
        'status': status_map,
        'pedidos_recentes': pedidos[:4],
    }


def load_pedidos_for_kanban():
    pedidos = (PedidoCompra.query
               .order_by(PedidoCompra.posicao, PedidoCompra.id)
               .all())

    updated = False
    for pedido in pedidos:
        normalized = normalize_pedido_status(pedido.status) or 'pendente'
        if pedido.status != normalized:
            pedido.status = normalized
            updated = True

    if updated:
        db.session.commit()

    return pedidos


def build_obras_overview_cards():
    """Build data cards for the principal page grouped by obra."""
    obras, obras_enabled = safe_obras_list()
    pedidos = (PedidoCompra.query
               .order_by(PedidoCompra.data_criacao.desc())
               .all())

    pedidos_por_obra_id = defaultdict(list)
    pedidos_por_nome = defaultdict(list)
    for pedido in pedidos:
        if pedido.obra_id:
            pedidos_por_obra_id[pedido.obra_id].append(pedido)
        nome_key = (pedido.obra or '').strip().lower()
        if nome_key:
            pedidos_por_nome[nome_key].append(pedido)

    cards = []
    if obras_enabled and obras:
        for obra in obras:
            nome_key = (obra.nome or '').strip().lower()
            pedidos_obra = list(pedidos_por_obra_id.get(obra.id, []))
            if not pedidos_obra and nome_key:
                pedidos_obra = list(pedidos_por_nome.get(nome_key, []))
            cards.append(_build_obra_card(obra.nome, obra.endereco, pedidos_obra))
    else:
        for nome_key, pedidos_obra in pedidos_por_nome.items():
            if not pedidos_obra:
                continue
            cards.append(_build_obra_card(pedidos_obra[0].obra, None, pedidos_obra))

    cards.sort(key=lambda item: (item['nome'] or '').lower())
    return cards, obras_enabled


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
# Diretório legado de upload usado por versões antigas.
LEGACY_UPLOAD_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads'))
# Diretório para avatares de usuário
AVATAR_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'media', 'avatars'))
os.makedirs(AVATAR_FOLDER, exist_ok=True)
# Diretório para imagens de capa de perfil
COVER_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'media', 'covers'))
os.makedirs(COVER_FOLDER, exist_ok=True)

ALLOWED_GENERIC_ATTACHMENTS = {'pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx', 'xls', 'xlsx', 'txt'}


def _is_allowed_attachment(filename):
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in ALLOWED_GENERIC_ATTACHMENTS


def _store_attachment_file(uploaded_file, prefix):
    original_filename = secure_filename(uploaded_file.filename or '')
    if not original_filename:
        return None

    if not _is_allowed_attachment(original_filename):
        return None

    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
    stored_filename = f"{prefix}_{timestamp}_{uuid4().hex[:8]}_{original_filename}"
    save_path = os.path.join(UPLOAD_FOLDER, stored_filename)
    uploaded_file.save(save_path)

    return {
        'original_filename': original_filename,
        'stored_filename': stored_filename,
        'content_type': uploaded_file.content_type,
        'file_size': os.path.getsize(save_path) if os.path.exists(save_path) else None,
    }


def _serialize_attachment_record(record):
    return {
        'id': record.id,
        'name': record.original_filename,
        'stored_filename': record.stored_filename,
        'url': url_for('home_blueprint.download_attachment', filename=record.stored_filename),
        'content_type': record.content_type or '',
        'file_size': record.file_size or 0,
    }


def _resolve_existing_attachment_file(stored_filename):
    """Resolve o caminho físico de um anexo em pastas atuais e legadas."""
    if not stored_filename:
        return None

    safe_name = Path(stored_filename).name
    if safe_name != stored_filename:
        return None

    for base_dir in (UPLOAD_FOLDER, ORCAMENTO_FOLDER, LEGACY_UPLOAD_FOLDER):
        candidate = os.path.join(base_dir, safe_name)
        if os.path.isfile(candidate):
            return candidate
    return None


def _store_orcamento_file(uploaded_file, prefix):
    original_filename = secure_filename(uploaded_file.filename or '')
    if not original_filename:
        return None

    if not _is_allowed_attachment(original_filename):
        return None

    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
    stored_filename = f"{prefix}_{timestamp}_{uuid4().hex[:8]}_{original_filename}"
    save_path = os.path.join(ORCAMENTO_FOLDER, stored_filename)
    uploaded_file.save(save_path)

    return {
        'original_filename': original_filename,
        'stored_filename': stored_filename,
        'content_type': uploaded_file.content_type,
        'file_size': os.path.getsize(save_path) if os.path.exists(save_path) else None,
    }


def _serialize_orcamento_attachment_record(record):
    return {
        'id': record.id,
        'name': record.original_filename,
        'stored_filename': record.stored_filename,
        'url': url_for('home_blueprint.download_orcamento', filename=record.stored_filename),
        'content_type': record.content_type or '',
        'file_size': record.file_size or 0,
    }


def _collect_compra_attachments(compra):
    attachments = []
    for att in (compra.attachments or []):
        attachments.append(_serialize_orcamento_attachment_record(att))

    # Compatibilidade com registros antigos com apenas um anexo.
    if compra.attachment_path and not any(a['stored_filename'] == compra.attachment_path for a in attachments):
        attachments.append({
            'id': 0,
            'name': compra.attachment_path,
            'stored_filename': compra.attachment_path,
            'url': url_for('home_blueprint.download_orcamento', filename=compra.attachment_path),
            'content_type': '',
            'file_size': 0,
        })
    return attachments


def _collect_completed_task_attachments(completed_task):
    attachments = []
    for att in (completed_task.attachments or []):
        attachments.append(_serialize_attachment_record(att))

    # Compatibilidade com registros legados que usam somente attachment_path.
    if completed_task.attachment_path and not any(a['stored_filename'] == completed_task.attachment_path for a in attachments):
        attachments.append({
            'id': 0,
            'name': completed_task.attachment_path,
            'stored_filename': completed_task.attachment_path,
            'url': url_for('home_blueprint.download_attachment', filename=completed_task.attachment_path),
            'content_type': '',
            'file_size': 0,
        })
    return attachments


def _collect_finance_attachments(completed_task):
    """Coleta anexos do financeiro com fallback para o serviço de origem."""
    attachments = _collect_completed_task_attachments(completed_task)
    if attachments:
        return attachments

    if not completed_task or not completed_task.original_task_id:
        return attachments

    workflow = CompraWorkflow.query.filter_by(pedido_id=completed_task.original_task_id).first()
    if not workflow or not workflow.compra:
        return attachments

    compra = workflow.compra
    for att in (compra.attachments or []):
        attachments.append({
            'id': att.id,
            'name': att.original_filename,
            'stored_filename': att.stored_filename,
            'url': url_for('home_blueprint.download_attachment', filename=att.stored_filename),
            'content_type': att.content_type or '',
            'file_size': att.file_size or 0,
        })

    if not attachments and compra.attachment_path:
        attachments.append({
            'id': 0,
            'name': Path(compra.attachment_path).name,
            'stored_filename': Path(compra.attachment_path).name,
            'url': url_for('home_blueprint.download_attachment', filename=Path(compra.attachment_path).name),
            'content_type': '',
            'file_size': 0,
        })

    return attachments


def _parse_currency_to_float(raw_value):
    if raw_value is None:
        return None

    text = str(raw_value).strip()
    if not text:
        return None

    text = re.sub(r'[^0-9,.\-]', '', text)
    if not text:
        return None

    if ',' in text and '.' in text:
        text = text.replace('.', '').replace(',', '.')
    elif ',' in text:
        text = text.replace(',', '.')

    try:
        return float(Decimal(text))
    except (InvalidOperation, ValueError):
        return None


def _resolve_completed_task_orcamento_valor(completed_task):
    """Resolve o valor do orçamento para uma linha do Financeiro."""
    if not completed_task:
        return None

    source_texts = (completed_task.observations, completed_task.description)

    for source_text in source_texts:
        if not source_text:
            continue
        compra_match = re.search(r'servico\s*/?\s*orcamento\s*#\s*(\d+)', source_text, flags=re.IGNORECASE)
        if not compra_match:
            continue
        try:
            compra_id = int(compra_match.group(1))
        except (TypeError, ValueError):
            continue

        compra = Compra.query.filter_by(id=compra_id, usuario_id=completed_task.usuario_id).first()
        if not compra:
            compra = Compra.query.filter_by(id=compra_id).first()
        if compra and compra.valor is not None:
            try:
                return float(compra.valor)
            except (TypeError, ValueError):
                continue

    for source_text in source_texts:
        if not source_text:
            continue
        match = re.search(r'valor\s*:\s*r?\$?\s*([0-9.,]+)', source_text, flags=re.IGNORECASE)
        if match:
            parsed = _parse_currency_to_float(match.group(1))
            if parsed is not None:
                return parsed

    if completed_task.original_task_id:
        workflows = CompraWorkflow.query.filter_by(pedido_id=completed_task.original_task_id).all()
        candidates = [wf for wf in workflows if wf.compra and wf.compra.valor is not None]

        if len(candidates) == 1:
            try:
                return float(candidates[0].compra.valor)
            except (TypeError, ValueError):
                pass

        if len(candidates) > 1 and completed_task.data_conclusao:
            prior = [wf for wf in candidates if wf.data_aprovacao and wf.data_aprovacao <= completed_task.data_conclusao]
            basis = prior if prior else [wf for wf in candidates if wf.data_aprovacao]
            if basis:
                nearest = min(
                    basis,
                    key=lambda wf: abs((completed_task.data_conclusao - wf.data_aprovacao).total_seconds())
                )
                try:
                    return float(nearest.compra.valor)
                except (TypeError, ValueError):
                    pass

    return None


@blueprint.route('/uploads/<path:filename>')
@login_required
def download_attachment(filename):
    """Serve um arquivo anexado a uma tarefa concluída.

    Prioriza os anexos salvos em ``UPLOAD_FOLDER`` e oferece um fallback
    para o diretório legado ``apps/static/uploads`` usado anteriormente.
    """
    safe_name = Path(filename).name
    if safe_name != filename:
        abort(404)

    if os.path.isfile(os.path.join(UPLOAD_FOLDER, safe_name)):
        return send_from_directory(UPLOAD_FOLDER, safe_name, as_attachment=True)

    if os.path.isfile(os.path.join(ORCAMENTO_FOLDER, safe_name)):
        return send_from_directory(ORCAMENTO_FOLDER, safe_name, as_attachment=True)

    if os.path.isfile(os.path.join(LEGACY_UPLOAD_FOLDER, safe_name)):
        return send_from_directory(LEGACY_UPLOAD_FOLDER, safe_name, as_attachment=True)

    abort(404)

# Novo endpoint para baixar anexos de orçamentos.
@blueprint.route('/orcamentos/<path:filename>')
@login_required
def download_orcamento(filename):
    """Serve um arquivo anexo de orçamento armazenado em ORCAMENTO_FOLDER."""
    return send_from_directory(ORCAMENTO_FOLDER, filename, as_attachment=True)


@blueprint.route('/servicos/<int:compra_id>/arquivos')
@login_required
def download_servico_attachments_zip(compra_id):
    """Baixa todos os arquivos anexos de um serviço (orçamento) em um único ZIP."""
    compra = Compra.query.filter_by(id=compra_id, usuario_id=current_user.id).first_or_404()
    attachments = _collect_compra_attachments(compra)
    if not attachments:
        abort(404)

    zip_buffer = io.BytesIO()
    used_names = set()
    with zipfile.ZipFile(zip_buffer, 'w', compression=zipfile.ZIP_DEFLATED) as zipf:
        for att in attachments:
            stored_filename = att.get('stored_filename')
            if not stored_filename:
                continue
            file_path = os.path.join(ORCAMENTO_FOLDER, stored_filename)
            if not os.path.isfile(file_path):
                continue

            original_name = secure_filename(att.get('name') or stored_filename) or stored_filename
            base, ext = os.path.splitext(original_name)
            arcname = original_name
            idx = 1
            while arcname in used_names:
                arcname = f"{base}_{idx}{ext}"
                idx += 1
            used_names.add(arcname)
            zipf.write(file_path, arcname=arcname)

    if not used_names:
        abort(404)

    zip_buffer.seek(0)
    filename = f"arquivos_servico_{compra_id}.zip"
    return send_file(zip_buffer, as_attachment=True, download_name=filename, mimetype='application/zip')

@blueprint.route('/avatars/<path:filename>')
@login_required
def download_avatar(filename):
    """Serve avatar de usuário."""
    return send_from_directory(AVATAR_FOLDER, filename, as_attachment=False)

@blueprint.route('/covers/<path:filename>')
@login_required
def download_cover(filename):
    """Serve imagem de capa de usuário."""
    return send_from_directory(COVER_FOLDER, filename, as_attachment=False)


@blueprint.route('/financeiro/<int:completed_task_id>/anexos')
@login_required
def download_financeiro_attachments_zip(completed_task_id):
    """Baixa todos os anexos de um registro do Financeiro em um único ZIP."""
    completed = CompletedTask.query.filter_by(id=completed_task_id, usuario_id=current_user.id).first_or_404()
    attachments = _collect_finance_attachments(completed)

    if not attachments:
        abort(404)

    zip_buffer = io.BytesIO()
    used_names = set()

    with zipfile.ZipFile(zip_buffer, 'w', compression=zipfile.ZIP_DEFLATED) as zipf:
        for att in attachments:
            stored_filename = att.get('stored_filename')
            if not stored_filename:
                continue
            file_path = _resolve_existing_attachment_file(stored_filename)
            if not file_path:
                continue

            original_name = secure_filename(att.get('name') or stored_filename) or stored_filename
            base, ext = os.path.splitext(original_name)
            arcname = original_name
            idx = 1
            while arcname in used_names:
                arcname = f"{base}_{idx}{ext}"
                idx += 1
            used_names.add(arcname)
            zipf.write(file_path, arcname=arcname)

    if not used_names:
        abort(404)

    zip_buffer.seek(0)
    filename = f"arquivos_financeiro_{completed_task_id}.zip"
    return send_file(zip_buffer, as_attachment=True, download_name=filename, mimetype='application/zip')

@blueprint.route('/pedidos-compra')
@login_required
def pedidos_compra():
    """Exibe o quadro Kanban de pedidos de compra."""
    pedidos = load_pedidos_for_kanban()
    return render_template('home/pedidos_compra_kanban.html', pedidos=pedidos, segment='pedidos')

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
            status=normalize_pedido_status(request.form.get('status')) or 'pendente',
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
    attach_local_datetime_fields(pedido, ['data_criacao'])
    dias_decorridos = None
    if pedido.data_criacao_local:
        try:
            dias_decorridos = (datetime.now(LOCAL_TIMEZONE).date() - pedido.data_criacao_local.date()).days
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
    data_criacao_local = utc_naive_to_local(pedido.data_criacao)
    data_criacao_local_str = data_criacao_local.strftime('%d/%m/%Y %H:%M') if data_criacao_local else '-'

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
    write_key_value("Data de criação", data_criacao_local_str)
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
        pedido.status = normalize_pedido_status(request.form.get('status')) or 'pendente'
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
            status=normalize_pedido_status(dados.get('status')) or 'pendente',
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
    valid_statuses = ['Pendente', 'Em Progresso', 'Finalizado']
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
        valid_statuses = ['Pendente', 'Em Progresso', 'Finalizado']
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
    valid_statuses = ['Pendente', 'Em Progresso', 'Finalizado']
    if status not in valid_statuses:
        return jsonify({'success': False, 'message': 'Status inválido'}), 400
    task.status = status

    # Arquivo opcional
    attachment_file = request.files.get('attachment') if 'attachment' in request.files else None
    attachment_path = None

    # Se o cliente enviar um anexo opcional, salva junto ao registro concluído.
    if attachment_file and attachment_file.filename:
        # Salva arquivo
        filename = secure_filename(attachment_file.filename)
        timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        filename = f"{task.id}_{timestamp}_{filename}"
        upload_dir = UPLOAD_FOLDER
        os.makedirs(upload_dir, exist_ok=True)
        file_full = os.path.join(upload_dir, filename)
        attachment_file.save(file_full)
        attachment_path = filename

    if status != 'Finalizado':
        return jsonify({'success': False, 'message': 'A tarefa precisa estar em Finalizado para concluir.'}), 400

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
        attach_local_datetime_fields(t, ['data_criacao', 'data_conclusao'])
        if t.data_criacao_local and t.data_conclusao_local:
            # Calcula diferença em dias completos entre as datas
            duration_days = (t.data_conclusao_local.date() - t.data_criacao_local.date()).days
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
@blueprint.route('/servicos')
@login_required
def compras():
    """Exibe a página de serviços (orçamentos) com todos os registros disponíveis."""
    sync_csv_fornecedores(current_user.id)
    compras = (Compra.query
               .filter_by(usuario_id=current_user.id)
               .order_by(Compra.data_criacao.desc())
               .all())
    for compra in compras:
        attach_local_datetime_fields(compra, ['data_criacao'])
        compra.data_criacao_local_date_str = (
            compra.data_criacao_local.strftime('%d/%m/%Y') if compra.data_criacao_local else ''
        )
        compra.servico_attachments = _collect_compra_attachments(compra)
        compra.servico_attachments_zip_url = url_for('home_blueprint.download_servico_attachments_zip', compra_id=compra.id)
        workflow = compra.workflow
        compra.obra = workflow.obra_rel if workflow and workflow.obra_rel else None
        compra.pedido_id = workflow.pedido_id if workflow else None
        compra.aprovado = bool(workflow and workflow.pedido_id)

    fornecedores = (Fornecedor.query
                    .filter_by(usuario_id=current_user.id)
                    .order_by(Fornecedor.nome)
                    .all())
    obras, obras_enabled = safe_obras_list(current_user.id)
    return render_template(
        'home/compras.html',
        compras=compras,
        fornecedores=fornecedores,
        obras=obras,
        obras_enabled=obras_enabled,
        segment='servicos'
    )


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

        data = request.get_json(silent=True) or request.form or {}
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
    """Cria um novo serviço (orçamento) com obra vinculada e múltiplos anexos."""
    data = request.form if request.form else (request.get_json() or {})
    fornecedor_id = data.get('fornecedor_id') or data.get('fornecedorId')
    obra_id_raw = data.get('obra_id') or data.get('obraId')
    valor = data.get('valor') or data.get('value')
    novo_fornecedor_nome = data.get('novo_fornecedor') or data.get('novoFornecedor')
    data_orcamento_str = data.get('data') or data.get('data_orcamento') or data.get('dataOrcamento')

    if not obra_id_raw:
        return jsonify({'success': False, 'message': 'Obra é obrigatória.'}), 400
    try:
        obra_id = int(obra_id_raw)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Obra inválida.'}), 400

    obra = Obra.query.filter_by(id=obra_id, usuario_id=current_user.id).first()
    if not obra:
        return jsonify({'success': False, 'message': 'Obra não encontrada.'}), 404

    try:
        valor_float = float(valor)
        if valor_float <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Valor inválido para orçamento.'}), 400

    fornecedor = None
    if novo_fornecedor_nome:
        fornecedor = Fornecedor(nome=novo_fornecedor_nome.strip(), usuario_id=current_user.id)
        db.session.add(fornecedor)
        db.session.flush()
        fornecedor_id = fornecedor.id
    else:
        if not fornecedor_id:
            return jsonify({'success': False, 'message': 'Fornecedor é obrigatório.'}), 400
        try:
            fornecedor_id = int(fornecedor_id)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'Fornecedor inválido.'}), 400

        fornecedor = Fornecedor.query.filter_by(id=fornecedor_id, usuario_id=current_user.id).first()
        if not fornecedor:
            return jsonify({'success': False, 'message': 'Fornecedor não encontrado.'}), 404

    data_orcamento = None
    if data_orcamento_str:
        try:
            data_orcamento = datetime.strptime(data_orcamento_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'message': 'Data do orçamento inválida.'}), 400

    compra = Compra(
        fornecedor_id=fornecedor_id,
        valor=valor_float,
        attachment_path=None,
        data_orcamento=data_orcamento,
        usuario_id=current_user.id
    )
    db.session.add(compra)
    db.session.flush()

    workflow = CompraWorkflow(
        compra_id=compra.id,
        obra_id=obra.id,
        pedido_id=None
    )
    db.session.add(workflow)

    uploaded_files = []
    if request.files:
        uploaded_files.extend(request.files.getlist('anexos'))
        uploaded_files.extend(request.files.getlist('attachments'))

        for key in ('anexo', 'attachment'):
            single_file = request.files.get(key)
            if single_file:
                uploaded_files.append(single_file)

    first_attachment = None
    for uploaded in uploaded_files:
        if not uploaded or not uploaded.filename:
            continue

        stored = _store_orcamento_file(uploaded, f"servico{compra.id}")
        if not stored:
            continue

        if first_attachment is None:
            first_attachment = stored['stored_filename']

        att = CompraAttachment(
            compra_id=compra.id,
            original_filename=stored['original_filename'],
            stored_filename=stored['stored_filename'],
            content_type=stored['content_type'],
            file_size=stored['file_size']
        )
        db.session.add(att)

    if first_attachment:
        compra.attachment_path = first_attachment

    db.session.commit()
    return jsonify({'success': True, 'compra_id': compra.id})


@blueprint.route('/api/compras/<int:compra_id>/aprovar', methods=['POST'])
@login_required
def api_aprovar_compra(compra_id):
    """Encaminha um serviço (orçamento) para Pedidos de Compra na coluna Pendente."""
    try:
        compra = Compra.query.filter_by(id=compra_id, usuario_id=current_user.id).first_or_404()
        workflow = compra.workflow
        if not workflow:
            return jsonify({'success': False, 'message': 'Serviço sem obra vinculada.'}), 400
        if workflow.pedido_id:
            return jsonify({
                'success': False,
                'message': 'Este serviço já foi encaminhado ao Pedido de Compra.',
                'pedido_id': workflow.pedido_id
            }), 400

        obra = workflow.obra_rel or Obra.query.filter_by(id=workflow.obra_id).first()
        if not obra:
            return jsonify({'success': False, 'message': 'Obra vinculada não encontrada.'}), 404

        responsavel = (current_user.first_name or current_user.username or 'Responsavel').strip()
        data_necessidade = compra.data_orcamento or datetime.utcnow().date()
        observacoes = (
            f"Encaminhado automaticamente do servico/orcamento #{compra.id}. "
            f"Fornecedor: {compra.fornecedor.nome if compra.fornecedor else '-'} | "
            f"Valor: R$ {compra.valor:.2f}"
        )
        posicao_atual = (db.session.query(func.max(PedidoCompra.posicao))
                         .filter_by(usuario_id=current_user.id, status='pendente')
                         .scalar())
        proxima_posicao = (posicao_atual + 1) if posicao_atual is not None else 0

        pedido = PedidoCompra(
            obra=obra.nome or 'Obra',
            obra_id=obra.id,
            obra_endereco=obra.endereco,
            responsavel=responsavel,
            prioridade='media',
            data_necessidade=data_necessidade,
            status='pendente',
            observacoes=observacoes,
            usuario_id=current_user.id,
            posicao=proxima_posicao
        )
        db.session.add(pedido)
        db.session.flush()

        item_nome = f"Servico - {compra.fornecedor.nome if compra.fornecedor else 'Fornecedor'}"
        item = ItemPedido(
            pedido_id=pedido.id,
            codigo_item=f"SERV-{compra.id}",
            nome_item=item_nome[:200],
            observacao=f"Originado do servico/orcamento #{compra.id}",
            quantidade=1.0,
            unidade='un'
        )
        db.session.add(item)

        can_store_pedido_attachments = True
        try:
            can_store_pedido_attachments = inspect(db.engine).has_table('pedido_compra_attachments')
        except Exception:
            can_store_pedido_attachments = False

        if can_store_pedido_attachments:
            compra_attachments = list(compra.attachments or [])
            if compra_attachments:
                for att in compra_attachments:
                    db.session.add(PedidoCompraAttachment(
                        pedido_id=pedido.id,
                        original_filename=att.original_filename,
                        stored_filename=att.stored_filename,
                        content_type=att.content_type,
                        file_size=att.file_size
                    ))
            elif compra.attachment_path:
                file_path = _resolve_existing_attachment_file(compra.attachment_path)
                db.session.add(PedidoCompraAttachment(
                    pedido_id=pedido.id,
                    original_filename=Path(compra.attachment_path).name,
                    stored_filename=Path(compra.attachment_path).name,
                    content_type=None,
                    file_size=(os.path.getsize(file_path) if file_path else None)
                ))

        workflow.pedido_id = pedido.id
        workflow.data_aprovacao = datetime.utcnow()

        db.session.commit()
        return jsonify({'success': True, 'pedido_id': pedido.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Erro ao aprovar orçamento: {str(e)}'}), 500


@blueprint.route('/pedidos-compra/kanban')
@login_required
def pedidos_compra_kanban():
    """Exibe o quadro Kanban de pedidos de compra"""
    pedidos = load_pedidos_for_kanban()
    return render_template('home/pedidos_compra_kanban.html', pedidos=pedidos, segment='pedidos')


@blueprint.route('/api/pedidos-compra/<int:pedido_id>/status', methods=['PATCH'])
@login_required
def atualizar_status_pedido(pedido_id):
    """Atualiza o status e a posição de um pedido de compra (Kanban)"""
    data = request.get_json() or {}
    novo_status = normalize_pedido_status(data.get('status'))
    nova_posicao = data.get('posicao', 0)
    # Garantir que o pedido existe e pertence ao usuário atual
    pedido = PedidoCompra.query.filter_by(id=pedido_id, usuario_id=current_user.id).first_or_404()
    # Validar o status
    if novo_status not in PEDIDO_STATUS_VALID:
        return jsonify({'success': False, 'message': 'Status inválido'}), 400
    # Atualizar status e posição
    pedido.status = novo_status
    try:
        pedido.posicao = int(nova_posicao)
    except (TypeError, ValueError):
        pedido.posicao = 0
    db.session.commit()
    return jsonify({'success': True})


@blueprint.route('/api/pedidos-compra/<int:pedido_id>/attachments', methods=['GET', 'POST'])
@login_required
def pedido_compra_attachments(pedido_id):
    """Lista e cadastra anexos de um pedido de compra."""
    pedido = PedidoCompra.query.filter_by(id=pedido_id, usuario_id=current_user.id).first_or_404()

    if request.method == 'GET':
        attachments = (PedidoCompraAttachment.query
                       .filter_by(pedido_id=pedido.id)
                       .order_by(PedidoCompraAttachment.data_criacao.asc())
                       .all())
        return jsonify({
            'success': True,
            'attachments': [_serialize_attachment_record(att) for att in attachments],
            'total_attachments': len(attachments)
        })

    uploaded_files = request.files.getlist('attachments')
    if not uploaded_files:
        return jsonify({'success': False, 'message': 'Nenhum arquivo enviado.'}), 400

    created = []
    rejected = []
    for uploaded in uploaded_files:
        if not uploaded or not uploaded.filename:
            continue

        stored = _store_attachment_file(uploaded, f"pedido{pedido.id}")
        if not stored:
            rejected.append(uploaded.filename)
            continue

        record = PedidoCompraAttachment(
            pedido_id=pedido.id,
            original_filename=stored['original_filename'],
            stored_filename=stored['stored_filename'],
            content_type=stored['content_type'],
            file_size=stored['file_size']
        )
        db.session.add(record)
        created.append(record)

    if not created:
        return jsonify({
            'success': False,
            'message': 'Nenhum anexo válido foi enviado.',
            'rejected': rejected
        }), 400

    db.session.commit()

    attachments = (PedidoCompraAttachment.query
                   .filter_by(pedido_id=pedido.id)
                   .order_by(PedidoCompraAttachment.data_criacao.asc())
                   .all())
    return jsonify({
        'success': True,
        'attachments': [_serialize_attachment_record(att) for att in attachments],
        'total_attachments': len(attachments),
        'rejected': rejected
    })


@blueprint.route('/api/pedidos-compra/<int:pedido_id>/complete', methods=['POST'])
@login_required
def concluir_pedido_compra(pedido_id):
    """Conclui um pedido entregue e move o registro para Financeiro."""
    pedido = PedidoCompra.query.filter_by(id=pedido_id, usuario_id=current_user.id).first_or_404()

    status = normalize_pedido_status(pedido.status) or 'pendente'
    if status != 'entregue':
        return jsonify({'success': False, 'message': 'O pedido precisa estar em Entregue para concluir.'}), 400

    completion_time = datetime.utcnow()
    duration_seconds = int((completion_time - pedido.data_criacao).total_seconds()) if pedido.data_criacao else None
    itens_count = len(pedido.itens or [])
    pedido_attachments = list(pedido.attachments or [])
    if not pedido_attachments:
        workflow = CompraWorkflow.query.filter_by(pedido_id=pedido.id).first()
        if workflow and workflow.compra:
            pedido_attachments = list(workflow.compra.attachments or [])
            if not pedido_attachments and workflow.compra.attachment_path:
                fallback_name = Path(workflow.compra.attachment_path).name
                fallback_path = _resolve_existing_attachment_file(fallback_name)
                pedido_attachments = [{
                    'original_filename': fallback_name,
                    'stored_filename': fallback_name,
                    'content_type': None,
                    'file_size': (os.path.getsize(fallback_path) if fallback_path else None)
                }]

    def _att_field(att, field_name, default=None):
        if isinstance(att, dict):
            return att.get(field_name, default)
        return getattr(att, field_name, default)

    data_necessidade = pedido.data_necessidade.strftime('%d/%m/%Y') if pedido.data_necessidade else '-'
    prioridade = (pedido.prioridade or '-').title()

    completed = CompletedTask(
        original_task_id=pedido.id,
        title=f"Pedido #{pedido.id} - {pedido.obra or 'Obra sem nome'}",
        description=f"Obra: {pedido.obra or '-'} | Itens: {itens_count} | Data necessidade: {data_necessidade}",
        observations=pedido.observacoes,
        priority=prioridade,
        assignee=pedido.responsavel,
        due_date=pedido.data_necessidade,
        status='Aguardando Nota/Boleto',
        data_criacao=pedido.data_criacao,
        data_conclusao=completion_time,
        duration_seconds=duration_seconds,
        usuario_id=pedido.usuario_id,
        attachment_path=(_att_field(pedido_attachments[0], 'stored_filename') if pedido_attachments else None)
    )

    db.session.add(completed)
    db.session.flush()

    for att in pedido_attachments:
        stored_filename = _att_field(att, 'stored_filename')
        if not stored_filename:
            continue
        original_filename = _att_field(att, 'original_filename') or stored_filename
        completed_attachment = CompletedTaskAttachment(
            completed_task_id=completed.id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            content_type=_att_field(att, 'content_type'),
            file_size=_att_field(att, 'file_size')
        )
        db.session.add(completed_attachment)

    db.session.delete(pedido)
    db.session.commit()

    return jsonify({'success': True, 'completed_id': completed.id})


@blueprint.route('/index')
@login_required
def index():
    return redirect(url_for('home_blueprint.principal'))


@blueprint.route('/principal')
@login_required
def principal():
    obra_cards, obras_enabled = build_obras_overview_cards()

    total_pedidos = sum(card['total_pedidos'] for card in obra_cards)
    total_entregues = sum(card['status']['entregue'] for card in obra_cards)
    total_em_aberto = max(total_pedidos - total_entregues, 0)

    compras_total = 0
    try:
        compras_total = Compra.query.count()
    except (OperationalError, ProgrammingError):
        db.session.rollback()
        compras_total = 0

    recados = []
    recados_hoje = 0
    try:
        recados = (RecadoMural.query
                   .order_by(RecadoMural.data_criacao.desc())
                   .limit(30)
                   .all())

        for recado in recados:
            local_dt = utc_naive_to_local(recado.data_criacao)
            recado.data_criacao_local = local_dt
            recado.data_criacao_local_str = local_dt.strftime('%d/%m/%Y %H:%M') if local_dt else ''

        inicio_dia_local = datetime.now(LOCAL_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
        inicio_dia_utc = inicio_dia_local.astimezone(timezone.utc).replace(tzinfo=None)
        recados_hoje = (RecadoMural.query
                        .filter(RecadoMural.data_criacao >= inicio_dia_utc)
                        .count())
    except (OperationalError, ProgrammingError):
        db.session.rollback()
        recados = []
        recados_hoje = 0

    return render_template(
        'home/principal.html',
        segment='principal',
        obra_cards=obra_cards,
        obras_enabled=obras_enabled,
        total_obras=len(obra_cards),
        total_pedidos=total_pedidos,
        total_entregues=total_entregues,
        total_em_aberto=total_em_aberto,
        compras_total=compras_total,
        recados=recados,
        recados_hoje=recados_hoje
    )


@blueprint.route('/principal/recados', methods=['POST'])
@login_required
def criar_recado_principal():
    mensagem = (request.form.get('mensagem') or '').strip()
    if not mensagem:
        return redirect(url_for('home_blueprint.principal'))

    recado = RecadoMural(
        mensagem=mensagem[:1000],
        usuario_id=current_user.id
    )
    try:
        db.session.add(recado)
        db.session.commit()
    except Exception:
        db.session.rollback()

    return redirect(url_for('home_blueprint.principal'))


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

    # Normaliza status antigos para o novo fluxo sem dependência de financeiro.
    status_legacy = {'Entregue', 'Aguardando Nota/Boleto'}
    updated = False
    for task in tasks:
        if task.status in status_legacy:
            task.status = 'Finalizado'
            updated = True
    if updated:
        db.session.commit()

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


@blueprint.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """Exibe e atualiza os dados de perfil do usuário logado."""
    user = current_user
    if request.method == 'POST':
        try:
            user.first_name = request.form.get('first_name', '').strip() or None
            user.last_name = request.form.get('last_name', '').strip() or None
            user.phone = request.form.get('phone', '').strip() or None
            user.address = request.form.get('address', '').strip() or None
            user.city = request.form.get('city', '').strip() or None
            user.country = request.form.get('country', '').strip() or None
            user.postal_code = request.form.get('postal_code', '').strip() or None
            user.bio = request.form.get('bio', '').strip() or None

            # Foto de perfil
            avatar_file = request.files.get('avatar') if request.files else None
            if avatar_file and avatar_file.filename:
                filename = secure_filename(avatar_file.filename)
                timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
                ext = os.path.splitext(filename)[1]
                final_name = f"user{user.id}_{timestamp}{ext}"
                save_path = os.path.join(AVATAR_FOLDER, final_name)
                avatar_file.save(save_path)
                user.avatar_path = final_name

            # Imagem de capa
            cover_file = request.files.get('cover') if request.files else None
            if cover_file and cover_file.filename:
                filename = secure_filename(cover_file.filename)
                timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
                ext = os.path.splitext(filename)[1]
                final_name = f"cover{user.id}_{timestamp}{ext}"
                save_path = os.path.join(COVER_FOLDER, final_name)
                cover_file.save(save_path)
                user.cover_path = final_name

            db.session.commit()
            flash('Perfil atualizado com sucesso.', 'success')
        except Exception as exc:
            db.session.rollback()
            flash(f'Erro ao salvar perfil: {exc}', 'danger')
        return redirect(url_for('home_blueprint.profile'))

    return render_template('home/profile.html', user=user, segment='profile')

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
    """Lista registros concluídos que aguardam nota ou boleto."""
    aguardando = (CompletedTask.query
                  .filter_by(status='Aguardando Nota/Boleto', usuario_id=current_user.id)
                  .order_by(CompletedTask.data_conclusao.desc())
                  .all())
    for tarefa in aguardando:
        attach_local_datetime_fields(tarefa, ['data_criacao', 'data_conclusao'])
        if tarefa.data_criacao_local and tarefa.data_conclusao_local:
            duration_days = (tarefa.data_conclusao_local.date() - tarefa.data_criacao_local.date()).days
            if duration_days < 0:
                duration_days = 0
            tarefa.duration_display = f"{duration_days} dia{'s' if duration_days != 1 else ''}"
        else:
            tarefa.duration_display = ''

        tarefa.orcamento_valor = _resolve_completed_task_orcamento_valor(tarefa)
        tarefa.finance_attachments = _collect_finance_attachments(tarefa)
        tarefa.finance_attachments_zip_url = url_for('home_blueprint.download_financeiro_attachments_zip', completed_task_id=tarefa.id)
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
